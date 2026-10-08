from __future__ import annotations

import hashlib
import io
import json
import logging
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal
from contextlib import nullcontext

from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
from azure.identity import DefaultAzureCredential
from azure.search.documents import SearchClient
from azure.storage.blob import BlobClient, BlobLeaseClient, ContentSettings
from pydantic import BaseModel, Field
from pypdf import PdfReader

from config.settings import get_settings
from ingest.blob import (
    BlobStore, DocumentMetadata, document_fingerprint, document_metadata, source_lease,
)
from ingest.catalog import annotate_chunks
from ingest.embedder import embed_texts
from ingest.figures import build_figure_chunks
from ingest.indexer import delete_stale_chunks, ensure_indexes, upload_chunks
from ingest.models import Chunk, ParsedDoc
from ingest.parser import analyze_pdf
from ingest.run import PreparedDocument, prepare_document
from ingest.structured_indexer import ensure_structured_indexes, replace_catalog, replace_facts

log = logging.getLogger(__name__)
EMBED_BATCH = 16
MAX_ATTEMPTS = 5


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class IngestionJob(BaseModel):
    job_id: str
    blob_name: str
    source_etag: str
    metadata: DocumentMetadata
    status: Literal["queued", "running", "retrying", "completed", "failed", "superseded"] = "queued"
    stage: Literal["prepare", "layout", "plan", "figures", "embedding", "finalize"] = "prepare"
    page_size: int = Field(default=25, ge=1, le=100)
    embedding_batch_size: int = Field(default=EMBED_BATCH, ge=1, le=32)
    total_pages: int = 0
    next_page: int = 1
    next_figure: int = 0
    figure_count: int = 0
    next_chunk: int = 0
    chunk_count: int = 0
    fingerprint: str = ""
    attempts: int = 0
    retry_after: datetime | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    @property
    def checkpoint_prefix(self) -> str:
        return f"checkpoints/{self.job_id}"

    @property
    def original_asset(self) -> str:
        return f"documents/{self.metadata.doc_id}/{self.fingerprint}/source.pdf"

    def public_status(self) -> dict:
        return {
            "job_id": self.job_id, "doc_id": self.metadata.doc_id,
            "source_file": self.blob_name, "status": self.status, "stage": self.stage,
            "pages_completed": min(self.next_page - 1, self.total_pages),
            "pages_total": self.total_pages,
            "figures_completed": self.next_figure, "figures_total": self.figure_count,
            "chunks_completed": self.next_chunk, "chunks_total": self.chunk_count,
            "error": self.error, "updated_at": self.updated_at.isoformat(),
        }


class JobStore(BlobStore):
    def read_asset(self, name: str) -> bytes:
        return self.assets.download_blob(name).readall()

    def read_json(self, name: str):
        try:
            return json.loads(self.read_asset(name))
        except ResourceNotFoundError:
            return None

    def write_json(self, name: str, data) -> None:
        self.write_asset(name, json.dumps(data, ensure_ascii=False).encode(), "application/json")

    def write_job(self, job: IngestionJob, *, lease=None, create: bool = False) -> None:
        job.updated_at = utcnow()
        self.assets.upload_blob(
            f"jobs/{job.job_id}.json", job.model_dump_json().encode(),
            overwrite=not create, lease=lease, metadata={"state": job.status},
            content_settings=ContentSettings(content_type="application/json"),
        )

    def jobs(self, *, pending_only: bool = False) -> list[IngestionJob]:
        records = []
        for blob in self.assets.list_blobs(name_starts_with="jobs/", include=["metadata"]):
            if pending_only and (blob.metadata or {}).get("state") in {
                "completed", "failed", "superseded",
            }:
                continue
            records.append(IngestionJob.model_validate_json(self.read_asset(blob.name)))
        return sorted(records, key=lambda job: job.updated_at)


def enqueue_blob(blob_name: str, *, store: JobStore | None = None) -> IngestionJob:
    if not blob_name.lower().endswith(".pdf"):
        raise ValueError("Only PDF sources are supported")
    store = store or JobStore()
    props = store.source(blob_name).get_blob_properties()
    if props.size > get_settings().max_upload_mb * 1024 * 1024:
        raise ValueError("Source exceeds MAX_UPLOAD_MB")
    metadata = document_metadata(blob_name, props.metadata)
    token = hashlib.sha256((blob_name + "\0" + props.etag).encode()).hexdigest()[:32]
    job = IngestionJob(
        job_id=f"{metadata.doc_id}-{token}", blob_name=blob_name,
        source_etag=props.etag, metadata=metadata,
    )
    try:
        store.write_job(job, create=True)
    except ResourceExistsError:
        existing = store.read_json(f"jobs/{job.job_id}.json")
        job = IngestionJob.model_validate(existing)
    log.info("ingest queued doc_id=%s job_id=%s status=%s",
             metadata.doc_id, job.job_id, job.status)
    return job


def _required_json(store: JobStore, name: str):
    value = store.read_json(name)
    if value is None:
        raise RuntimeError(f"Missing ingestion checkpoint: {name}")
    return value


def merge_layout_parts(job: IngestionJob, store: JobStore) -> ParsedDoc:
    merged = ParsedDoc(doc_id=job.metadata.doc_id, paragraphs=[], tables=[], figures=[])
    offset = 0
    for first in range(1, job.total_pages + 1, job.page_size):
        part = ParsedDoc.model_validate(_required_json(
            store, f"{job.checkpoint_prefix}/layout/{first:05d}.json",
        ))
        elements = [*part.paragraphs, *part.tables, *part.figures]
        for element in elements:
            element.offset += offset
        offset = max((element.offset for element in elements), default=offset) + 1
        merged.paragraphs.extend(part.paragraphs)
        merged.tables.extend(part.tables)
        merged.figures.extend(part.figures)
    return merged


def _metadata_args(job: IngestionJob) -> dict:
    return job.metadata.model_dump(exclude={"doc_id"})


def _source_url(job: IngestionJob, store: JobStore) -> str:
    return f"{store.endpoint}/api/documents/{job.metadata.doc_id}?version={job.fingerprint}"


def _finish_upload_plan(job: IngestionJob, store: JobStore, prepared: PreparedDocument) -> None:
    chunks = prepared.chunks
    for i in range(job.figure_count):
        chunks.append(Chunk.model_validate(_required_json(
            store, f"{job.checkpoint_prefix}/figures/{i}.json",
        )))
    if not chunks:
        raise ValueError("No extractable content; existing indexes are unchanged")
    for chunk in chunks:
        chunk.source_file = job.blob_name
        chunk.source_url = _source_url(job, store)
    store.write_json(
        f"{job.checkpoint_prefix}/chunks.json",
        [chunk.model_dump(mode="json", exclude={"content_vector"}) for chunk in chunks],
    )
    job.chunk_count = len(chunks)
    job.stage = "embedding"


def advance_job(
    job: IngestionJob, store: JobStore, *, source_lock: BlobLeaseClient | None = None,
) -> None:
    """Perform one bounded, checkpointed unit of work; never the whole PDF."""
    source = store.source(job.blob_name)
    if source_lock is None and job.stage in {"embedding", "finalize"}:
        with source_lease(source) as lease:
            _advance_job(job, store, source, lease)
    else:
        _advance_job(job, store, source, source_lock)


def _advance_job(
    job: IngestionJob, store: JobStore, source: BlobClient,
    source_lock: BlobLeaseClient | None,
) -> None:
    if source.get_blob_properties(lease=source_lock).etag != job.source_etag:
        job.status = "superseded"
        return
    prefix = job.checkpoint_prefix

    if job.stage == "prepare":
        from azure.core import MatchConditions
        content = source.download_blob(
            etag=job.source_etag, match_condition=MatchConditions.IfNotModified,
        ).readall()
        if not content.startswith(b"%PDF-"):
            raise ValueError("Source is not a PDF")
        reader = PdfReader(io.BytesIO(content))
        if reader.is_encrypted:
            raise ValueError("Encrypted PDFs must be unlocked before upload")
        job.total_pages = len(reader.pages)
        if not job.total_pages:
            raise ValueError("PDF has no pages")
        job.fingerprint = document_fingerprint(content, job.metadata)
        previous = store.read_manifest(job.metadata.doc_id)
        if (previous and previous["fingerprint"] == job.fingerprint
                and not store.has_pending(job.metadata.doc_id)):
            job.status = "completed"
            job.next_page = job.total_pages + 1
            job.chunk_count = job.next_chunk = previous.get("chunks", 0)
            job.figure_count = job.next_figure = len(previous.get("figures", {}))
            return
        if previous and (previous["doc_type"], previous["year"]) != (
            job.metadata.doc_type, job.metadata.year,
        ):
            raise ValueError("Use a new blob name when changing document type or year")
        store.write_pending(job.metadata.doc_id, job.fingerprint)
        store.write_asset(job.original_asset, content, "application/pdf")
        job.stage = "layout"
        return

    if job.stage == "layout":
        first = job.next_page
        last = min(first + job.page_size - 1, job.total_pages)
        checkpoint = f"{prefix}/layout/{first:05d}.json"
        if store.read_json(checkpoint) is None:
            with tempfile.TemporaryDirectory(prefix="ingest-part-") as directory:
                pdf = Path(directory) / "source.pdf"
                pdf.write_bytes(store.read_asset(job.original_asset))
                part = analyze_pdf(
                    str(pdf), job.metadata.doc_id, pages=f"{first}-{last}",
                    use_cache=False, cache_dir=Path(directory) / "cache",
                )
                for element in [*part.paragraphs, *part.tables, *part.figures]:
                    if not first <= element.page <= last:
                        raise ValueError(f"DI returned page {element.page} outside {first}-{last}")
                for i, figure in enumerate(part.figures):
                    if figure.image_path is None:
                        raise ValueError(f"DI figure {i} has no extracted image")
                    figure.image_blob = f"{prefix}/images/{first:05d}-{i}.png"
                    store.write_asset(figure.image_blob, figure.image_path.read_bytes(), "image/png")
                    figure.image_path = None
                store.write_json(checkpoint, part.model_dump(mode="json"))
        job.next_page = last + 1
        if job.next_page > job.total_pages:
            job.stage = "plan"
        return

    if job.stage == "plan":
        doc = merge_layout_parts(job, store)
        prepared = prepare_document(doc, "", figures=False, **_metadata_args(job))
        ensure_indexes()
        if job.metadata.doc_type == "report":
            ensure_structured_indexes()
        store.write_json(f"{prefix}/document.json", doc.model_dump(mode="json"))
        store.write_json(f"{prefix}/prepared.json", prepared.model_dump(mode="json"))
        job.figure_count = len(doc.figures)
        if job.figure_count:
            job.stage = "figures"
        else:
            _finish_upload_plan(job, store, prepared)
        return

    if job.stage == "figures":
        i = job.next_figure
        checkpoint = f"{prefix}/figures/{i}.json"
        if store.read_json(checkpoint) is None:
            doc = ParsedDoc.model_validate(_required_json(store, f"{prefix}/document.json"))
            figure = doc.figures[i]
            if not figure.image_blob:
                raise ValueError("Missing persisted DI figure")
            with tempfile.TemporaryDirectory(prefix="ingest-figure-") as directory:
                figure.image_path = Path(directory) / "figure.png"
                figure.image_path.write_bytes(store.read_asset(figure.image_blob))
                doc.figures = [figure]
                chunks = build_figure_chunks(
                    doc, "", year=job.metadata.year, doc_type=job.metadata.doc_type,
                    fund_scale_default=job.metadata.fund_scale, start_index=i,
                    store_image=lambda index, png: (
                        f"{store.endpoint}/api/figures/{job.metadata.doc_id}/{job.fingerprint}/{index}"
                    ),
                )
                prepared = PreparedDocument.model_validate(
                    _required_json(store, f"{prefix}/prepared.json"),
                )
                if prepared.catalog:
                    chunks = annotate_chunks(chunks, prepared.catalog).chunks
                store.write_json(checkpoint, chunks[0].model_dump(mode="json"))
        if i + 1 == job.figure_count:
            prepared = PreparedDocument.model_validate(_required_json(store, f"{prefix}/prepared.json"))
            _finish_upload_plan(job, store, prepared)
        job.next_figure = i + 1
        return

    if job.stage == "embedding":
        rows = _required_json(store, f"{prefix}/chunks.json")
        first = job.next_chunk
        batch = [Chunk.model_validate(row) for row in rows[first:first + job.embedding_batch_size]]
        receipt = f"{prefix}/uploaded/{first:05d}.json"
        expected_ids = [chunk.id for chunk in batch]
        saved_receipt = store.read_json(receipt)
        if saved_receipt is not None and saved_receipt["ids"] != expected_ids:
            raise ValueError("Upload checkpoint no longer matches the chunk plan")
        if saved_receipt is None:
            vectors = embed_texts([chunk.content for chunk in batch])
            if len(vectors) != len(batch):
                raise ValueError("Embedding count does not match the batch")
            for chunk, vector in zip(batch, vectors):
                chunk.content_vector = vector
            upload_chunks(batch)
            store.write_json(receipt, {"ids": expected_ids})
        job.next_chunk += len(batch)
        if job.next_chunk >= job.chunk_count:
            job.stage = "finalize"
        return

    if job.stage == "finalize":
        prepared = PreparedDocument.model_validate(_required_json(store, f"{prefix}/prepared.json"))
        if job.metadata.doc_type == "report":
            s = get_settings()
            credential = DefaultAzureCredential()
            replace_catalog(job.metadata.doc_id, prepared.catalog, SearchClient(
                s.search_endpoint, s.search_index_catalog, credential,
            ))
            replace_facts(job.metadata.doc_id, prepared.facts, SearchClient(
                s.search_endpoint, s.search_index_facts, credential,
            ))
        rows = _required_json(store, f"{prefix}/chunks.json")
        delete_stale_chunks(job.metadata.doc_id, {
            kind: {row["id"] for row in rows if row["chunk_type"] == kind}
            for kind in ("narrative", "table", "figure")
        })
        doc = ParsedDoc.model_validate(_required_json(store, f"{prefix}/document.json"))
        source.get_blob_properties(lease=source_lock)
        store.write_manifest(job.metadata.doc_id, {
            **job.metadata.model_dump(mode="json"), "source_file": job.blob_name,
            "source_url": _source_url(job, store), "source_etag": job.source_etag,
            "fingerprint": job.fingerprint, "original_asset": job.original_asset,
            "figures": {str(i): figure.image_blob for i, figure in enumerate(doc.figures)},
            "chunks": job.chunk_count,
        })
        store.clear_pending(job.metadata.doc_id)
        job.status = "completed"


def process_next_job(*, store: JobStore | None = None) -> IngestionJob | None:
    store = store or JobStore()
    for candidate in store.jobs(pending_only=True):
        if candidate.retry_after and candidate.retry_after > utcnow():
            continue
        blob = store.assets.get_blob_client(f"jobs/{candidate.job_id}.json")
        try:
            with source_lease(blob) as lease:
                job = IngestionJob.model_validate_json(blob.download_blob(lease=lease).readall())
                if job.status in {"completed", "failed", "superseded"}:
                    continue
                if job.attempts >= MAX_ATTEMPTS:
                    job.status = "failed"
                    job.error = job.error or "Worker repeatedly stopped before checkpoint completion"
                    store.write_job(job, lease=lease)
                    return job
                job.status = "running"
                job.attempts += 1
                store.write_job(job, lease=lease)
                log.info("ingest job=%s stage=%s pages=%d/%d chunks=%d/%d",
                         job.job_id, job.stage, job.next_page-1, job.total_pages,
                         job.next_chunk, job.chunk_count)
                writing = job.stage in {"embedding", "finalize"}
                with (source_lease(store.source(job.blob_name)) if writing else nullcontext(None)) as source_lock:
                    try:
                        advance_job(job, store, source_lock=source_lock)
                    except Exception as exc:
                        log.exception("Ingestion job step failed: %s", job.job_id)
                        job.error = str(exc)[:2000]
                        job.status = "failed" if isinstance(exc, ValueError) or job.attempts >= MAX_ATTEMPTS else "retrying"
                        job.retry_after = utcnow() + timedelta(seconds=min(30 * 2**job.attempts, 300))
                    else:
                        if job.status == "running":
                            job.status = "queued"
                        job.attempts = 0
                        job.retry_after = None
                        job.error = None
                    store.write_job(job, lease=lease)
                return job
        except ResourceExistsError as exc:
            if exc.error_code != "LeaseAlreadyPresent":
                raise
            log.info("Another worker owns job %s", candidate.job_id)
    return None
