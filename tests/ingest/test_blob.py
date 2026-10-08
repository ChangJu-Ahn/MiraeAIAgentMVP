from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


def test_known_pdf_keeps_fund_postprocessing_metadata():
    from ingest.blob import document_metadata
    from ingest.corpus import CORPUS
    from pathlib import Path
    doc = CORPUS[0]
    result = document_metadata(Path(doc.pdf).name, {})
    assert result.doc_id == doc.doc_id
    assert result.doc_type == "report"
    assert result.year == 2025
    assert result.expected_overall_grade_count == 24


def test_unknown_pdf_defaults_to_generic_and_has_collision_safe_id():
    from ingest.blob import document_metadata
    first = document_metadata("자료.pdf", {})
    second = document_metadata("다른.pdf", {})
    assert first.doc_type == "document"
    assert first.doc_id != second.doc_id
    assert first.doc_id.isascii()


def test_invalid_report_metadata_is_rejected():
    from ingest.blob import document_metadata
    with pytest.raises(ValueError, match="year"):
        document_metadata("new.pdf", {"doc_type": "report"})


def _store():
    store = MagicMock()
    source = store.source.return_value
    source.get_blob_properties.return_value = SimpleNamespace(metadata={})
    source.download_blob.return_value.readall.return_value = b"%PDF-first"
    store.read_manifest.return_value = None
    store.has_pending.return_value = False
    store.endpoint = "https://ingest.example"
    return store


def test_blob_runs_main_pipeline_and_publishes_manifest_after_success(monkeypatch):
    import ingest.blob as module
    store = _store()
    monkeypatch.setattr(module, "source_lease", lambda source: nullcontext(None))
    calls = []
    def run(pdf, doc_id, pages, use_cache, **kwargs):
        from pathlib import Path
        assert Path(pdf).read_bytes() == b"%PDF-first"
        assert kwargs["cache_dir"].is_dir()
        assert kwargs["doc_type"] == "document"
        assert not store.write_manifest.called
        assert kwargs["store_image"]("0", b"png").startswith("https://ingest.example/")
        calls.append(doc_id)
        return 3
    monkeypatch.setattr(module, "run", run)
    result = module.ingest_blob("new.pdf", store=store)
    assert result["chunks"] == 3
    assert result["doc_id"] == calls[0]
    store.write_manifest.assert_called_once()
    store.write_asset.assert_called()


def test_duplicate_content_skips_analysis_but_changed_content_is_reprocessed(monkeypatch):
    import ingest.blob as module
    store = _store()
    monkeypatch.setattr(module, "source_lease", lambda source: nullcontext(None))
    runner = MagicMock(return_value=1)
    monkeypatch.setattr(module, "run", runner)
    module.ingest_blob("new.pdf", store=store)
    record = store.write_manifest.call_args.args[1]
    store.read_manifest.return_value = record
    module.ingest_blob("new.pdf", store=store)
    assert runner.call_count == 1
    store.source.return_value.download_blob.return_value.readall.return_value = b"%PDF-new"
    module.ingest_blob("new.pdf", store=store)
    assert runner.call_count == 2


def test_failed_ingest_does_not_publish_success(monkeypatch):
    import ingest.blob as module
    store = _store()
    monkeypatch.setattr(module, "source_lease", lambda source: nullcontext(None))
    monkeypatch.setattr(module, "run", MagicMock(side_effect=RuntimeError("index failed")))
    with pytest.raises(RuntimeError, match="index failed"):
        module.ingest_blob("new.pdf", store=store)
    store.write_manifest.assert_not_called()


def test_full_blob_pipeline_routes_three_types_and_preserves_image_bytes(monkeypatch):
    """Only Azure boundaries are fake; real parsing, chunking, run and index routing execute."""
    import ingest.blob as blob
    import ingest.run as runner
    from ingest import figures, indexer, parser
    from config.settings import Settings
    store = _store()
    monkeypatch.setattr(blob, "source_lease", lambda source: nullcontext(None))
    png = b"\x89PNG\r\n\x1a\nreal DI image bytes"
    di = MagicMock()
    di.begin_analyze_document.return_value.details = {"operation_id": "op"}
    di.begin_analyze_document.return_value.result.return_value.as_dict.return_value = {
        "modelId": "prebuilt-layout",
        "paragraphs": [{"content": "Body text", "spans": [{"offset": 0, "length": 9}]}],
        "tables": [{
            "rowCount": 1, "columnCount": 1,
            "cells": [{"rowIndex": 0, "columnIndex": 0, "content": "42"}],
            "spans": [{"offset": 20, "length": 2}],
        }],
        "figures": [{
            "id": "1.1", "spans": [{"offset": 40, "length": 1}],
            "boundingRegions": [{"pageNumber": 1, "polygon": [0, 0, 1, 0, 1, 1, 0, 1]}],
        }],
    }
    di.get_analyze_result_figure.return_value = [png]
    monkeypatch.setattr(parser, "DocumentIntelligenceClient", lambda **kw: di)
    monkeypatch.setattr(parser, "DefaultAzureCredential", lambda: object())
    monkeypatch.setattr(figures, "describe_figure", lambda image: "Extracted chart" if image == png else "")
    monkeypatch.setattr(figures, "render_figure_png", MagicMock(side_effect=AssertionError("No Poppler in Function")))
    monkeypatch.setattr(runner, "embed_texts", lambda texts: [[0.0] * 3072 for _ in texts])
    monkeypatch.setattr(runner, "ensure_indexes", lambda: None)
    monkeypatch.setattr(indexer, "get_settings", lambda: Settings())
    monkeypatch.setattr(indexer, "DefaultAzureCredential", lambda: object())
    uploads = {}
    def search_client(**kwargs):
        client = MagicMock()
        client.search.return_value = []
        def upload(documents):
            uploads[kwargs["index_name"]] = documents
            return [SimpleNamespace(succeeded=True) for _ in documents]
        client.upload_documents.side_effect = upload
        return client
    monkeypatch.setattr(indexer, "SearchClient", search_client)
    record = blob.ingest_blob("new.pdf", store=store)
    assert record["chunks"] == 3
    assert set(uploads) == {"narrative-index", "table-index", "figure-index"}
    assert uploads["narrative-index"][0]["content"] == "Body text"
    assert "42" in uploads["table-index"][0]["content"]
    assert uploads["figure-index"][0]["image_url"].endswith("/0")
    assert any(call.args[1] == png for call in store.write_asset.call_args_list)


def test_failed_update_forces_reindex_even_when_reuploading_last_success(monkeypatch):
    import ingest.blob as module
    store = _store()
    dirty = [False]
    store.has_pending.side_effect = lambda doc_id: dirty[0]
    store.write_pending.side_effect = lambda *args: dirty.__setitem__(0, True)
    store.clear_pending.side_effect = lambda *args: dirty.__setitem__(0, False)
    monkeypatch.setattr(module, "source_lease", lambda source: nullcontext(None))
    runner = MagicMock(side_effect=[1, RuntimeError("partial write"), 1])
    monkeypatch.setattr(module, "run", runner)
    module.ingest_blob("new.pdf", store=store)
    store.read_manifest.return_value = store.write_manifest.call_args.args[1]
    source = store.source.return_value
    source.download_blob.return_value.readall.return_value = b"%PDF-version-B"
    with pytest.raises(RuntimeError, match="partial write"):
        module.ingest_blob("new.pdf", store=store)
    source.download_blob.return_value.readall.return_value = b"%PDF-first"
    module.ingest_blob("new.pdf", store=store)
    assert runner.call_count == 3
    assert dirty == [False]


def test_published_versions_keep_old_pdf_and_figure_accessible():
    from ingest.blob import BlobStore
    from azure.core.exceptions import ResourceNotFoundError
    storage = {}
    assets = MagicMock()
    assets.upload_blob.side_effect = lambda name, data, **kw: storage.__setitem__(name, data)
    def download(name):
        if name not in storage:
            raise ResourceNotFoundError(name)
        return SimpleNamespace(readall=lambda: storage[name])
    assets.download_blob.side_effect = download
    store = BlobStore.__new__(BlobStore)
    store.assets = assets
    a, b = "a" * 64, "b" * 64
    for version in (a, b):
        storage[f"{version}/pdf"] = version.encode()
        storage[f"{version}/png"] = b"png:" + version.encode()
        store.write_manifest("doc", {
            "doc_id": "doc", "fingerprint": version, "source_file": "file.pdf",
            "original_asset": f"{version}/pdf", "figures": {"0": f"{version}/png"},
        })
    assert store.read_source("doc", version=a)[0] == a.encode()
    assert store.read_source("doc")[0] == b.encode()
    assert store.read_figure("doc", a, "0") == b"png:" + a.encode()
