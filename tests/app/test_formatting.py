from agent.tools import RetrievedSource, TraceStep
from app.formatting import format_citations, format_debug


def test_format_debug_includes_trace_scores_and_citations():
    steps = [TraceStep(tool="search_narrative", query="탁월 등급", n_hits=2)]
    sources = [
        RetrievedSource(
            n=1, index="narrative-index", section_path="Ⅱ > 1 > 가",
            page_physical=24, chunk_type="narrative", snippet="탁월 등급 설명 본문", score=3.42,
        ),
        RetrievedSource(
            n=2, index="narrative-index", section_path="Ⅱ > 2",
            page_physical=25, chunk_type="narrative", snippet="추가 근거", score=2.10,
        ),
    ]
    out = format_debug([("원 질문", steps, sources)], cited=[sources[0]])
    assert "디버그 트레이스" in out
    assert "라운드 1" in out
    assert 'search_narrative("탁월 등급")' in out and "2건" in out
    assert "관련도 3.42" in out and "관련도 2.10" in out  # 전체 검색 결과 스코어
    assert "최종 인용" in out
    assert "탁월 등급 설명 본문" in out  # 스니펫 노출


def test_format_debug_handles_empty_results():
    out = format_debug([("q", [], [])], cited=[])
    assert "검색 결과 없음" in out
    assert "인용하지 않음" in out


def test_format_debug_appends_collapsed_raw_trace():
    raw = '[\n  {"name": "chat gpt-4o"}\n]'
    out = format_debug([("q", [], [])], cited=[], raw_trace=raw)
    assert "<details>" in out and "</details>" in out
    assert "Raw OpenTelemetry Trace" in out
    assert '"name": "chat gpt-4o"' in out
    # raw_trace 미지정 시 details 블록 없음
    assert "<details>" not in format_debug([("q", [], [])], cited=[])


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


def test_format_source_docs():
    from app.formatting import format_source_docs
    out = format_source_docs([("2025 보고서", "https://x/source-docs/a.pdf?sas")])
    assert "원본 자료" in out
    assert "[2025 보고서](https://x/source-docs/a.pdf?sas)" in out
    assert format_source_docs([]) == ""
