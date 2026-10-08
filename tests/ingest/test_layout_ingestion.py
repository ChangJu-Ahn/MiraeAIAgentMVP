from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from ingest import indexer, parser
from ingest.chunker import chunk_document
from ingest.models import Chunk


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
    client.begin_analyze_document.return_value.result.return_value.as_dict.return_value = data
    client.begin_analyze_document.return_value.details = {"operation_id": "operation"}
    client.get_analyze_result_figure.return_value = [b"\x89PNG\r\n\x1a\n", b"image"]
    monkeypatch.setattr(parser, "DocumentIntelligenceClient", lambda **kw: client)
    monkeypatch.setattr(parser, "DefaultAzureCredential", lambda: object())

    first = parser.analyze_pdf(str(pdf), "doc", cache_dir=cache)
    assert first.figures[0].image_path.read_bytes().startswith(b"\x89PNG")
    parser.analyze_pdf(str(pdf), "doc", cache_dir=cache)
    assert client.begin_analyze_document.call_count == 1
    pdf.write_bytes(b"changed pdf")
    parser.analyze_pdf(str(pdf), "doc", cache_dir=cache)
    assert client.begin_analyze_document.call_count == 2
    assert client.begin_analyze_document.call_args.kwargs["output"] == ["figures"]


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
