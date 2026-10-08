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
    monkeypatch.setattr(module, "ingest_blob", handler)
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
