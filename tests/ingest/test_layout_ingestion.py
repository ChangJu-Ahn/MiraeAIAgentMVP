from types import SimpleNamespace
from unittest.mock import MagicMock
from azure.ai.documentintelligence.models import AnalyzeResult

import pytest

from ingest import indexer, parser
from ingest.chunker import chunk_document
from ingest.models import Chunk


def _analysis_responses(data):
    accepted = MagicMock()
    accepted.headers = {
        "Operation-Location": "https://di.test/documentintelligence/documentModels/prebuilt-layout/analyzeResults/operation?api-version=2024-11-30",
    }
    completed = MagicMock()
    import json
    completed.iter_bytes.return_value = [
        json.dumps({"status": "succeeded", "analyzeResult": data}).encode(),
    ]
    return [accepted, completed]


def test_layout_regions_are_excluded_from_narrative_but_preserved_for_postprocessing():
    data = {
        "paragraphs": [
            {"content": "Introduction", "spans": [{"offset": 0, "length": 12}]},
            {"content": "Revenue 42", "spans": [{"offset": 20, "length": 10}]},
            {"content": "Chart labels", "spans": [{"offset": 40, "length": 12}]},
        ],
        "tables": [{
            "rowCount": 1, "columnCount": 1,
            "cells": [{"rowIndex": 0, "columnIndex": 0, "content": "Revenue 42"}],
            "spans": [{"offset": 20, "length": 10}],
        }],
        "figures": [{
            "id": "1.1", "spans": [{"offset": 40, "length": 12}],
            "boundingRegions": [{"pageNumber": 1, "polygon": [0, 0, 1, 0, 1, 1, 0, 1]}],
        }],
    }
    doc = parser._result_to_parsed("doc", data)
    assert len(doc.paragraphs) == 3  # Fund postprocessing still sees the original layout.
    chunks = chunk_document(doc)
    narrative = "\n".join(c.content for c in chunks if c.chunk_type == "narrative")
    assert narrative == "Introduction"
    assert [c.chunk_type for c in chunks] == ["narrative", "table"]
    assert doc.figures[0].figure_id == "1.1"


def test_cache_changes_with_pdf_content_and_downloads_di_figures(tmp_path, monkeypatch):
    pdf = tmp_path / "input.pdf"
    pdf.write_bytes(b"first pdf")
    cache = tmp_path / "cache"
    data = {
        "modelId": "prebuilt-layout", "paragraphs": [], "tables": [],
        "figures": [{"id": "1.1", "boundingRegions": [
            {"pageNumber": 1, "polygon": [0, 0, 1, 0, 1, 1, 0, 1]},
        ]}],
    }
    client = MagicMock()
    client.send_request.side_effect = _analysis_responses(data) + _analysis_responses(data)
    client.get_analyze_result_figure.return_value = [b"\x89PNG\r\n\x1a\n", b"image"]
    monkeypatch.setattr(parser, "DocumentIntelligenceClient", lambda **kw: client)
    monkeypatch.setattr(parser, "DefaultAzureCredential", lambda: object())
    monkeypatch.setattr(parser, "get_settings", lambda: SimpleNamespace(doc_intelligence_endpoint="https://di.test"))

    first = parser.analyze_pdf(str(pdf), "doc", cache_dir=cache)
    assert first.figures[0].image_path.read_bytes().startswith(b"\x89PNG")
    parser.analyze_pdf(str(pdf), "doc", cache_dir=cache)
    assert client.send_request.call_count == 2
    pdf.write_bytes(b"changed pdf")
    parser.analyze_pdf(str(pdf), "doc", cache_dir=cache)
    assert client.send_request.call_count == 4
    first_request = client.send_request.call_args_list[0].args[0]
    assert "output=figures" in first_request.url
    assert first_request.headers["Content-Type"] == "application/pdf"
    assert client.send_request.call_args_list[1].kwargs["stream"] is True


def test_parser_does_not_materialize_unused_word_geometry(tmp_path, monkeypatch):
    import json
    pdf = tmp_path / "report.pdf"
    pdf.write_bytes(b"%PDF-report")
    data = {
        "modelId": "prebuilt-layout",
        "pages": [{"pageNumber": 1, "words": [{"content": "unused"}]}],
        "paragraphs": [{"content": "Body", "spans": [{"offset": 0, "length": 4}]}],
        "tables": [], "figures": [],
    }
    client = MagicMock()
    client.send_request.side_effect = _analysis_responses(data)
    client.begin_analyze_document.side_effect = AssertionError("Typed full-result deserialization is too expensive")
    monkeypatch.setattr(parser, "DocumentIntelligenceClient", lambda **kwargs: client)
    monkeypatch.setattr(parser, "DefaultAzureCredential", lambda: object())
    monkeypatch.setattr(parser, "get_settings", lambda: SimpleNamespace(doc_intelligence_endpoint="https://di.test"))
    monkeypatch.setattr(AnalyzeResult, "as_dict", lambda *a, **kw: pytest.fail(
        "Do not expand the complete DI result including all word geometry",
    ))
    doc = parser.analyze_pdf(str(pdf), "doc", cache_dir=tmp_path / "cache")
    assert doc.paragraphs[0].content == "Body"
    cached = json.loads(next((tmp_path / "cache").rglob("layout.json")).read_text())
    assert set(cached) == {"modelId", "paragraphs", "tables", "figures"}


def test_analysis_rejects_a_polling_url_outside_the_di_endpoint():
    client = MagicMock()
    response = MagicMock()
    response.headers = {"Operation-Location": "https://elsewhere.test/operation"}
    client.send_request.return_value = response
    with pytest.raises(ValueError, match="polling"):
        parser._analyze_layout(client, "https://di.test", b"%PDF", None)
    assert client.send_request.call_count == 1


def test_analysis_surfaces_failed_service_operation():
    client = MagicMock()
    responses = _analysis_responses({})
    responses[1].iter_bytes.return_value = [b'{"status":"failed","error":{"message":"Invalid PDF"}}']
    client.send_request.side_effect = responses
    with pytest.raises(RuntimeError, match="Invalid PDF"):
        parser._analyze_layout(client, "https://di.test", b"%PDF", None)


def test_content_upload_batches_bound_peak_vector_serialization(monkeypatch):
    clients = _clients(monkeypatch)
    chunks = [Chunk(
        id=f"doc-{i}", doc_id="doc", content="body", chunk_type="narrative",
        section_path="", page_physical=1, content_vector=[0.0] * 3072,
    ) for i in range(201)]
    indexer.upload_chunks(chunks, doc_id="doc")
    batches = clients["narrative-index"].upload_documents.call_args_list
    assert [len(c.kwargs["documents"]) for c in batches] == [100, 100, 1]


def _settings():
    return SimpleNamespace(
        search_endpoint="https://test.search.windows.net",
        search_index_narrative="narrative-index",
        search_index_table="table-index",
        search_index_figure="figure-index",
    )


def _clients(monkeypatch, fail=False):
    clients = {}
    def create(**kwargs):
        client = MagicMock()
        client.search.return_value = [{"id": "doc-old"}]
        client.upload_documents.return_value = [
            SimpleNamespace(succeeded=not fail, key="doc-new", error_message="rejected"),
        ]
        client.delete_documents.return_value = [SimpleNamespace(succeeded=True)]
        clients[kwargs["index_name"]] = client
        return client
    monkeypatch.setattr(indexer, "get_settings", _settings)
    monkeypatch.setattr(indexer, "DefaultAzureCredential", lambda: object())
    monkeypatch.setattr(indexer, "SearchClient", create)
    return clients


def test_figure_has_separate_index_and_stale_chunks_are_removed(monkeypatch):
    clients = _clients(monkeypatch)
    chunk = Chunk(
        id="doc-new", doc_id="doc", content="A chart", chunk_type="figure",
        section_path="Results", page_physical=1, content_vector=[0.0] * 3072,
        source_file="report.pdf", source_url="https://app/api/documents/doc",
        image_url="https://app/api/figures/doc/1.1",
    )
    assert indexer.upload_chunks([chunk], doc_id="doc") == 1
    assert set(clients) == {"narrative-index", "table-index", "figure-index"}
    uploaded = clients["figure-index"].upload_documents.call_args.kwargs["documents"][0]
    assert uploaded["image_url"].endswith("/1.1")
    assert uploaded["source_file"] == "report.pdf"
    for client in clients.values():
        client.delete_documents.assert_called_once_with(documents=[{"id": "doc-old"}])


def test_failed_upload_never_deletes_old_chunks(monkeypatch):
    clients = _clients(monkeypatch, fail=True)
    chunks = [Chunk(
        id="doc-new", doc_id="doc", content="body", chunk_type="narrative",
        section_path="", page_physical=1, content_vector=[0.0] * 3072,
    )]
    with pytest.raises(RuntimeError, match="rejected"):
        indexer.upload_chunks(chunks, doc_id="doc")
    assert all(not c.delete_documents.called for c in clients.values())


def test_stale_cleanup_is_separate_from_checkpointed_uploads(monkeypatch):
    clients = _clients(monkeypatch)
    indexer.delete_stale_chunks("doc", {"narrative": {"doc-new"}, "table": set(), "figure": set()})
    assert set(clients) == {"narrative-index", "table-index", "figure-index"}
    for client in clients.values():
        client.upload_documents.assert_not_called()
        client.delete_documents.assert_called_once_with(documents=[{"id": "doc-old"}])


def test_cleanup_removes_ids_that_changed_content_type(monkeypatch):
    clients = _clients(monkeypatch)
    monkeypatch.setattr(indexer, "_fetch_existing_keys", lambda *args: ["doc-0"])
    indexer.delete_stale_chunks("doc", {
        "narrative": set(), "table": {"doc-0"}, "figure": set(),
    })
    clients["narrative-index"].delete_documents.assert_called_once_with(documents=[{"id": "doc-0"}])
    clients["table-index"].delete_documents.assert_not_called()


def test_index_schema_contains_source_and_image_references():
    fields = {f.name for f in indexer.build_index("figure-index").fields}
    assert {"source_file", "source_url", "image_url", "bounding_regions"} <= fields


def test_region_element_references_do_not_leak_into_narrative():
    doc = parser._result_to_parsed("doc", {
        "paragraphs": [{"content": "Photo labels"}, {"content": "Outside the photo"}],
        "figures": [{
            "id": "1.1", "elements": ["/paragraphs/0"],
            "boundingRegions": [{"pageNumber": 1, "polygon": [0, 0, 1, 0, 1, 1, 0, 1]}],
        }],
    })
    assert [c.content for c in chunk_document(doc)] == ["Outside the photo"]
