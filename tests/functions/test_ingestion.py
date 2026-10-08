import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import azure.functions as func
import pytest


def _module():
    from functions.ingestion import function_app
    return function_app


def _invoke(function, request):
    return function.build().get_user_function()(request)


def test_blob_event_invokes_main_adapter_only_for_source_pdf(monkeypatch):
    module = _module()
    handler = MagicMock(return_value={"chunks": 3})
    monkeypatch.setattr(module, "enqueue_blob", handler)
    for subject in (
        "/blobServices/default/containers/document-assets/blobs/image.png",
        "/blobServices/default/containers/pdfs/blobs/image.png",
    ):
        _invoke(module.index, SimpleNamespace(subject=subject))
    handler.assert_not_called()
    _invoke(module.index, SimpleNamespace(
        subject="/blobServices/default/containers/pdfs/blobs/folder/report.pdf",
    ))
    handler.assert_called_once_with("folder/report.pdf")


def test_timer_serializes_work_without_blocking_event_enqueue(monkeypatch):
    module = _module()
    subject = "/blobServices/default/containers/pdfs/blobs/report.pdf"
    calls = []
    queued = MagicMock()
    monkeypatch.setattr(module, "enqueue_blob", queued)
    def process():
        calls.append("step")
        if len(calls) == 1:
            _invoke(module.process_jobs, SimpleNamespace())
            _invoke(module.index, SimpleNamespace(subject=subject))
        return {}
    monkeypatch.setattr(module, "process_next_job", process)
    _invoke(module.process_jobs, SimpleNamespace())
    assert calls == ["step"]
    queued.assert_called_once_with("report.pdf")
    # The slot must be released after success.
    monkeypatch.setattr(module, "process_next_job", MagicMock(side_effect=ValueError("bad PDF")))
    with pytest.raises(ValueError, match="bad PDF"):
        _invoke(module.process_jobs, SimpleNamespace())
    handler = MagicMock()
    monkeypatch.setattr(module, "process_next_job", handler)
    _invoke(module.process_jobs, SimpleNamespace())
    handler.assert_called_once()


def test_upload_returns_accepted_not_indexed(monkeypatch):
    module = _module()
    store = MagicMock()
    monkeypatch.setattr(module, "BlobStore", lambda: store)
    part = SimpleNamespace(filename="new.pdf", read=lambda: b"%PDF-new")
    response = _invoke(module.upload, SimpleNamespace(
        method="POST", files={"file": part}, form={},
    ))
    assert response.status_code == 202
    assert json.loads(response.get_body())["status"] == "uploaded"
    store.source.return_value.upload_blob.assert_called_once()


@pytest.mark.parametrize("filename,body", [("bad.txt", b"text"), ("bad.pdf", b"not a pdf")])
def test_invalid_upload_is_not_stored(monkeypatch, filename, body):
    module = _module()
    store = MagicMock()
    monkeypatch.setattr(module, "BlobStore", lambda: store)
    response = _invoke(module.upload, SimpleNamespace(
        method="POST", files={"file": SimpleNamespace(filename=filename, read=lambda: body)},
        form={},
    ))
    assert response.status_code == 400
    store.source.assert_not_called()


def test_document_list_exposes_completed_records_not_private_asset_paths(monkeypatch):
    module = _module()
    store = MagicMock()
    store.documents.return_value = [{
        "doc_id": "doc", "source_file": "a.pdf", "doc_type": "document", "year": None,
        "source_url": "https://fn/api/documents/doc", "chunks": 3,
        "original_asset": "private/path", "figures": {"0": "private/figure"},
    }]
    monkeypatch.setattr(module, "BlobStore", lambda: store)
    response = _invoke(module.documents, func.HttpRequest("GET", "/api/documents", body=b""))
    records = json.loads(response.get_body())
    assert records[0]["doc_id"] == "doc"
    assert "private/" not in response.get_body().decode()


def test_jobs_endpoint_reports_progress_without_internal_checkpoint_paths(monkeypatch):
    from ingest.jobs import IngestionJob
    from ingest.blob import DocumentMetadata
    module = _module()
    job = IngestionJob(
        job_id="job", blob_name="report.pdf", source_etag="private-etag",
        metadata=DocumentMetadata(doc_id="doc"), stage="layout",
        total_pages=532, next_page=26,
    )
    store = MagicMock()
    store.jobs.return_value = [job]
    monkeypatch.setattr(module, "JobStore", lambda: store)
    response = _invoke(module.jobs, func.HttpRequest("GET", "/api/jobs", body=b""))
    row = json.loads(response.get_body())[0]
    assert row["pages_completed"] == 25 and row["pages_total"] == 532
    assert "source_etag" not in row and "metadata" not in row
