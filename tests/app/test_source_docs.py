from __future__ import annotations

import importlib
import unicodedata
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.responses import FileResponse, HTMLResponse

import app.source_docs as source_docs_module
from app.source_docs import source_document_response, source_documents, source_docs_page
from ingest.corpus import CORPUS, CorpusDoc


def test_source_documents_resolve_all_manifest_pdfs():
    documents = source_documents()

    assert [document.doc_id for document in documents] == [
        corpus_doc.doc_id for corpus_doc in CORPUS
    ]
    assert [document.label for document in documents] == [
        "2025 보고서",
        "2022 보고서",
        "2021 보고서",
        "2021 지침",
        "2022 지침",
    ]
    assert all(document.path.is_file() for document in documents)
    assert all(document.path.parent.name == "Docs" for document in documents)
    assert all(
        document.href == f"/source-docs/{document.doc_id}"
        for document in documents
    )


def test_source_path_resolution_matches_unicode_normalization(tmp_path, monkeypatch):
    decomposed_name = unicodedata.normalize("NFD", "2025회계연도 보고서.pdf")
    pdf = tmp_path / decomposed_name
    pdf.write_bytes(b"%PDF-1.7\n")
    corpus_doc = CorpusDoc(
        pdf="Docs/2025회계연도 보고서.pdf",
        doc_id="report-2025-test",
        year=2025,
        doc_type="report",
    )
    monkeypatch.setattr(source_docs_module, "DOCS_DIR", tmp_path)

    assert source_docs_module._resolve_source_path(corpus_doc) == pdf


def test_source_docs_page_lists_safe_manifest_links_without_local_paths():
    response = source_docs_page()
    html = response.body.decode("utf-8")

    assert isinstance(response, HTMLResponse)
    assert response.status_code == 200
    assert "원본자료" in html
    assert "RAG에 등록된 원본 PDF 5개" in html
    assert html.count('target="_blank"') == 5
    for document in source_documents():
        assert document.label in html
        assert f'href="{document.href}"' in html
        assert str(document.path) not in html


def test_source_document_response_opens_the_actual_pdf_inline():
    response = source_document_response("report-2025")
    expected = source_documents()[0]

    assert isinstance(response, FileResponse)
    assert Path(response.path).samefile(expected.path)
    assert response.media_type == "application/pdf"
    assert response.headers["content-disposition"].startswith("inline;")


def test_source_document_response_rejects_unknown_ids():
    with pytest.raises(HTTPException) as exc_info:
        source_document_response("../../README")

    assert exc_info.value.status_code == 404


def test_chainlit_registers_source_routes_before_the_spa_fallback():
    importlib.import_module("app.chat")

    from chainlit.server import app as chainlit_app

    paths = [getattr(route, "path", "") for route in chainlit_app.router.routes]
    assert paths[:2] == ["/source-docs", "/source-docs/{doc_id}"]