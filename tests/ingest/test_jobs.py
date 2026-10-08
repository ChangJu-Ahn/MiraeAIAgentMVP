from __future__ import annotations

import copy
import io
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
from contextlib import nullcontext

from pypdf import PdfWriter

from ingest.models import ParsedDoc, ParsedParagraph


class MemoryStore:
    endpoint = "https://function.example"

    def __init__(self, pages=51):
        writer = PdfWriter()
        for _ in range(pages):
            writer.add_blank_page(width=72, height=72)
        stream = io.BytesIO()
        writer.write(stream)
        self.pdf = stream.getvalue()
        self.values = {}
        self.manifest = None
        self.pending = False
        self.etag = "version-1"
        self.leased = False

    def source(self, name):
        def acquire(**kwargs):
            self.leased = True
            return SimpleNamespace(renew=lambda: None, release=lambda: setattr(self, "leased", False))
        return SimpleNamespace(
            get_blob_properties=lambda **kw: SimpleNamespace(
                etag=self.etag, metadata={}, size=len(self.pdf),
            ),
            download_blob=lambda **kw: SimpleNamespace(readall=lambda: self.pdf),
            acquire_lease=acquire,
        )

    def read_json(self, name):
        return copy.deepcopy(self.values.get(name))

    def write_json(self, name, value):
        self.values[name] = copy.deepcopy(value)

    def write_asset(self, name, data, content_type):
        self.values[name] = data

    def read_asset(self, name):
        return self.values[name]

    def read_manifest(self, doc_id):
        return self.manifest

    def write_manifest(self, doc_id, record):
        self.manifest = record

    def has_pending(self, doc_id):
        return self.pending

    def write_pending(self, doc_id, fingerprint):
        self.pending = True

    def clear_pending(self, doc_id):
        self.pending = False


def make_job():
    from ingest.jobs import IngestionJob
    from ingest.blob import DocumentMetadata
    return IngestionJob(
        job_id="job", blob_name="input.pdf", source_etag="version-1",
        metadata=DocumentMetadata(doc_id="doc"),
    )


def test_page_ranges_checkpoint_and_resume_without_reanalyzing(monkeypatch):
    from ingest import jobs
    store = MemoryStore()
    job = make_job()
    calls = []

    def analyze(pdf, doc_id, *, pages, **kwargs):
        calls.append(pages)
        first, last = map(int, pages.split("-"))
        return ParsedDoc(doc_id=doc_id, paragraphs=[
            ParsedParagraph(role=None, content=f"Page {page}", page=page, offset=page-first)
            for page in range(first, last+1)
        ], tables=[])

    monkeypatch.setattr(jobs, "analyze_pdf", analyze)
    jobs.advance_job(job, store)
    assert job.total_pages == 51 and job.stage == "layout"
    before = job.model_copy(deep=True)
    jobs.advance_job(job, store)
    assert job.next_page == 26
    jobs.advance_job(before, store)  # Simulate a crash after saving the part but before the cursor.
    assert before.next_page == 26 and calls == ["1-25"]
    jobs.advance_job(job, store)
    jobs.advance_job(job, store)
    assert calls == ["1-25", "26-50", "51-51"]
    assert job.stage == "plan"
    merged = jobs.merge_layout_parts(job, store)
    assert [p.page for p in merged.paragraphs] == list(range(1, 52))
    offsets = [p.offset for p in merged.paragraphs]
    assert offsets == sorted(set(offsets))


def test_embedding_batches_do_not_delete_prior_ranges_and_finalize_once(monkeypatch):
    from ingest import jobs
    store = MemoryStore(pages=3)
    job = make_job()
    monkeypatch.setattr(jobs, "analyze_pdf", lambda *a, **kw: ParsedDoc(
        doc_id="doc", paragraphs=[
            ParsedParagraph(role=None, content=f"Page {i}", page=i, offset=i)
            for i in range(1, 4)
        ], tables=[],
    ))
    monkeypatch.setattr(jobs, "ensure_indexes", lambda: None)
    embedding = MagicMock(side_effect=lambda texts: [[0.0]*3072 for _ in texts])
    upload = MagicMock(return_value=3)
    cleanup = MagicMock()
    monkeypatch.setattr(jobs, "embed_texts", embedding)
    monkeypatch.setattr(jobs, "upload_chunks", upload)
    monkeypatch.setattr(jobs, "delete_stale_chunks", cleanup)
    for _ in range(3):
        jobs.advance_job(job, store)
    assert job.stage == "embedding"
    before = job.model_copy(deep=True)
    jobs.advance_job(job, store)
    assert job.next_chunk == 3 and job.stage == "finalize"
    cleanup.assert_not_called()
    assert not store.manifest
    jobs.advance_job(before, store)  # A persisted upload receipt prevents a second model call.
    assert embedding.call_count == 1 and upload.call_count == 1
    assert upload.call_args.kwargs == {}
    jobs.advance_job(job, store)
    assert job.status == "completed" and store.manifest["chunks"] == 3
    assert not store.pending
    cleanup.assert_called_once()
    assert cleanup.call_args.args[1]["narrative"] == {"doc-0", "doc-1", "doc-2"}


def test_changed_source_supersedes_old_job_before_any_processing():
    from ingest import jobs
    store = MemoryStore()
    job = make_job()
    store.etag = "new-version"
    jobs.advance_job(job, store)
    assert job.status == "superseded"
    assert store.values == {}


def test_existing_completed_document_is_not_processed_again():
    from ingest import jobs
    from ingest.blob import document_fingerprint
    store = MemoryStore()
    job = make_job()
    store.manifest = {"fingerprint": document_fingerprint(store.pdf, job.metadata)}
    jobs.advance_job(job, store)
    assert job.status == "completed"
    assert store.values == {}


def test_transient_step_failure_keeps_cursor_and_records_retry(monkeypatch):
    from ingest import jobs
    job = make_job()
    job.stage = "layout"
    job.next_page = 26
    store = MagicMock()
    store.jobs.return_value = [job]
    store.assets.get_blob_client.return_value.download_blob.return_value.readall.return_value = job.model_dump_json()
    saved = []
    store.write_job.side_effect = lambda value, **kw: saved.append(value.model_copy(deep=True))
    monkeypatch.setattr(jobs, "source_lease", lambda blob: nullcontext("lease"))
    monkeypatch.setattr(jobs, "advance_job", MagicMock(side_effect=RuntimeError("rate limited")))
    result = jobs.process_next_job(store=store)
    assert result.status == "retrying"
    assert result.next_page == 26
    assert result.error == "rate limited" and result.retry_after > jobs.utcnow()
    assert saved[0].status == "running" and saved[-1].status == "retrying"
    store.jobs.return_value = [result]
    assert jobs.process_next_job(store=store) is None
    assert jobs.advance_job.call_count == 1


def test_enqueue_only_creates_a_job_and_deduplicates_same_etag():
    from azure.core.exceptions import ResourceExistsError
    from ingest import jobs
    store = MagicMock()
    store.source.return_value.get_blob_properties.return_value = SimpleNamespace(
        etag="etag", metadata={}, size=123,
    )
    first = jobs.enqueue_blob("input.pdf", store=store)
    store.source.return_value.download_blob.assert_not_called()
    store.write_job.assert_called_once_with(first, create=True)
    store.write_job.side_effect = ResourceExistsError("Already exists")
    store.read_json.return_value = first.model_dump(mode="json")
    repeated = jobs.enqueue_blob("input.pdf", store=store)
    assert repeated.job_id == first.job_id


def test_figure_survives_range_checkpoint_and_keeps_global_id(monkeypatch):
    from ingest import jobs, figures
    from ingest.models import ParsedFigure
    store = MemoryStore(pages=1)
    job = make_job()
    png = b"\x89PNG\r\n\x1a\nimage"
    def analyze(pdf, doc_id, **kwargs):
        image = Path(pdf).parent / "figure.png"
        image.write_bytes(png)
        return ParsedDoc(doc_id=doc_id, paragraphs=[], tables=[], figures=[
            ParsedFigure(page=1, polygon=[0,0,1,0,1,1,0,1], image_path=image),
        ])
    monkeypatch.setattr(jobs, "analyze_pdf", analyze)
    monkeypatch.setattr(figures, "describe_figure", lambda image: "Diagram")
    monkeypatch.setattr(jobs, "ensure_indexes", lambda: None)
    monkeypatch.setattr(jobs, "embed_texts", lambda texts: [[0.0]*3072 for _ in texts])
    uploaded = []
    monkeypatch.setattr(jobs, "upload_chunks", lambda chunks: uploaded.extend(chunks))
    monkeypatch.setattr(jobs, "delete_stale_chunks", lambda *args: None)
    for _ in range(3):
        jobs.advance_job(job, store)
    write_json = store.write_json
    failed = [False]
    def temporary_failure(name, value):
        if name.endswith("/chunks.json") and not failed[0]:
            failed[0] = True
            raise RuntimeError("temporary storage failure")
        write_json(name, value)
    store.write_json = temporary_failure
    import pytest
    with pytest.raises(RuntimeError, match="temporary storage"):
        jobs.advance_job(job, store)
    assert job.stage == "figures" and job.next_figure == 0
    for _ in range(3):
        jobs.advance_job(job, store)
    assert job.status == "completed"
    assert uploaded[0].id == "doc-fig-0"
    assert uploaded[0].image_url.endswith("/0")
    image_blob = store.manifest["figures"]["0"]
    assert store.read_asset(image_blob) == png


def test_final_publication_holds_source_lease(monkeypatch):
    from ingest import jobs
    from ingest.run import PreparedDocument
    job = make_job()
    job.stage = "finalize"
    job.fingerprint = "version"
    job.chunk_count = 1
    store = MemoryStore()
    store.values[f"{job.checkpoint_prefix}/prepared.json"] = PreparedDocument(chunks=[]).model_dump()
    store.values[f"{job.checkpoint_prefix}/chunks.json"] = [{"id": "doc-0", "chunk_type": "narrative"}]
    store.values[f"{job.checkpoint_prefix}/document.json"] = ParsedDoc(
        doc_id="doc", paragraphs=[], tables=[],
    ).model_dump()
    def cleanup(*args):
        assert store.leased, "source must be locked through cleanup and publication"
    monkeypatch.setattr(jobs, "delete_stale_chunks", cleanup)
    original_publish = store.write_manifest
    def publish(*args):
        assert store.leased
        original_publish(*args)
    store.write_manifest = publish
    jobs.advance_job(job, store)
    assert job.status == "completed" and not store.leased
