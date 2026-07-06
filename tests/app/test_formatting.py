from agent.tools import RetrievedSource, TraceStep
from app.formatting import format_citations, format_reasoning_step


def test_format_reasoning_step():
    step = TraceStep(tool="search_narrative", query="탁월 등급", n_hits=5)
    out = format_reasoning_step(step)
    assert "search_narrative" in out
    assert "탁월 등급" in out
    assert "5" in out


def test_format_citations_lists_sources():
    sources = [
        RetrievedSource(
            n=1, index="narrative-index", section_path="Ⅱ > 1 > 가",
            page_physical=24, chunk_type="narrative", snippet="...",
        ),
        RetrievedSource(
            n=2, index="table-index", section_path="03. 방송통신발전기금 > 2. 기금현황",
            page_physical=89, chunk_type="table", snippet="...",
        ),
    ]
    out = format_citations(sources)
    assert "### 근거" in out
    assert "[출처 1]" in out and "[출처 2]" in out
    assert "p.24" in out
    assert "03. 방송통신발전기금" in out


def test_format_citations_empty():
    assert format_citations([]) == ""
