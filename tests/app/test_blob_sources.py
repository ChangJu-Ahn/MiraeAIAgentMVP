from types import SimpleNamespace

from fastapi.responses import RedirectResponse

from app import source_docs
from app.formatting import dedup_sources, format_citations
from agent.tools import RetrievedSource


def test_remote_sources_replace_static_manifest_and_redirect_to_pdf(monkeypatch):
    monkeypatch.setattr(source_docs, "get_settings", lambda: SimpleNamespace(
        ingest_api_endpoint="https://ingest.example",
    ))
    monkeypatch.setattr(source_docs, "indexed_documents", lambda: [
        SimpleNamespace(doc_id="new", source_file="new.pdf", year=None,
                        doc_type="document", source_url="https://ingest.example/api/documents/new"),
    ])
    documents = source_docs.source_documents()
    assert [d.doc_id for d in documents] == ["new"]
    response = source_docs.source_document_response("new")
    assert isinstance(response, RedirectResponse)
    assert response.headers["location"] == "https://ingest.example/api/documents/new"


def test_citations_link_original_and_figure_and_dedup_per_document():
    def source(n, doc_id):
        return RetrievedSource(
            n=n, index="figure-index", section_path="Chart", page_physical=1,
            chunk_type="figure", snippet="chart", doc_id=doc_id,
            source_url=f"https://fn/api/documents/{doc_id}",
            image_url=f"https://fn/api/figures/{doc_id}/version/0",
        )
    records = [source(1, "first"), source(2, "second")]
    assert len(dedup_sources(records)) == 2
    rendered = format_citations(records)
    assert "https://fn/api/documents/first#page=1" in rendered
    assert "https://fn/api/figures/second/version/0" in rendered
