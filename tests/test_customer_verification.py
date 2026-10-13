from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from scripts import deploy_demo as demo


def runner(tmp_path):
    args = demo.parse_args(["--resource-group", "rg-demo", "--yes", "--auth-mode", "identity"])
    result = demo.Deployment(args, tmp_path, tmp_path)
    result.outputs = {
        "storageEndpoint": "https://example.blob.core.windows.net",
        "apiEndpoint": "https://fn.azurewebsites.net",
        "uploadUrl": "https://fn.azurewebsites.net/api/upload",
    }
    result.credential = object()
    return result


def test_default_smoke_never_overwrites_an_unrelated_customer_pdf(monkeypatch, tmp_path):
    import azure.storage.blob
    store = MagicMock()
    store.get_blob_client.return_value.exists.return_value = True
    store.get_blob_client.return_value.download_blob.return_value.readall.return_value = b"customer file"
    monkeypatch.setattr(azure.storage.blob, "BlobServiceClient", lambda *a, **kw: store)
    monkeypatch.setattr(demo.requests, "post", lambda *a, **kw: pytest.fail("must not upload"))
    with pytest.raises(RuntimeError, match="Refusing to overwrite"):
        runner(tmp_path).verify()


@pytest.mark.parametrize("image_only", [False, True])
def test_real_verification_waits_for_exact_event_job_and_persists_no_credentials(monkeypatch, tmp_path, image_only):
    import azure.storage.blob
    import azure.search.documents
    from ingest.blob import document_metadata
    from pathlib import Path
    import hashlib
    import json
    store = MagicMock()
    store.get_blob_client.return_value.exists.return_value = False
    store.get_blob_client.return_value.get_blob_properties.return_value = SimpleNamespace(etag="uploaded-version")
    monkeypatch.setattr(azure.storage.blob, "BlobServiceClient", lambda *a, **kw: store)
    r = runner(tmp_path)
    sample_name = "demo-connection-check.pdf"
    if image_only:
        r.args.sample_pdf = tmp_path / "image-only.pdf"
        r.args.sample_pdf.write_bytes(demo.synthetic_pdf())
        sample_name = r.args.sample_pdf.name
    r.cli = SimpleNamespace(subscription="customer-subscription")
    r.outputs.update({
        "chatbotUrl": "https://chat.test",
        "storageAccountName": "customerstorage", "uploadContainer": "pdfs",
        "assetsContainer": "document-assets", "searchName": "customersearch",
        "searchEndpoint": "https://customersearch.search.windows.net",
        "functionAppName": "customerfunction",
        "appInsightsConnectionString": "do-not-publish", "credential": "do-not-publish",
    })
    response = MagicMock(status_code=202)
    monkeypatch.setattr(demo.requests, "post", lambda *a, **kw: response)
    meta = document_metadata(sample_name, {})
    token = hashlib.sha256((sample_name + "\0uploaded-version").encode()).hexdigest()[:32]
    job = {"job_id": meta.doc_id + "-" + token, "status": "completed", "stage": "finalize",
           "pages_completed": 1, "chunks_completed": 1}
    def http(url, **kwargs):
        values = {
            r.outputs["apiEndpoint"] + "/api/jobs": [job],
            r.outputs["apiEndpoint"] + "/api/documents": [{"doc_id": meta.doc_id}],
            r.outputs["chatbotUrl"] + "/project/settings": {
                "features": {"spontaneous_file_upload": {"enabled": False}},
                "ui": {"name": "Assistant"},
            },
        }
        return SimpleNamespace(json=lambda: values[url])
    monkeypatch.setattr(demo, "wait_http", http)
    def search_client(endpoint, index, credential):
        rows = [] if image_only and index != "figure-index" else [{"content": "Azure component demo"}]
        return SimpleNamespace(search=lambda **kw: rows)
    monkeypatch.setattr(azure.search.documents, "SearchClient", search_client)
    if image_only:
        clock = iter(range(0, 10000, 60))
        monkeypatch.setattr(demo.time, "monotonic", lambda: next(clock))
        monkeypatch.setattr(demo.time, "sleep", lambda delay: None)
    r.verify()
    path = Path(tmp_path) / ".azure/customer/rg-demo/deployment.json"
    contents = path.read_text()
    assert "do-not-publish" not in contents
    assert json.loads(contents)["verified"] is True
    store.get_blob_client.return_value.delete_blob.assert_not_called()


def test_failed_job_does_not_write_a_verified_deployment_summary(monkeypatch, tmp_path):
    import azure.storage.blob
    from ingest.blob import document_metadata
    import hashlib
    store = MagicMock()
    store.get_blob_client.return_value.exists.return_value = False
    store.get_blob_client.return_value.get_blob_properties.return_value = SimpleNamespace(etag="etag")
    monkeypatch.setattr(azure.storage.blob, "BlobServiceClient", lambda *a, **kw: store)
    response = MagicMock(status_code=202)
    monkeypatch.setattr(demo.requests, "post", lambda *a, **kw: response)
    doc_id = document_metadata("demo-connection-check.pdf", {}).doc_id
    token = hashlib.sha256(b"demo-connection-check.pdf\0etag").hexdigest()[:32]
    job = {"job_id": doc_id + "-" + token, "status": "failed", "stage": "layout",
           "pages_completed": 0, "chunks_completed": 0, "error": "DI permission denied"}
    monkeypatch.setattr(demo, "wait_http", lambda *a, **kw: SimpleNamespace(json=lambda: [job]))
    with pytest.raises(RuntimeError, match="DI permission denied"):
        runner(tmp_path).verify()
    assert not (tmp_path / ".azure/customer").exists()
