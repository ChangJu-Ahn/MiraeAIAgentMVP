from types import SimpleNamespace

import pytest

from agent import tools
from agent.tools import TraceRecorder, make_search_tools, _build_odata_filter


def test_build_odata_filter_combines_nonnull():
    assert _build_odata_filter(year=2022, doc_type="report") == "year eq 2022 and doc_type eq 'report'"
    assert _build_odata_filter() is None
    assert _build_odata_filter(fund_name="국민'연금") == "fund_name eq '국민''연금'"


def test_search_narrative_returns_citations_and_records():
    rec = TraceRecorder()
    search_narrative, _search_tables = make_search_tools(rec)[:2]
    out = search_narrative("탁월 등급의 의미")
    assert "[출처 1]" in out
    assert rec.steps and rec.steps[0].tool == "search_narrative"
    assert rec.sources and rec.sources[0].section_path is not None


def test_search_tables_records_table_tool():
    rec = TraceRecorder()
    tools_list = make_search_tools(rec)
    search_tables = tools_list[1]
    out = search_tables("등급 내용 표")
    assert "[출처" in out
    assert rec.steps[-1].tool == "search_tables"


def test_run_tool_truncates_stored_source_snippet_to_300_chars(monkeypatch):
    hit = SimpleNamespace(
        section_path="section",
        page_physical=1,
        chunk_type="text",
        content="x" * 600,
        score=1.0,
    )
    monkeypatch.setattr(tools, "hybrid_search", lambda *args, **kwargs: [hit])
    recorder = TraceRecorder()

    result = tools._run_tool(
        recorder,
        "search_narrative",
        "narrative-index",
        "query",
    )

    assert len(recorder.sources[0].snippet) == 300
    assert "x" * 500 in result


def test_run_tool_centers_excerpt_on_query_evidence(monkeypatch):
    evidence = (
        "통합 운영했던 리스크관리규정과 성과평가규정을 폐지하고 "
        "기금 단독 규정을 제정하여 독립성을 확보함."
    )
    hit = SimpleNamespace(
        section_path="section",
        page_physical=1,
        chunk_type="text",
        content=("관련 없는 서론 " * 300) + evidence + (" 후속 내용" * 300),
        score=1.0,
    )
    monkeypatch.setattr(tools, "hybrid_search", lambda *args, **kwargs: [hit])
    recorder = TraceRecorder()

    result = tools._run_tool(
        recorder,
        "search_narrative",
        "narrative-index",
        "리스크관리규정 성과평가규정 독립 규정 제정",
    )

    assert "단독 규정을 제정" in result
    assert "단독 규정을 제정" in recorder.sources[0].snippet
    assert len(recorder.sources[0].snippet) <= 300


def test_missing_requested_document_blocks_unfiltered_and_substitute_searches(
    monkeypatch,
):
    calls: list[tuple[str, str | None]] = []

    def _search(index_name, query, *, top, odata_filter):
        calls.append((query, odata_filter))
        return []

    monkeypatch.setattr(tools, "hybrid_search", _search)
    recorder = TraceRecorder(
        requested_years=[2026],
        requested_doc_type="guideline",
    )
    search_narrative, search_tables = make_search_tools(recorder)[:2]

    missing = search_narrative(
        "자산운용 성과 평가지표 범주",
        year=2026,
        doc_type="guideline",
    )
    widened = search_tables("계량평가")
    substituted = search_tables(
        "계량평가 자산운용 성과 부문",
        year=2025,
        doc_type="report",
    )

    assert calls == []
    assert "2026회계연도 기금운용평가지침" in missing
    assert "제공된 corpus에 없습니다" in missing
    assert "[출처 1]" in missing
    assert "대체 검색을 차단" in widened
    assert "대체 검색을 차단" in substituted
    assert len(recorder.sources) == 1
    assert recorder.sources[0].index == "corpus-manifest"
    assert recorder.sources[0].chunk_type == "manifest"


def test_missing_year_still_allows_available_year_in_requested_range(monkeypatch):
    hit = SimpleNamespace(
        section_path="공무원연금기금 > 평가결과",
        page_physical=1,
        chunk_type="text",
        content="2025년 전체 합계 우수",
        score=1.0,
    )
    calls: list[str | None] = []

    def _search(index_name, query, *, top, odata_filter):
        calls.append(odata_filter)
        return [hit]

    monkeypatch.setattr(tools, "hybrid_search", _search)
    recorder = TraceRecorder(
        requested_years=[2023, 2024, 2025],
        requested_doc_type="report",
    )
    search_narrative = make_search_tools(recorder)[0]

    missing = search_narrative(
        "최종등급",
        year=2023,
        doc_type="report",
        fund_name="공무원연금기금",
    )
    available = search_narrative(
        "최종등급",
        year=2025,
        doc_type="report",
        fund_name="공무원연금기금",
    )

    assert "2023회계연도 기금운용평가보고서" in missing
    assert "2025년 전체 합계 우수" in available
    assert calls == [
        "year eq 2025 and doc_type eq 'report' and fund_name eq '공무원연금기금'"
    ]


# ═══════════════════════════════════════════════════════════════════════════════
# Task 6 — Structured catalog/aggregation tool tests
# ═══════════════════════════════════════════════════════════════════════════════

from ingest.catalog import FundCatalogEntry
from ingest.facts import EvaluationFact
from search.structured import (
    AnalyticsRow,
    AnalyticsYearSummary,
    EvaluationAggregate,
    FundAnalyticsResult,
)


def _make_catalog_entry(
    toc_order: int,
    canonical_name: str,
    ministry: str,
    year: int = 2025,
    fund_id: str | None = None,
    aliases: list[str] | None = None,
) -> FundCatalogEntry:
    fid = fund_id or canonical_name
    return FundCatalogEntry(
        id=f"report-{year}/{toc_order:03d}",
        fund_id=fid,
        year=year,
        doc_id=f"report-{year}",
        toc_order=toc_order,
        canonical_name=canonical_name,
        aliases=aliases or [],
        ministry=ministry,
        fund_scale=None,
        start_page_printed=100 + toc_order,
        end_page_printed=110 + toc_order,
        start_page_physical=100 + toc_order,
        end_page_physical=110 + toc_order,
        source_page_physical=5,
    )


def _make_fact(
    fund_id: str,
    fund_name: str,
    year: int = 2025,
    metric_code: str = "quantitative_total",
    metric_name: str = "계량지표 합계",
    score: float | None = 80.0,
    max_score: float | None = 100.0,
    grade: str | None = None,
    grade_rank: int | None = None,
    ministry: str = "기획재정부",
    source_chunk_id: str | None = None,
) -> EvaluationFact:
    chunk_id = source_chunk_id or f"chunk-{fund_id}-{metric_code}"
    return EvaluationFact(
        id=f"fact-{fund_id}-{metric_code}-{year}",
        fund_id=fund_id,
        fund_name=fund_name,
        doc_id=f"report-{year}",
        year=year,
        ministry=ministry,
        fact_type="score" if score is not None else "grade",
        metric_code=metric_code,
        metric_name=metric_name,
        score=score,
        max_score=max_score,
        grade=grade,
        grade_rank=grade_rank,
        source_chunk_id=chunk_id,
        source_page_physical=42,
        source_section_path="Ⅲ > 1. 기금A > 평가결과 총괄표",
        source_text=f"{fund_name} {metric_name} {score or grade}",
    )


SAMPLE_CATALOG = [
    _make_catalog_entry(1, "공무원연금기금", "인사혁신처"),
    _make_catalog_entry(2, "국민연금기금", "보건복지부"),
    _make_catalog_entry(3, "사학연금기금", "교육부", aliases=["사립학교교직원연금기금"]),
]

SAMPLE_FACTS = [
    _make_fact("공무원연금기금", "공무원연금기금", score=85.0, source_chunk_id="chunk-001"),
    _make_fact("국민연금기금", "국민연금기금", score=92.0, source_chunk_id="chunk-002"),
    _make_fact("사학연금기금", "사학연금기금", score=78.0, source_chunk_id="chunk-003"),
]


@pytest.fixture()
def patch_structured(monkeypatch):
    """Monkeypatch search.structured operations so no network calls are made."""
    import search.structured as _smod

    monkeypatch.setattr(_smod, "list_funds", lambda year, ministry=None: [
        e for e in SAMPLE_CATALOG
        if e.year == year and (ministry is None or e.ministry == ministry)
    ])

    def _resolve(name, year=None):
        for e in SAMPLE_CATALOG:
            if name in [e.canonical_name] + e.aliases:
                if year is None or e.year == year:
                    return e
        return None

    monkeypatch.setattr(_smod, "resolve_fund", _resolve)

    monkeypatch.setattr(_smod, "get_fund_evaluations", lambda fund_name, year, metric=None: [
        f for f in SAMPLE_FACTS
        if f.fund_name == fund_name and f.year == year
        and (metric is None or metric in (f.metric_code, f.metric_name))
    ])

    def _aggregate(year, metric=None, *, order="desc", limit=3, ministry=None, per_fund=False):
        pop = [e for e in SAMPLE_CATALOG if e.year == year and (ministry is None or e.ministry == ministry)]
        facts = [f for f in SAMPLE_FACTS if f.year == year and (ministry is None or f.ministry == ministry)]
        matched_ids = {f.fund_id for f in facts}
        missing = [e.canonical_name for e in pop if e.fund_id not in matched_ids]
        rev = (order == "desc")
        ranked = sorted([f for f in facts if f.score is not None], key=lambda f: f.score or 0, reverse=rev)
        if not per_fund:
            ranked = ranked[:limit]
        return EvaluationAggregate(
            year=year, metric=metric, order=order, limit=limit,
            per_fund=per_fund, ministry=ministry,
            population_count=len(pop), matched_count=len(matched_ids),
            missing_funds=missing, rows=ranked,
        )

    monkeypatch.setattr(_smod, "aggregate_evaluations", _aggregate)


class TestMakeSearchToolsReturnsAllTools:
    """make_search_tools must return legacy + new structured tools."""

    def test_tool_count_and_names(self, patch_structured):
        rec = TraceRecorder()
        all_tools = make_search_tools(rec)
        names = {t.__name__ for t in all_tools}
        # Legacy
        assert "search_narrative" in names
        assert "search_tables" in names
        # New structured
        assert "list_funds" in names
        assert "resolve_fund" in names
        assert "get_fund_evaluations" in names
        assert "aggregate_evaluations" in names
        assert "fund_analytics" in names
        assert len(all_tools) == 7


class TestListFundsTool:
    def test_output_has_count_and_ordered_funds(self, patch_structured):
        rec = TraceRecorder()
        all_tools = make_search_tools(rec)
        list_funds_fn = [t for t in all_tools if t.__name__ == "list_funds"][0]
        out = list_funds_fn(year=2025)
        assert "3" in out  # total count
        assert "공무원연금기금" in out
        assert "국민연금기금" in out
        assert "사학연금기금" in out
        # Must show ministry
        assert "인사혁신처" in out or "보건복지부" in out

    def test_ministry_filter(self, patch_structured):
        rec = TraceRecorder()
        all_tools = make_search_tools(rec)
        list_funds_fn = [t for t in all_tools if t.__name__ == "list_funds"][0]
        out = list_funds_fn(year=2025, ministry="인사혁신처")
        assert "공무원연금기금" in out
        assert "국민연금기금" not in out

    def test_records_exhaustive_catalog_source_for_absence_citations(
        self, patch_structured
    ):
        rec = TraceRecorder()
        all_tools = make_search_tools(rec)
        list_funds_fn = [t for t in all_tools if t.__name__ == "list_funds"][0]

        out = list_funds_fn(year=2025)

        assert "[출처 1]" in out
        assert len(rec.sources) == 1
        source = rec.sources[0]
        assert source.index == "fund-catalog-index"
        assert source.chunk_type == "catalog"
        assert source.source_chunk_id == "catalog-list:2025:*"
        for entry in SAMPLE_CATALOG:
            assert entry.canonical_name in source.snippet


class TestResolveFundTool:
    def test_resolve_canonical(self, patch_structured):
        rec = TraceRecorder()
        all_tools = make_search_tools(rec)
        resolve_fn = [t for t in all_tools if t.__name__ == "resolve_fund"][0]
        out = resolve_fn(name="국민연금기금", year=2025)
        assert "국민연금기금" in out
        assert "보건복지부" in out

    def test_resolve_alias(self, patch_structured):
        rec = TraceRecorder()
        all_tools = make_search_tools(rec)
        resolve_fn = [t for t in all_tools if t.__name__ == "resolve_fund"][0]
        out = resolve_fn(name="사립학교교직원연금기금", year=2025)
        assert "사학연금기금" in out

    def test_resolve_not_found(self, patch_structured):
        rec = TraceRecorder()
        all_tools = make_search_tools(rec)
        resolve_fn = [t for t in all_tools if t.__name__ == "resolve_fund"][0]
        out = resolve_fn(name="존재하지않는기금", year=2025)
        # Korean error message
        assert "기금" in out and ("없" in out or "찾을 수 없" in out)


class TestGetFundEvaluationsTool:
    def test_records_structured_tool_output_as_evidence(self, patch_structured):
        rec = TraceRecorder()
        all_tools = make_search_tools(rec)
        get_evals_fn = [t for t in all_tools if t.__name__ == "get_fund_evaluations"][0]

        out = get_evals_fn(
            fund_name="국민연금기금",
            year=2025,
            metric="quantitative_total",
        )

        assert rec.evidence == [out]

    def test_returns_facts_with_citations(self, patch_structured):
        rec = TraceRecorder()
        all_tools = make_search_tools(rec)
        get_evals_fn = [t for t in all_tools if t.__name__ == "get_fund_evaluations"][0]
        out = get_evals_fn(fund_name="국민연금기금", year=2025)
        assert "[출처" in out
        assert "계량지표 합계" in out
        assert "92" in out
        # Source recorded
        assert len(rec.sources) >= 1
        assert rec.sources[-1].chunk_type == "fact"

    def test_source_has_provenance_fields(self, patch_structured):
        rec = TraceRecorder()
        all_tools = make_search_tools(rec)
        get_evals_fn = [t for t in all_tools if t.__name__ == "get_fund_evaluations"][0]
        get_evals_fn(fund_name="공무원연금기금", year=2025)
        src = rec.sources[-1]
        assert src.chunk_type == "fact"
        assert src.source_chunk_id is not None
        assert "chunk-001" in src.source_chunk_id

    def test_no_duplicate_sources_for_same_chunk_id(self, patch_structured):
        rec = TraceRecorder()
        all_tools = make_search_tools(rec)
        get_evals_fn = [t for t in all_tools if t.__name__ == "get_fund_evaluations"][0]
        # Call twice for the same fund
        get_evals_fn(fund_name="국민연금기금", year=2025)
        get_evals_fn(fund_name="국민연금기금", year=2025)
        chunk_ids = [s.source_chunk_id for s in rec.sources if s.source_chunk_id == "chunk-002"]
        assert len(chunk_ids) == 1  # no duplicates

    def test_citation_number_reused_for_duplicate(self, patch_structured):
        rec = TraceRecorder()
        all_tools = make_search_tools(rec)
        get_evals_fn = [t for t in all_tools if t.__name__ == "get_fund_evaluations"][0]
        out1 = get_evals_fn(fund_name="국민연금기금", year=2025)
        out2 = get_evals_fn(fund_name="국민연금기금", year=2025)
        # Both outputs should reference the same citation number
        import re as _re
        nums1 = _re.findall(r"\[출처 (\d+)\]", out1)
        nums2 = _re.findall(r"\[출처 (\d+)\]", out2)
        assert nums1 and nums2
        assert nums1[0] == nums2[0]

    def test_no_data_korean_message(self, patch_structured):
        rec = TraceRecorder()
        all_tools = make_search_tools(rec)
        get_evals_fn = [t for t in all_tools if t.__name__ == "get_fund_evaluations"][0]
        out = get_evals_fn(fund_name="존재하지않는기금", year=2025)
        assert "없" in out or "찾을 수 없" in out

    def test_formats_metric_value_score_and_grade_transition(
        self, patch_structured, monkeypatch
    ):
        import search.structured as _smod

        fact = _make_fact(
            "공무원연금기금",
            "공무원연금기금",
            metric_code="medium_long_term_three_year_yield",
            metric_name="중장기자산 3년 운용수익률",
            score=9.6,
            max_score=None,
            grade="탁월",
            grade_rank=5,
        ).model_copy(
            update={
                "metric_value": 12.21,
                "unit": "%",
                "pre_grade": "양호",
                "final_grade": "탁월",
            }
        )
        monkeypatch.setattr(_smod, "get_fund_evaluations", lambda **kwargs: [fact])

        rec = TraceRecorder()
        fns = {tool.__name__: tool for tool in make_search_tools(rec)}
        out = fns["get_fund_evaluations"](
            fund_name="공무원연금기금", year=2025
        )

        assert "지표값 12.21%" in out
        assert "평가점수 9.6" in out
        assert "사전등급 양호 → 최종등급 탁월" in out

    def test_formats_positive_adjustment(self, patch_structured, monkeypatch):
        import search.structured as _smod

        fact = _make_fact(
            "고용보험기금",
            "고용보험기금",
            metric_code="adjustment_innovation_growth",
            metric_name="혁신성장 투자",
            score=None,
            max_score=None,
        ).model_copy(
            update={"fact_type": "adjustment", "adjustment": 1.0}
        )
        monkeypatch.setattr(_smod, "get_fund_evaluations", lambda **kwargs: [fact])

        rec = TraceRecorder()
        fns = {tool.__name__: tool for tool in make_search_tools(rec)}
        out = fns["get_fund_evaluations"](fund_name="고용보험기금", year=2025)

        assert "혁신성장 투자: +1" in out

    def test_adjustment_query_includes_deterministic_total(
        self, patch_structured, monkeypatch
    ):
        import search.structured as _smod

        facts = [
            _make_fact(
                "고용보험기금",
                "고용보험기금",
                metric_code="adjustment_innovation_growth",
                metric_name="혁신성장 투자",
                score=None,
                max_score=None,
            ).model_copy(update={"fact_type": "adjustment", "adjustment": 1.0}),
            _make_fact(
                "고용보험기금",
                "고용보험기금",
                metric_code="adjustment_short_term_pool",
                metric_name="단기자금 통합",
                score=None,
                max_score=None,
            ).model_copy(update={"fact_type": "adjustment", "adjustment": -0.25}),
        ]
        monkeypatch.setattr(_smod, "get_fund_evaluations", lambda **kwargs: facts)

        rec = TraceRecorder()
        fns = {tool.__name__: tool for tool in make_search_tools(rec)}
        out = fns["get_fund_evaluations"](
            fund_name="고용보험기금", year=2025, metric="가감점"
        )

        assert "혁신성장 투자: +1" in out
        assert "단기자금 통합: -0.25" in out
        assert "총 가감점: +0.75" in out

    def test_asset_management_performance_includes_evaluated_rank(
        self, patch_structured, monkeypatch
    ):
        import search.structured as _smod

        target = _make_fact(
            "최저등급기금",
            "최저등급기금",
            year=2022,
            metric_code="asset_management_performance",
            metric_name="자산운용 성과",
            score=19.42,
            max_score=50.0,
            grade="보통",
            grade_rank=4,
        )
        ranking_facts = [
            _make_fact(
                f"상위기금-{index}",
                f"상위기금-{index}",
                year=2022,
                metric_code="asset_management_performance",
                metric_name="자산운용 성과",
                score=50.0 - index,
                max_score=50.0,
            )
            for index in range(1, 25)
        ] + [target] + [
            _make_fact(
                f"하위기금-{index}",
                f"하위기금-{index}",
                year=2022,
                metric_code="asset_management_performance",
                metric_name="자산운용 성과",
                score=float(5 - index),
                max_score=50.0,
            )
            for index in range(5)
        ]
        captured = {}

        def _analytics(**kwargs):
            captured.update(kwargs)
            return FundAnalyticsResult(
                operation="rank",
                metric="asset_management_performance",
                years=[2022],
                population="evaluated",
                summaries=[
                    AnalyticsYearSummary(
                        year=2022,
                        catalog_count=31,
                        population_count=30,
                        matched_count=30,
                        population_basis="annual_summary",
                        missing_funds=[],
                        grade_distribution={},
                    )
                ],
                rows=[
                    AnalyticsRow(
                        fund_id=fact.fund_id,
                        fund_name=fact.fund_name,
                        facts=[fact],
                    )
                    for fact in ranking_facts
                ],
            )

        monkeypatch.setattr(_smod, "get_fund_evaluations", lambda **kwargs: [target])
        monkeypatch.setattr(_smod, "fund_analytics", _analytics)
        rec = TraceRecorder()
        fns = {tool.__name__: tool for tool in make_search_tools(rec)}

        out = fns["get_fund_evaluations"](
            fund_name="최저등급기금",
            year=2022,
            metric="asset_management_performance",
        )

        assert captured == {
            "operation": "rank",
            "years": [2022],
            "metric": "asset_management_performance",
            "population": "evaluated",
            "order": "desc",
            "limit": 100,
        }
        assert "19.42/50" in out
        assert "30개 중 25위" in out
        assert "최종등급" not in out
        assert "보통" not in out
        assert rec.steps[-1].tool == "fund_analytics"
        assert "population=evaluated" in rec.steps[-1].query
        assert len(rec.sources) == 30


class TestAggregateEvaluationsTool:
    def test_output_has_coverage_and_rows(self, patch_structured):
        rec = TraceRecorder()
        all_tools = make_search_tools(rec)
        agg_fn = [t for t in all_tools if t.__name__ == "aggregate_evaluations"][0]
        out = agg_fn(year=2025, metric="quantitative_total", order="desc", limit=3)
        # Must include population and matched counts
        assert "3" in out  # population
        # Must include ranked funds
        assert "국민연금기금" in out
        # Must have citations
        assert "[출처" in out

    def test_missing_funds_disclosure(self, patch_structured, monkeypatch):
        """If some funds lack facts, they must be disclosed."""
        import search.structured as _smod

        extra_entry = _make_catalog_entry(4, "우체국예금기금", "과학기술정보통신부")

        monkeypatch.setattr(_smod, "list_funds", lambda year, ministry=None: SAMPLE_CATALOG + [extra_entry])

        def _aggregate(year, metric=None, *, order="desc", limit=3, ministry=None, per_fund=False):
            pop = SAMPLE_CATALOG + [extra_entry]
            facts = SAMPLE_FACTS  # 우체국예금기금 has no facts
            matched_ids = {f.fund_id for f in facts}
            missing = [e.canonical_name for e in pop if e.fund_id not in matched_ids]
            ranked = sorted([f for f in facts if f.score is not None], key=lambda f: f.score or 0, reverse=True)[:limit]
            return EvaluationAggregate(
                year=year, metric=metric, order=order, limit=limit,
                per_fund=per_fund, ministry=ministry,
                population_count=len(pop), matched_count=len(matched_ids),
                missing_funds=missing, rows=ranked,
            )

        monkeypatch.setattr(_smod, "aggregate_evaluations", _aggregate)

        rec = TraceRecorder()
        all_tools = make_search_tools(rec)
        agg_fn = [t for t in all_tools if t.__name__ == "aggregate_evaluations"][0]
        out = agg_fn(year=2025, metric="quantitative_total")
        # Must disclose missing fund
        assert "우체국예금기금" in out
        # Must NOT say complete/전체 when incomplete
        assert "4" in out  # population count

    def test_limit_bounds_error(self, patch_structured):
        rec = TraceRecorder()
        all_tools = make_search_tools(rec)
        agg_fn = [t for t in all_tools if t.__name__ == "aggregate_evaluations"][0]
        # limit 0 → error
        out = agg_fn(year=2025, metric="quantitative_total", limit=0)
        assert "1" in out and "100" in out  # mentions valid range
        # limit 101 → error
        out2 = agg_fn(year=2025, metric="quantitative_total", limit=101)
        assert "1" in out2 and "100" in out2

    def test_invalid_order_error(self, patch_structured):
        rec = TraceRecorder()
        all_tools = make_search_tools(rec)
        agg_fn = [t for t in all_tools if t.__name__ == "aggregate_evaluations"][0]
        out = agg_fn(year=2025, metric="quantitative_total", order="invalid")
        assert "asc" in out and "desc" in out

    def test_per_fund_formatting(self, patch_structured):
        rec = TraceRecorder()
        all_tools = make_search_tools(rec)
        agg_fn = [t for t in all_tools if t.__name__ == "aggregate_evaluations"][0]
        out = agg_fn(year=2025, metric="quantitative_total", per_fund=True)
        # Should show all funds with data
        assert "공무원연금기금" in out
        assert "국민연금기금" in out

    def test_sources_recorded_with_fact_type(self, patch_structured):
        rec = TraceRecorder()
        all_tools = make_search_tools(rec)
        agg_fn = [t for t in all_tools if t.__name__ == "aggregate_evaluations"][0]
        agg_fn(year=2025, metric="quantitative_total")
        fact_sources = [s for s in rec.sources if s.chunk_type == "fact"]
        assert len(fact_sources) >= 1

    def test_year_validation(self, patch_structured):
        rec = TraceRecorder()
        all_tools = make_search_tools(rec)
        agg_fn = [t for t in all_tools if t.__name__ == "aggregate_evaluations"][0]
        out = agg_fn(year=1800, metric="quantitative_total")
        # Should mention valid year range
        assert "연도" in out or "2000" in out


class TestFundAnalyticsTool:
    def test_rank_output_has_population_basis_and_citations(self, patch_structured):
        rec = TraceRecorder()
        fns = {tool.__name__: tool for tool in make_search_tools(rec)}

        out = fns["fund_analytics"](
            operation="rank",
            years=[2025],
            metric="quantitative_total",
            limit=3,
        )

        assert "Python 결정적 집계" in out
        assert "모집단 기준" in out
        assert "국민연금기금" in out
        assert "[출처" in out
        assert rec.steps[-1].tool == "fund_analytics"

    def test_rank_forwards_and_discloses_evaluated_population(
        self, patch_structured, monkeypatch
    ):
        import search.structured as _smod

        captured = {}
        fact = _make_fact(
            "최저등급기금",
            "최저등급기금",
            year=2022,
            metric_code="asset_management_performance",
            metric_name="자산운용 성과",
            score=19.42,
            max_score=50.0,
            grade="보통",
            grade_rank=4,
        )

        def _analytics(**kwargs):
            captured.update(kwargs)
            return FundAnalyticsResult(
                operation="rank",
                metric="asset_management_performance",
                years=[2022],
                population="evaluated",
                summaries=[
                    AnalyticsYearSummary(
                        year=2022,
                        catalog_count=31,
                        population_count=30,
                        matched_count=30,
                        population_basis="annual_summary",
                        missing_funds=[],
                        grade_distribution={"보통": 1},
                    )
                ],
                rows=[
                    AnalyticsRow(
                        fund_id=fact.fund_id,
                        fund_name=fact.fund_name,
                        facts=[fact],
                    )
                ],
            )

        monkeypatch.setattr(_smod, "fund_analytics", _analytics)
        rec = TraceRecorder()
        fns = {tool.__name__: tool for tool in make_search_tools(rec)}

        out = fns["fund_analytics"](
            operation="rank",
            years=[2022],
            metric="asset_management_performance",
            population="evaluated",
            limit=100,
        )

        assert captured["population"] == "evaluated"
        assert "모집단 30개" in out
        assert "연간 종합평가표" in out
        assert "population=evaluated" in rec.steps[-1].query
        assert "평가점수 19.42/50" in out
        assert "최종등급" not in out
        assert "보통" not in out

    def test_invalid_comparison_returns_clear_error(self, patch_structured):
        rec = TraceRecorder()
        fns = {tool.__name__: tool for tool in make_search_tools(rec)}

        out = fns["fund_analytics"](
            operation="grade_changes",
            years=[2025],
        )

        assert "분석 오류" in out
        assert not rec.steps


# ═══════════════════════════════════════════════════════════════════════════════
# Review-fix tests — TraceStep recording for structured closures
# ═══════════════════════════════════════════════════════════════════════════════


class TestStructuredTraceSteps:
    """Each structured closure must append exactly one TraceStep per call."""

    def test_list_funds_records_trace_step(self, patch_structured):
        rec = TraceRecorder()
        fns = {t.__name__: t for t in make_search_tools(rec)}
        fns["list_funds"](year=2025)
        steps = [s for s in rec.steps if s.tool == "list_funds"]
        assert len(steps) == 1
        assert steps[0].n_hits == 3  # 3 catalog entries

    def test_list_funds_ministry_filter_trace(self, patch_structured):
        rec = TraceRecorder()
        fns = {t.__name__: t for t in make_search_tools(rec)}
        fns["list_funds"](year=2025, ministry="인사혁신처")
        step = rec.steps[-1]
        assert step.tool == "list_funds"
        assert step.n_hits == 1

    def test_resolve_fund_records_trace_step(self, patch_structured):
        rec = TraceRecorder()
        fns = {t.__name__: t for t in make_search_tools(rec)}
        fns["resolve_fund"](name="국민연금기금", year=2025)
        steps = [s for s in rec.steps if s.tool == "resolve_fund"]
        assert len(steps) == 1
        assert steps[0].n_hits == 1

    def test_resolve_fund_not_found_records_zero_hits(self, patch_structured):
        rec = TraceRecorder()
        fns = {t.__name__: t for t in make_search_tools(rec)}
        fns["resolve_fund"](name="없는기금")
        steps = [s for s in rec.steps if s.tool == "resolve_fund"]
        assert len(steps) == 1
        assert steps[0].n_hits == 0

    def test_get_fund_evaluations_records_trace_step(self, patch_structured):
        rec = TraceRecorder()
        fns = {t.__name__: t for t in make_search_tools(rec)}
        fns["get_fund_evaluations"](fund_name="국민연금기금", year=2025)
        steps = [s for s in rec.steps if s.tool == "get_fund_evaluations"]
        assert len(steps) == 1
        assert steps[0].n_hits == 1  # 1 fact for this fund

    def test_get_fund_evaluations_zero_results_trace(self, patch_structured):
        rec = TraceRecorder()
        fns = {t.__name__: t for t in make_search_tools(rec)}
        fns["get_fund_evaluations"](fund_name="없는기금", year=2025)
        steps = [s for s in rec.steps if s.tool == "get_fund_evaluations"]
        assert len(steps) == 1
        assert steps[0].n_hits == 0

    def test_aggregate_evaluations_records_trace_step(self, patch_structured):
        rec = TraceRecorder()
        fns = {t.__name__: t for t in make_search_tools(rec)}
        fns["aggregate_evaluations"](year=2025, metric="quantitative_total")
        steps = [s for s in rec.steps if s.tool == "aggregate_evaluations"]
        assert len(steps) == 1
        assert steps[0].n_hits == 3  # 3 aggregate rows

    def test_repeated_calls_append_separate_steps(self, patch_structured):
        """Multiple calls must each append a separate TraceStep, while sources still dedupe."""
        rec = TraceRecorder()
        fns = {t.__name__: t for t in make_search_tools(rec)}
        fns["get_fund_evaluations"](fund_name="국민연금기금", year=2025)
        fns["get_fund_evaluations"](fund_name="국민연금기금", year=2025)
        eval_steps = [s for s in rec.steps if s.tool == "get_fund_evaluations"]
        assert len(eval_steps) == 2  # separate steps
        # Sources still deduplicated
        chunk_ids = [s.source_chunk_id for s in rec.sources if s.source_chunk_id == "chunk-002"]
        assert len(chunk_ids) == 1


# ═══════════════════════════════════════════════════════════════════════════════
# Review-fix tests — resolve_fund year validation
# ═══════════════════════════════════════════════════════════════════════════════


class TestResolveFundYearValidation:
    """resolve_fund must validate year exactly like other tools."""

    def test_invalid_year_returns_korean_error(self, patch_structured):
        rec = TraceRecorder()
        fns = {t.__name__: t for t in make_search_tools(rec)}
        out = fns["resolve_fund"](name="국민연금기금", year=1800)
        assert "연도 오류" in out
        assert "2000" in out and "2099" in out

    def test_invalid_year_makes_no_structured_call(self, patch_structured, monkeypatch):
        """Invalid year must not call _structured.resolve_fund."""
        import search.structured as _smod
        calls: list[dict] = []
        original = _smod.resolve_fund

        def spy(name, year=None):
            calls.append({"name": name, "year": year})
            return original(name=name, year=year)

        monkeypatch.setattr(_smod, "resolve_fund", spy)

        rec = TraceRecorder()
        fns = {t.__name__: t for t in make_search_tools(rec)}
        fns["resolve_fund"](name="국민연금기금", year=1800)
        assert len(calls) == 0, "should not call _structured.resolve_fund with invalid year"

    def test_year_none_remains_valid(self, patch_structured):
        rec = TraceRecorder()
        fns = {t.__name__: t for t in make_search_tools(rec)}
        out = fns["resolve_fund"](name="국민연금기금", year=None)
        assert "국민연금기금" in out
        assert "연도 오류" not in out

    def test_resolve_invalid_year_has_trace_step_policy(self, patch_structured):
        """Validation error before Task 5 call records no TraceStep
        (consistent: no structured operation occurred)."""
        rec = TraceRecorder()
        fns = {t.__name__: t for t in make_search_tools(rec)}
        fns["resolve_fund"](name="국민연금기금", year=1800)
        resolve_steps = [s for s in rec.steps if s.tool == "resolve_fund"]
        # No step recorded because the structured backend was never called
        assert len(resolve_steps) == 0


class TestListFundsYearValidation:
    """Direct coverage for list_funds year validation path."""

    def test_invalid_year_returns_korean_error(self, patch_structured):
        rec = TraceRecorder()
        fns = {t.__name__: t for t in make_search_tools(rec)}
        out = fns["list_funds"](year=1800)
        assert "연도 오류" in out
        assert "2000" in out and "2099" in out

    def test_invalid_year_records_no_trace_step(self, patch_structured):
        rec = TraceRecorder()
        fns = {t.__name__: t for t in make_search_tools(rec)}
        fns["list_funds"](year=1800)
        list_steps = [s for s in rec.steps if s.tool == "list_funds"]
        assert len(list_steps) == 0
