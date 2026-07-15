from agent.tools import RetrievedSource
from app.formatting import format_citations


def test_format_citations_lists_sources():
    sources = [
        RetrievedSource(
            n=1, index="narrative-index", section_path="Ⅱ > 1 > 가",
            page_physical=24, chunk_type="narrative", snippet="...", score=3.42,
        ),
        RetrievedSource(
            n=2, index="table-index", section_path="03. 방송통신발전기금 > 2. 기금현황",
            page_physical=89, chunk_type="table", snippet="...", score=2.10,
        ),
    ]
    out = format_citations(sources)
    assert "### 근거" in out
    assert "[출처 1]" in out and "[출처 2]" in out
    assert "p.24" in out
    assert "03. 방송통신발전기금" in out
    assert "관련도" not in out  # 일반 모드 카드에는 점수 미표시 (디버그 전용)


def test_format_citations_empty():
    assert format_citations([]) == ""


def test_cited_sources_filters_to_referenced():
    from agent.tools import RetrievedSource
    from app.formatting import cited_sources

    srcs = [
        RetrievedSource(n=1, index="narrative-index", section_path="A", page_physical=1, chunk_type="narrative", snippet="s"),
        RetrievedSource(n=2, index="table-index", section_path="B", page_physical=2, chunk_type="table", snippet="s"),
        RetrievedSource(n=3, index="narrative-index", section_path="C", page_physical=3, chunk_type="narrative", snippet="s"),
    ]
    answer = "핵심은 [출처 1] 이고 표는 [출처 3] 참조."
    out = cited_sources(answer, srcs)
    assert {s.n for s in out} == {1, 3}


def test_cited_sources_empty_when_no_refs():
    from agent.tools import RetrievedSource
    from app.formatting import cited_sources

    srcs = [RetrievedSource(n=1, index="x", section_path="A", page_physical=1, chunk_type="narrative", snippet="s")]
    assert cited_sources("인용 없음", srcs) == []
