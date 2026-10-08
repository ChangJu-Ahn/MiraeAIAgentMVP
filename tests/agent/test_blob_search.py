from types import SimpleNamespace

from agent import tools
from agent.tools import TraceRecorder, make_search_tools


def test_figure_search_keeps_existing_tools_and_provenance(monkeypatch):
    monkeypatch.setattr(tools, "hybrid_search", lambda index, *a, **kw: [
        SimpleNamespace(
            content="A performance chart", section_path="Results",
            page_physical=2, chunk_type="figure", score=1.0, doc_id="doc",
            source_url="https://fn/api/documents/doc",
            image_url="https://fn/api/figures/doc/hash/0", source_file="a.pdf",
        )
    ])
    recorder = TraceRecorder()
    registered = {f.__name__: f for f in make_search_tools(recorder)}
    assert "fund_analytics" in registered
    assert "search_figures" in registered
    result = registered["search_figures"]("chart")
    assert "doc" in result
    assert recorder.sources[0].index == "figure-index"
    assert recorder.sources[0].image_url.endswith("/0")
    assert recorder.sources[0].doc_id == "doc"


def test_blob_manifest_allows_new_year_without_changing_static_corpus(monkeypatch):
    monkeypatch.setattr(tools, "indexed_documents", lambda: [
        SimpleNamespace(doc_id="new", year=2026, doc_type="report"),
    ])
    calls = []
    monkeypatch.setattr(tools, "hybrid_search", lambda *a, **kw: calls.append(a) or [])
    result = make_search_tools(TraceRecorder())[0]("query", year=2026, doc_type="report")
    assert result == "검색 결과 없음"
    assert calls


def test_structured_fact_keeps_blob_provenance(monkeypatch):
    from ingest.facts import EvaluationFact
    fact = EvaluationFact(
        id="fact", doc_id="report-2025", fund_id="fund", fund_name="Fund",
        year=2025, ministry="Ministry", metric_code="score", metric_name="Score", fact_type="score",
        score=42, source_chunk_id="report-2025-1", source_page_physical=2,
        source_section_path="Results", source_text="Score: 42",
    )
    monkeypatch.setattr(tools, "indexed_documents", lambda: [
        SimpleNamespace(doc_id="report-2025", year=2025, doc_type="report",
                        source_file="report.pdf", source_url="https://fn/api/documents/report-2025?version=old"),
    ])
    monkeypatch.setattr(tools._structured, "get_fund_evaluations", lambda **kw: [fact])
    recorder = TraceRecorder()
    registered = {f.__name__: f for f in make_search_tools(recorder)}
    result = registered["get_fund_evaluations"]("Fund", 2025)
    source = recorder.sources[0]
    assert source.doc_id == "report-2025"
    assert source.source_url.endswith("version=old")
    assert "doc_id=report-2025" in result
