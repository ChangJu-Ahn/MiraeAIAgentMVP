"""Tests for search.structured — deterministic structured query operations.

All tests use monkeypatched SearchClient factories so no network is required.
"""
from __future__ import annotations

import base64
from typing import Any
from unittest.mock import MagicMock

import pytest

from ingest.catalog import FundCatalogEntry
from ingest.facts import EvaluationFact, GRADE_RANKS


# ── Fixtures: fake Azure Search result pages ────────────────────────────────


def _make_catalog_row(
    fund_id: str,
    canonical_name: str,
    year: int = 2025,
    toc_order: int = 1,
    ministry: str = "기획재정부",
    aliases: list[str] | None = None,
    doc_id: str = "report-2025",
    **extra: Any,
) -> dict[str, Any]:
    return {
        "id": f"{doc_id}/{toc_order:03d}",
        "fund_id": fund_id,
        "year": year,
        "doc_id": doc_id,
        "toc_order": toc_order,
        "canonical_name": canonical_name,
        "aliases": aliases or [],
        "ministry": ministry,
        "fund_scale": None,
        "start_page_printed": 10 + toc_order,
        "end_page_printed": 20 + toc_order,
        "start_page_physical": 30 + toc_order,
        "end_page_physical": 40 + toc_order,
        "source_page_physical": 5,
        **extra,
    }


def _make_fact_row(
    fund_id: str,
    fund_name: str,
    metric_code: str,
    metric_name: str,
    year: int = 2025,
    fact_type: str = "score",
    score: float | None = None,
    max_score: float | None = None,
    grade: str | None = None,
    grade_rank: int | None = None,
    ministry: str = "기획재정부",
    doc_id: str = "report-2025",
    **extra: Any,
) -> dict[str, Any]:
    return {
        "id": f"{doc_id}/{fund_id}/{metric_code}",
        "fund_id": fund_id,
        "fund_name": fund_name,
        "doc_id": doc_id,
        "year": year,
        "ministry": ministry,
        "fact_type": fact_type,
        "metric_code": metric_code,
        "metric_name": metric_name,
        "score": score,
        "max_score": max_score,
        "grade": grade,
        "grade_rank": grade_rank,
        "source_chunk_id": f"chunk-{fund_id}-{metric_code}",
        "source_page_physical": 100,
        "source_section_path": f"Ⅲ/{fund_name}",
        "source_text": f"{metric_name}: {score or grade}",
        **extra,
    }


def _fake_search_client(rows: list[dict[str, Any]]) -> MagicMock:
    """Return a MagicMock SearchClient whose .search() yields *rows*."""
    client = MagicMock()
    client.search.return_value = iter(rows)
    return client


def _search_key(logical_id: str) -> str:
    token = base64.urlsafe_b64encode(logical_id.encode("utf-8")).decode("ascii")
    return f"b64_{token}"


# ── Catalog data ─────────────────────────────────────────────────────────────

_CATALOG_2025 = [
    _make_catalog_row("공무원연금기금", "공무원연금기금", toc_order=1, ministry="인사혁신처"),
    _make_catalog_row("국민연금기금", "국민연금기금", toc_order=2, ministry="보건복지부"),
    _make_catalog_row("사립학교교직원연금기금", "사립학교교직원연금기금", toc_order=3,
                      ministry="교육부", aliases=["사학연금기금"]),
    _make_catalog_row("O'Brien기금", "O'Brien기금", toc_order=4, ministry="기획재정부"),
    _make_catalog_row("국민체육진흥기금(국민체육진흥계정)", "국민체육진흥기금(국민체육진흥계정)",
                      toc_order=5, ministry="문화체육관광부"),
]

_CATALOG_2022 = [
    _make_catalog_row("공무원연금기금", "공무원연금기금", year=2022, toc_order=1,
                      ministry="인사혁신처", doc_id="report-2022"),
    _make_catalog_row("국민연금기금", "국민연금기금", year=2022, toc_order=2,
                      ministry="보건복지부", doc_id="report-2022"),
]

# ── Fact data ────────────────────────────────────────────────────────────────

_FACTS_2025 = [
    # 공무원연금기금 — score 85
    _make_fact_row("공무원연금기금", "공무원연금기금", "asset_management_performance",
                   "자산운용 성과", score=85.0, max_score=100.0, ministry="인사혁신처"),
    # 국민연금기금 — score 92
    _make_fact_row("국민연금기금", "국민연금기금", "asset_management_performance",
                   "자산운용 성과", score=92.0, max_score=100.0, ministry="보건복지부"),
    # 사립학교교직원연금기금 — score 88
    _make_fact_row("사립학교교직원연금기금", "사립학교교직원연금기금",
                   "asset_management_performance", "자산운용 성과",
                   score=88.0, max_score=100.0, ministry="교육부"),
    # O'Brien기금 — score 90 (tests quote escaping)
    _make_fact_row("O'Brien기금", "O'Brien기금", "asset_management_performance",
                   "자산운용 성과", score=90.0, max_score=100.0, ministry="기획재정부"),
    # 국민체육진흥기금 — no score, grade only
    _make_fact_row("국민체육진흥기금(국민체육진흥계정)", "국민체육진흥기금(국민체육진흥계정)",
                   "asset_management_performance", "자산운용 성과",
                   fact_type="grade", grade="우수", grade_rank=GRADE_RANKS["우수"],
                   ministry="문화체육관광부"),
]

# Grade-only facts for per-fund testing
_GRADE_FACTS_2025 = [
    # Fund 1 — three grades
    _make_fact_row("공무원연금기금", "공무원연금기금", "asset_management_framework",
                   "자산운용 체계", fact_type="grade", grade="탁월",
                   grade_rank=GRADE_RANKS["탁월"], ministry="인사혁신처"),
    _make_fact_row("공무원연금기금", "공무원연금기금", "asset_management_policy",
                   "자산운용 정책", fact_type="grade", grade="우수",
                   grade_rank=GRADE_RANKS["우수"], ministry="인사혁신처"),
    _make_fact_row("공무원연금기금", "공무원연금기금", "asset_management_execution",
                   "자산운용 집행", fact_type="grade", grade="양호",
                   grade_rank=GRADE_RANKS["양호"], ministry="인사혁신처"),
    _make_fact_row("공무원연금기금", "공무원연금기금", "qualitative_total",
                   "비계량지표 합계", fact_type="grade", grade="보통",
                   grade_rank=GRADE_RANKS["보통"], ministry="인사혁신처"),
    # Fund 2 — two grades
    _make_fact_row("국민연금기금", "국민연금기금", "asset_management_framework",
                   "자산운용 체계", fact_type="grade", grade="우수",
                   grade_rank=GRADE_RANKS["우수"], ministry="보건복지부"),
    _make_fact_row("국민연금기금", "국민연금기금", "asset_management_policy",
                   "자산운용 정책", fact_type="grade", grade="탁월",
                   grade_rank=GRADE_RANKS["탁월"], ministry="보건복지부"),
]


# ═══════════════════════════════════════════════════════════════════════════════
# list_funds
# ═══════════════════════════════════════════════════════════════════════════════


class TestListFunds:
    def test_returns_ordered_catalog(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from search import structured

        client = _fake_search_client(_CATALOG_2025)
        monkeypatch.setattr(structured, "_catalog_client", lambda: client)

        result = structured.list_funds(year=2025)

        assert len(result) == 5
        assert all(isinstance(r, FundCatalogEntry) for r in result)
        assert [r.toc_order for r in result] == [1, 2, 3, 4, 5]

    def test_decodes_search_key_to_logical_catalog_id(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from search import structured

        row = _make_catalog_row("국민연금기금", "국민연금기금")
        logical_id = row["id"]
        row["id"] = _search_key(logical_id)
        monkeypatch.setattr(
            structured, "_catalog_client", lambda: _fake_search_client([row])
        )

        result = structured.list_funds(year=2025)

        assert result[0].id == logical_id

    def test_filters_by_ministry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from search import structured

        rows = [r for r in _CATALOG_2025 if r["ministry"] == "인사혁신처"]
        client = _fake_search_client(rows)
        monkeypatch.setattr(structured, "_catalog_client", lambda: client)

        result = structured.list_funds(year=2025, ministry="인사혁신처")

        assert len(result) == 1
        assert result[0].canonical_name == "공무원연금기금"

    def test_deterministic_order_canonical_name_tiebreaker(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When toc_order is same, canonical_name breaks tie."""
        from search import structured

        rows = [
            _make_catalog_row("B기금", "B기금", toc_order=1),
            _make_catalog_row("A기금", "A기금", toc_order=1),
        ]
        client = _fake_search_client(rows)
        monkeypatch.setattr(structured, "_catalog_client", lambda: client)

        result = structured.list_funds(year=2025)
        assert [r.canonical_name for r in result] == ["A기금", "B기금"]

    def test_server_order_uses_only_sortable_catalog_fields(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from search import structured

        client = _fake_search_client(_CATALOG_2025)
        monkeypatch.setattr(structured, "_catalog_client", lambda: client)

        structured.list_funds(year=2025)

        assert client.search.call_args.kwargs["order_by"] == ["toc_order asc"]

    def test_quote_escaping_ministry_filter(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Ministry with embedded single quote is escaped for OData."""
        from search import structured

        client = _fake_search_client([])
        monkeypatch.setattr(structured, "_catalog_client", lambda: client)

        structured.list_funds(year=2025, ministry="It's a test")

        call_kwargs = client.search.call_args
        odata_filter = call_kwargs.kwargs.get("filter") or call_kwargs[1].get("filter") or ""
        assert "It''s a test" in odata_filter


# ═══════════════════════════════════════════════════════════════════════════════
# resolve_fund
# ═══════════════════════════════════════════════════════════════════════════════


class TestResolveFund:
    def test_resolve_by_canonical_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from search import structured

        client = _fake_search_client([_CATALOG_2025[0]])
        monkeypatch.setattr(structured, "_catalog_client", lambda: client)

        result = structured.resolve_fund("공무원연금기금", year=2025)

        assert result is not None
        assert result.canonical_name == "공무원연금기금"

    def test_resolve_by_alias(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from search import structured

        client = _fake_search_client([_CATALOG_2025[2]])
        monkeypatch.setattr(structured, "_catalog_client", lambda: client)

        result = structured.resolve_fund("사학연금기금", year=2025)

        assert result is not None
        assert result.canonical_name == "사립학교교직원연금기금"

    def test_resolve_no_match_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from search import structured

        client = _fake_search_client([])
        monkeypatch.setattr(structured, "_catalog_client", lambda: client)

        result = structured.resolve_fund("존재하지않는기금", year=2025)
        assert result is None

    def test_resolve_yearless_same_fund_id_latest(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Same fund_id in multiple years → resolve to latest year."""
        from search import structured

        rows = [
            _make_catalog_row("공무원연금기금", "공무원연금기금", year=2022, toc_order=1,
                              doc_id="report-2022"),
            _make_catalog_row("공무원연금기금", "공무원연금기금", year=2025, toc_order=1),
        ]
        client = _fake_search_client(rows)
        monkeypatch.setattr(structured, "_catalog_client", lambda: client)

        result = structured.resolve_fund("공무원연금기금")

        assert result is not None
        assert result.year == 2025

    def test_resolve_yearless_different_fund_ids_ambiguous(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Distinct fund_ids for same normalized name → None (ambiguous)."""
        from search import structured

        rows = [
            _make_catalog_row("TestA", "Test기금", year=2022, toc_order=1,
                              doc_id="report-2022"),
            _make_catalog_row("TestB", "Test기금", year=2025, toc_order=1),
        ]
        client = _fake_search_client(rows)
        monkeypatch.setattr(structured, "_catalog_client", lambda: client)

        result = structured.resolve_fund("Test기금")
        assert result is None

    def test_resolve_quote_in_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Name with single-quote is properly escaped in OData filter."""
        from search import structured

        client = _fake_search_client([_CATALOG_2025[3]])
        monkeypatch.setattr(structured, "_catalog_client", lambda: client)

        result = structured.resolve_fund("O'Brien기금", year=2025)
        assert result is not None
        assert result.fund_id == "O'Brien기금"

        call_kwargs = client.search.call_args
        odata_filter = call_kwargs.kwargs.get("filter") or ""
        assert "O''Brien기금" in odata_filter


# ═══════════════════════════════════════════════════════════════════════════════
# get_fund_evaluations
# ═══════════════════════════════════════════════════════════════════════════════


class TestGetFundEvaluations:
    def test_returns_facts_for_resolved_fund(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from search import structured

        catalog_client = _fake_search_client([_CATALOG_2025[0]])
        facts_client = _fake_search_client([_FACTS_2025[0]])
        monkeypatch.setattr(structured, "_catalog_client", lambda: catalog_client)
        monkeypatch.setattr(structured, "_facts_client", lambda: facts_client)

        result = structured.get_fund_evaluations("공무원연금기금", year=2025)

        assert len(result) == 1
        assert isinstance(result[0], EvaluationFact)
        assert result[0].fund_id == "공무원연금기금"

    def test_decodes_search_key_to_logical_fact_id(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from search import structured

        fact_row = dict(_FACTS_2025[0])
        logical_id = fact_row["id"]
        fact_row["id"] = _search_key(logical_id)
        monkeypatch.setattr(
            structured,
            "_catalog_client",
            lambda: _fake_search_client([_CATALOG_2025[0]]),
        )
        monkeypatch.setattr(
            structured, "_facts_client", lambda: _fake_search_client([fact_row])
        )

        result = structured.get_fund_evaluations("공무원연금기금", year=2025)

        assert result[0].id == logical_id

    def test_metric_filter_by_code(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from search import structured

        catalog_client = _fake_search_client([_CATALOG_2025[0]])
        facts_client = _fake_search_client([_FACTS_2025[0]])
        monkeypatch.setattr(structured, "_catalog_client", lambda: catalog_client)
        monkeypatch.setattr(structured, "_facts_client", lambda: facts_client)

        result = structured.get_fund_evaluations(
            "공무원연금기금", year=2025, metric="asset_management_performance"
        )
        assert len(result) == 1

        # Verify the OData filter sent to SearchClient contains the code clause
        call_kwargs = facts_client.search.call_args
        odata_filter = call_kwargs.kwargs.get("filter") or ""
        assert "metric_code eq 'asset_management_performance'" in odata_filter, (
            f"Expected metric_code eq clause in filter; got: {odata_filter!r}"
        )

    def test_metric_filter_by_exact_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from search import structured

        catalog_client = _fake_search_client([_CATALOG_2025[0]])
        facts_client = _fake_search_client([_FACTS_2025[0]])
        monkeypatch.setattr(structured, "_catalog_client", lambda: catalog_client)
        monkeypatch.setattr(structured, "_facts_client", lambda: facts_client)

        result = structured.get_fund_evaluations(
            "공무원연금기금", year=2025, metric="자산운용 성과"
        )
        assert len(result) == 1

        # Verify the OData filter sent to SearchClient contains the name clause
        call_kwargs = facts_client.search.call_args
        odata_filter = call_kwargs.kwargs.get("filter") or ""
        assert "metric_name eq '자산운용 성과'" in odata_filter, (
            f"Expected metric_name eq clause in filter; got: {odata_filter!r}"
        )

    def test_human_metric_label_adds_stable_code_filter(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from search import structured

        catalog_client = _fake_search_client([_CATALOG_2025[0]])
        facts_client = _fake_search_client([])
        monkeypatch.setattr(structured, "_catalog_client", lambda: catalog_client)
        monkeypatch.setattr(structured, "_facts_client", lambda: facts_client)

        structured.get_fund_evaluations(
            "공무원연금기금", year=2025, metric="중장기자산 3년 운용수익률"
        )

        odata_filter = facts_client.search.call_args.kwargs["filter"]
        assert "metric_code eq 'medium_long_term_three_year_yield'" in odata_filter

    @pytest.mark.parametrize("metric", ["가감점", "조정", "가점", "감점", "adjustment"])
    def test_adjustment_alias_filters_by_fact_type(
        self, monkeypatch: pytest.MonkeyPatch, metric: str
    ) -> None:
        from search import structured

        catalog_client = _fake_search_client([_CATALOG_2025[0]])
        facts_client = _fake_search_client([])
        monkeypatch.setattr(structured, "_catalog_client", lambda: catalog_client)
        monkeypatch.setattr(structured, "_facts_client", lambda: facts_client)

        structured.get_fund_evaluations(
            "공무원연금기금", year=2025, metric=metric
        )

        odata_filter = facts_client.search.call_args.kwargs["filter"]
        assert "fact_type eq 'adjustment'" in odata_filter
        assert "metric_code" not in odata_filter

    def test_unresolved_fund_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from search import structured

        catalog_client = _fake_search_client([])
        monkeypatch.setattr(structured, "_catalog_client", lambda: catalog_client)

        result = structured.get_fund_evaluations("없는기금", year=2025)
        assert result == []

    def test_deterministic_sort(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Facts should be sorted by metric_code then metric_name."""
        from search import structured

        facts = [
            _make_fact_row("공무원연금기금", "공무원연금기금", "zzz_metric",
                           "zzz", score=10.0, ministry="인사혁신처"),
            _make_fact_row("공무원연금기금", "공무원연금기금", "aaa_metric",
                           "aaa", score=20.0, ministry="인사혁신처"),
        ]
        catalog_client = _fake_search_client([_CATALOG_2025[0]])
        facts_client = _fake_search_client(facts)
        monkeypatch.setattr(structured, "_catalog_client", lambda: catalog_client)
        monkeypatch.setattr(structured, "_facts_client", lambda: facts_client)

        result = structured.get_fund_evaluations("공무원연금기금", year=2025)
        assert [f.metric_code for f in result] == ["aaa_metric", "zzz_metric"]


# ═══════════════════════════════════════════════════════════════════════════════
# aggregate_evaluations
# ═══════════════════════════════════════════════════════════════════════════════


class TestAggregateEvaluations:
    def test_overall_grade_uses_annual_summary_population(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from search import structured

        catalog = [
            _make_catalog_row("평가기금", "평가기금", toc_order=1),
            _make_catalog_row("제외기금", "제외기금", toc_order=2),
        ]
        facts = [
            _make_fact_row(
                "평가기금", "평가기금", "overall_grade", "종합등급",
                fact_type="grade", grade="탁월", grade_rank=GRADE_RANKS["탁월"],
                source_scope="annual_summary", population_scope="evaluated",
            )
        ]
        monkeypatch.setattr(structured, "_catalog_client", lambda: _fake_search_client(catalog))
        monkeypatch.setattr(structured, "_facts_client", lambda: _fake_search_client(facts))

        result = structured.aggregate_evaluations(
            year=2025, metric="overall_grade", limit=10
        )

        assert result.catalog_count == 2
        assert result.population_count == 1
        assert result.matched_count == 1
        assert result.population_basis == "annual_summary"
        assert result.missing_funds == ["제외기금"]

    def test_metric_query_rejects_mixed_population_semantics(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from search import structured

        catalog = [
            _make_catalog_row("A기금", "A기금", toc_order=1),
            _make_catalog_row("B기금", "B기금", toc_order=2),
        ]
        facts = [
            _make_fact_row(
                "A기금", "A기금", "overall_grade", "종합등급",
                fact_type="grade", grade="탁월", grade_rank=GRADE_RANKS["탁월"],
                source_scope="annual_summary", population_scope="evaluated",
            ),
            _make_fact_row(
                "B기금", "B기금", "overall_grade", "종합등급",
                fact_type="grade", grade="우수", grade_rank=GRADE_RANKS["우수"],
                source_scope="fund_detail", population_scope="catalog",
            ),
        ]
        monkeypatch.setattr(
            structured, "_catalog_client", lambda: _fake_search_client(catalog)
        )
        monkeypatch.setattr(
            structured, "_facts_client", lambda: _fake_search_client(facts)
        )

        with pytest.raises(ValueError, match="mixed population semantics"):
            structured.aggregate_evaluations(
                year=2025, metric="overall_grade", limit=10
            )

    def test_score_ranking_desc(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from search import structured

        catalog_client = _fake_search_client(_CATALOG_2025)
        facts_client = _fake_search_client(_FACTS_2025)
        monkeypatch.setattr(structured, "_catalog_client", lambda: catalog_client)
        monkeypatch.setattr(structured, "_facts_client", lambda: facts_client)

        result = structured.aggregate_evaluations(
            year=2025, metric="asset_management_performance", limit=3
        )

        assert isinstance(result, structured.EvaluationAggregate)
        assert result.population_count == 5
        # All 5 have facts: 4 score + 1 grade
        assert result.matched_count == 5
        assert result.missing_funds == []
        # Top 3 by score descending: 92, 90, 88
        assert len(result.rows) == 3
        scores = [r.score for r in result.rows if r.score is not None]
        assert scores == [92.0, 90.0, 88.0]

    def test_score_ranking_asc(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from search import structured

        catalog_client = _fake_search_client(_CATALOG_2025)
        facts_client = _fake_search_client(_FACTS_2025)
        monkeypatch.setattr(structured, "_catalog_client", lambda: catalog_client)
        monkeypatch.setattr(structured, "_facts_client", lambda: facts_client)

        result = structured.aggregate_evaluations(
            year=2025, metric="asset_management_performance", limit=3, order="asc"
        )
        # Score-based ascending: 85, 88, 90
        scores = [r.score for r in result.rows if r.score is not None]
        assert scores == [85.0, 88.0, 90.0]

    def test_grade_ranking_when_no_score(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Facts with no score fall back to grade_rank ordering."""
        from search import structured

        # All grade-only facts for one metric
        grade_facts = [
            _make_fact_row("A기금", "A기금", "qualitative_total", "비계량지표 합계",
                           fact_type="grade", grade="양호", grade_rank=GRADE_RANKS["양호"]),
            _make_fact_row("B기금", "B기금", "qualitative_total", "비계량지표 합계",
                           fact_type="grade", grade="탁월", grade_rank=GRADE_RANKS["탁월"]),
            _make_fact_row("C기금", "C기금", "qualitative_total", "비계량지표 합계",
                           fact_type="grade", grade="우수", grade_rank=GRADE_RANKS["우수"]),
        ]
        catalog = [
            _make_catalog_row("A기금", "A기금", toc_order=1),
            _make_catalog_row("B기금", "B기금", toc_order=2),
            _make_catalog_row("C기금", "C기금", toc_order=3),
        ]
        catalog_client = _fake_search_client(catalog)
        facts_client = _fake_search_client(grade_facts)
        monkeypatch.setattr(structured, "_catalog_client", lambda: catalog_client)
        monkeypatch.setattr(structured, "_facts_client", lambda: facts_client)

        result = structured.aggregate_evaluations(
            year=2025, metric="qualitative_total", limit=2
        )
        assert [r.grade for r in result.rows] == ["탁월", "우수"]

    def test_tie_breaking_deterministic(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Same score → tie-break by fund_id ascending."""
        from search import structured

        tie_facts = [
            _make_fact_row("ZZZ기금", "ZZZ기금", "asset_management_performance",
                           "자산운용 성과", score=90.0),
            _make_fact_row("AAA기금", "AAA기금", "asset_management_performance",
                           "자산운용 성과", score=90.0),
        ]
        catalog = [
            _make_catalog_row("ZZZ기금", "ZZZ기금", toc_order=1),
            _make_catalog_row("AAA기금", "AAA기금", toc_order=2),
        ]
        catalog_client = _fake_search_client(catalog)
        facts_client = _fake_search_client(tie_facts)
        monkeypatch.setattr(structured, "_catalog_client", lambda: catalog_client)
        monkeypatch.setattr(structured, "_facts_client", lambda: facts_client)

        result = structured.aggregate_evaluations(
            year=2025, metric="asset_management_performance", limit=2
        )
        assert [r.fund_id for r in result.rows] == ["AAA기금", "ZZZ기금"]

    def test_missing_funds_coverage(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Funds in catalog but not in facts appear in missing_funds."""
        from search import structured

        catalog = [
            _make_catalog_row("A기금", "A기금", toc_order=1),
            _make_catalog_row("B기금", "B기금", toc_order=2),
            _make_catalog_row("C기금", "C기금", toc_order=3),
        ]
        facts = [
            _make_fact_row("A기금", "A기금", "asset_management_performance",
                           "자산운용 성과", score=85.0),
        ]
        catalog_client = _fake_search_client(catalog)
        facts_client = _fake_search_client(facts)
        monkeypatch.setattr(structured, "_catalog_client", lambda: catalog_client)
        monkeypatch.setattr(structured, "_facts_client", lambda: facts_client)

        result = structured.aggregate_evaluations(
            year=2025, metric="asset_management_performance", limit=10
        )
        assert result.population_count == 3
        assert result.matched_count == 1
        assert result.missing_funds == ["B기금", "C기금"]  # catalog order
        assert len(result.rows) == 1

    def test_per_fund_top_3(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """per_fund=True returns top limit per fund, in catalog order."""
        from search import structured

        catalog = [
            _make_catalog_row("공무원연금기금", "공무원연금기금", toc_order=1, ministry="인사혁신처"),
            _make_catalog_row("국민연금기금", "국민연금기금", toc_order=2, ministry="보건복지부"),
        ]
        catalog_client = _fake_search_client(catalog)
        facts_client = _fake_search_client(_GRADE_FACTS_2025)
        monkeypatch.setattr(structured, "_catalog_client", lambda: catalog_client)
        monkeypatch.setattr(structured, "_facts_client", lambda: facts_client)

        result = structured.aggregate_evaluations(
            year=2025, limit=3, per_fund=True
        )
        # Fund 1 has 4 facts, limited to top 3 (descending grade_rank: 탁월5, 우수4, 양호3)
        # Fund 2 has 2 facts, both returned (탁월5, 우수4)
        assert result.population_count == 2
        assert result.matched_count == 2

        fund1_rows = [r for r in result.rows if r.fund_id == "공무원연금기금"]
        fund2_rows = [r for r in result.rows if r.fund_id == "국민연금기금"]
        assert len(fund1_rows) == 3
        assert len(fund2_rows) == 2

        # Fund 1 best first
        assert [r.grade_rank for r in fund1_rows] == [5, 4, 3]
        # Fund 2 best first
        assert [r.grade_rank for r in fund2_rows] == [5, 4]

        # Catalog order: fund1 rows before fund2 rows
        first_fund2_idx = next(
            i for i, r in enumerate(result.rows) if r.fund_id == "국민연금기금"
        )
        last_fund1_idx = max(
            i for i, r in enumerate(result.rows) if r.fund_id == "공무원연금기금"
        )
        assert last_fund1_idx < first_fund2_idx

    def test_per_fund_asc_worst_first(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """per_fund=True, order='asc' returns worst-first rows per fund in catalog order."""
        from search import structured

        catalog = [
            _make_catalog_row("공무원연금기금", "공무원연금기금", toc_order=1, ministry="인사혁신처"),
            _make_catalog_row("국민연금기금", "국민연금기금", toc_order=2, ministry="보건복지부"),
        ]
        catalog_client = _fake_search_client(catalog)
        facts_client = _fake_search_client(_GRADE_FACTS_2025)
        monkeypatch.setattr(structured, "_catalog_client", lambda: catalog_client)
        monkeypatch.setattr(structured, "_facts_client", lambda: facts_client)

        result = structured.aggregate_evaluations(
            year=2025, limit=3, per_fund=True, order="asc"
        )
        # Fund 1 has 4 facts; limit=3 worst-first (asc grade_rank): 보통(2), 양호(3), 우수(4)
        # Fund 2 has 2 facts; both returned worst-first: 우수(4), 탁월(5)
        fund1_rows = [r for r in result.rows if r.fund_id == "공무원연금기금"]
        fund2_rows = [r for r in result.rows if r.fund_id == "국민연금기금"]

        assert len(fund1_rows) == 3, f"Expected 3 fund1 rows, got {len(fund1_rows)}"
        assert len(fund2_rows) == 2, f"Expected 2 fund2 rows, got {len(fund2_rows)}"

        # Worst-first ascending by grade_rank within each fund
        assert [r.grade_rank for r in fund1_rows] == [2, 3, 4], (
            f"Fund1 grade_ranks wrong: {[r.grade_rank for r in fund1_rows]}"
        )
        assert [r.grade_rank for r in fund2_rows] == [4, 5], (
            f"Fund2 grade_ranks wrong: {[r.grade_rank for r in fund2_rows]}"
        )

        # Catalog order: all fund1 rows precede all fund2 rows
        fund1_indices = [i for i, r in enumerate(result.rows) if r.fund_id == "공무원연금기금"]
        fund2_indices = [i for i, r in enumerate(result.rows) if r.fund_id == "국민연금기금"]
        assert max(fund1_indices) < min(fund2_indices), (
            "Catalog order violated: fund2 rows appear before fund1 rows"
        )

    def test_limit_validation_too_low(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from search import structured

        catalog_client = _fake_search_client([])
        facts_client = _fake_search_client([])
        monkeypatch.setattr(structured, "_catalog_client", lambda: catalog_client)
        monkeypatch.setattr(structured, "_facts_client", lambda: facts_client)

        with pytest.raises(ValueError, match="limit"):
            structured.aggregate_evaluations(year=2025, limit=0)

    def test_limit_validation_too_high(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from search import structured

        catalog_client = _fake_search_client([])
        facts_client = _fake_search_client([])
        monkeypatch.setattr(structured, "_catalog_client", lambda: catalog_client)
        monkeypatch.setattr(structured, "_facts_client", lambda: facts_client)

        with pytest.raises(ValueError, match="limit"):
            structured.aggregate_evaluations(year=2025, limit=101)

    def test_invalid_order(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from search import structured

        catalog_client = _fake_search_client([])
        facts_client = _fake_search_client([])
        monkeypatch.setattr(structured, "_catalog_client", lambda: catalog_client)
        monkeypatch.setattr(structured, "_facts_client", lambda: facts_client)

        with pytest.raises(ValueError, match="order"):
            structured.aggregate_evaluations(year=2025, order="random")  # type: ignore[arg-type]

    def test_empty_facts_returns_coverage(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """No facts → population coverage, zero matched, no fabricated rows."""
        from search import structured

        catalog = [
            _make_catalog_row("A기금", "A기금", toc_order=1),
            _make_catalog_row("B기금", "B기금", toc_order=2),
        ]
        catalog_client = _fake_search_client(catalog)
        facts_client = _fake_search_client([])
        monkeypatch.setattr(structured, "_catalog_client", lambda: catalog_client)
        monkeypatch.setattr(structured, "_facts_client", lambda: facts_client)

        result = structured.aggregate_evaluations(year=2025, limit=3)
        assert result.population_count == 2
        assert result.matched_count == 0
        assert result.missing_funds == ["A기금", "B기금"]
        assert result.rows == []

    def test_complete_pagination_iteration(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """SearchClient returns a lazy iterator; all pages must be consumed."""
        from search import structured

        # Simulate many rows delivered by the search iterator
        many_facts = [
            _make_fact_row(f"fund{i}", f"fund{i}", "asset_management_performance",
                           "자산운용 성과", score=float(i))
            for i in range(50)
        ]
        catalog = [
            _make_catalog_row(f"fund{i}", f"fund{i}", toc_order=i + 1)
            for i in range(50)
        ]
        catalog_client = _fake_search_client(catalog)
        facts_client = _fake_search_client(many_facts)
        monkeypatch.setattr(structured, "_catalog_client", lambda: catalog_client)
        monkeypatch.setattr(structured, "_facts_client", lambda: facts_client)

        result = structured.aggregate_evaluations(
            year=2025, metric="asset_management_performance", limit=5
        )
        assert result.population_count == 50
        assert result.matched_count == 50
        assert result.missing_funds == []
        assert len(result.rows) == 5

    def test_no_semantic_search_used(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify search_text='*' is used, not semantic/vector search."""
        from search import structured

        catalog_client = _fake_search_client(_CATALOG_2025)
        facts_client = _fake_search_client(_FACTS_2025)
        monkeypatch.setattr(structured, "_catalog_client", lambda: catalog_client)
        monkeypatch.setattr(structured, "_facts_client", lambda: facts_client)

        structured.aggregate_evaluations(
            year=2025, metric="asset_management_performance", limit=3
        )

        # Both clients should use search_text="*"
        for c in (catalog_client, facts_client):
            call_args = c.search.call_args
            search_text = call_args.kwargs.get("search_text") or call_args.args[0]
            assert search_text == "*", f"Expected '*', got {search_text!r}"

    def test_ministry_filter_escaping(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Ministry with quotes is escaped properly in aggregate_evaluations."""
        from search import structured

        catalog_client = _fake_search_client([])
        facts_client = _fake_search_client([])
        monkeypatch.setattr(structured, "_catalog_client", lambda: catalog_client)
        monkeypatch.setattr(structured, "_facts_client", lambda: facts_client)

        structured.aggregate_evaluations(
            year=2025, ministry="It's a test", limit=1
        )

        call_kwargs = catalog_client.search.call_args
        odata_filter = call_kwargs.kwargs.get("filter") or ""
        assert "It''s a test" in odata_filter

    def test_facts_with_neither_score_nor_grade_rank_excluded(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Facts with neither score nor grade_rank are excluded from ranking."""
        from search import structured

        orphan_fact = _make_fact_row(
            "A기금", "A기금", "asset_management_performance", "자산운용 성과",
            fact_type="grade",  # no score, no grade_rank
        )
        scored_fact = _make_fact_row(
            "B기금", "B기금", "asset_management_performance", "자산운용 성과",
            score=50.0,
        )
        catalog = [
            _make_catalog_row("A기금", "A기금", toc_order=1),
            _make_catalog_row("B기금", "B기금", toc_order=2),
        ]
        catalog_client = _fake_search_client(catalog)
        facts_client = _fake_search_client([orphan_fact, scored_fact])
        monkeypatch.setattr(structured, "_catalog_client", lambda: catalog_client)
        monkeypatch.setattr(structured, "_facts_client", lambda: facts_client)

        result = structured.aggregate_evaluations(
            year=2025, metric="asset_management_performance", limit=5
        )
        # A기금 has fact but excluded from ranking → still matched (has a fact)
        # but its row won't appear in ranked output
        assert result.matched_count == 2
        assert len(result.rows) == 1
        assert result.rows[0].fund_id == "B기금"


# ═══════════════════════════════════════════════════════════════════════════════
# fund_analytics
# ═══════════════════════════════════════════════════════════════════════════════


def _annual_grade_aggregate(
    year: int,
    grades: dict[str, str],
) -> Any:
    from search.structured import EvaluationAggregate

    facts = [
        EvaluationFact(
            **_make_fact_row(
                fund_id,
                fund_id,
                "overall_grade",
                "종합등급",
                year=year,
                doc_id=f"report-{year}",
                fact_type="grade",
                grade=grade,
                grade_rank=GRADE_RANKS[grade],
                source_scope="annual_summary",
                population_scope="evaluated",
            )
        )
        for fund_id, grade in grades.items()
    ]
    return EvaluationAggregate(
        year=year,
        metric="overall_grade",
        order="desc",
        limit=100,
        population_count=len(facts),
        matched_count=len(facts),
        missing_funds=["국민연금기금"],
        rows=facts,
        catalog_count=len(facts) + 1,
        population_basis="annual_summary",
    )


class TestFundAnalytics:
    @pytest.fixture(autouse=True)
    def _aggregates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from search import structured

        aggregates = {
            2021: _annual_grade_aggregate(
                2021, {"A기금": "탁월", "B기금": "탁월", "C기금": "우수"}
            ),
            2022: _annual_grade_aggregate(
                2022, {"A기금": "탁월", "B기금": "우수", "C기금": "탁월"}
            ),
        }
        monkeypatch.setattr(
            structured,
            "aggregate_evaluations",
            lambda year, **kwargs: aggregates[year],
        )

    def test_distribution_is_counted_in_python(self) -> None:
        from search import structured

        result = structured.fund_analytics(
            operation="distribution", years=[2021], metric="overall_grade"
        )

        assert result.summaries[0].grade_distribution == {"탁월": 2, "우수": 1}
        assert result.summaries[0].population_count == 3
        assert result.summaries[0].catalog_count == 4
        assert len(result.rows) == 3

    def test_rank_can_be_scoped_to_annual_evaluated_population(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from search import structured

        score_facts = [
            EvaluationFact(
                **_make_fact_row(
                    fund_id,
                    fund_id,
                    "asset_management_performance",
                    "자산운용 성과",
                    year=2022,
                    doc_id="report-2022",
                    score=score,
                    max_score=50.0,
                    source_scope="fund_detail",
                    population_scope="catalog",
                )
            )
            for fund_id, score in (
                ("A기금", 30.0),
                ("평가제외기금", 25.0),
                ("최저등급기금", 19.42),
            )
        ]
        score_aggregate = structured.EvaluationAggregate(
            year=2022,
            metric="asset_management_performance",
            order="desc",
            limit=100,
            population_count=3,
            matched_count=3,
            missing_funds=[],
            rows=score_facts,
            catalog_count=3,
            population_basis="catalog",
        )
        grade_aggregate = _annual_grade_aggregate(
            2022,
            {"A기금": "우수", "최저등급기금": "미흡"},
        )

        monkeypatch.setattr(
            structured,
            "aggregate_evaluations",
            lambda year, metric, **kwargs: (
                grade_aggregate if metric == "overall_grade" else score_aggregate
            ),
        )

        result = structured.fund_analytics(
            operation="rank",
            years=[2022],
            metric="asset_management_performance",
            population="evaluated",
            limit=100,
        )

        assert result.population == "evaluated"
        assert result.summaries[0].catalog_count == 3
        assert result.summaries[0].population_count == 2
        assert result.summaries[0].matched_count == 2
        assert result.summaries[0].population_basis == "annual_summary"
        assert result.summaries[0].missing_funds == []
        assert [row.fund_name for row in result.rows] == ["A기금", "최저등급기금"]

    def test_grade_changes_are_directional_and_complete(self) -> None:
        from search import structured

        result = structured.fund_analytics(
            operation="grade_changes", years=[2021, 2022], metric="overall_grade"
        )

        assert result.common_count == 3
        assert result.unchanged_count == 1
        assert [(row.fund_name, row.direction) for row in result.rows] == [
            ("B기금", "down"),
            ("C기금", "up"),
        ]
        assert all(len(row.facts) == 2 for row in result.rows)

    def test_maintained_grade_uses_set_intersection(self) -> None:
        from search import structured

        result = structured.fund_analytics(
            operation="maintained_grade",
            years=[2021, 2022],
            metric="overall_grade",
            grade="탁월",
        )

        assert result.common_count == 3
        assert [row.fund_name for row in result.rows] == ["A기금"]
        assert [fact.grade for fact in result.rows[0].facts] == ["탁월", "탁월"]

    def test_comparison_requires_distinct_years(self) -> None:
        from search import structured

        with pytest.raises(ValueError, match="two distinct years"):
            structured.fund_analytics(
                operation="grade_changes", years=[2021, 2021]
            )

    def test_comparison_rejects_incompatible_value_kinds(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from search import structured

        first = _annual_grade_aggregate(2021, {"A기금": "탁월"})
        second = _annual_grade_aggregate(2022, {"A기금": "우수"})
        first.rows[0] = first.rows[0].model_copy(
            update={"score": 80.0, "grade": None, "grade_rank": None}
        )
        monkeypatch.setattr(
            structured,
            "aggregate_evaluations",
            lambda year, **kwargs: {2021: first, 2022: second}[year],
        )

        with pytest.raises(ValueError, match="incompatible analytics value kinds"):
            structured.fund_analytics(
                operation="compare_years", years=[2021, 2022]
            )

    def test_distribution_rejects_unrecognized_grade(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from search import structured

        aggregate = _annual_grade_aggregate(2021, {"A기금": "탁월"})
        aggregate.rows[0] = aggregate.rows[0].model_copy(
            update={"grade": "신설", "grade_rank": 6}
        )
        monkeypatch.setattr(
            structured,
            "aggregate_evaluations",
            lambda year, **kwargs: aggregate,
        )

        with pytest.raises(ValueError, match="unrecognized grade"):
            structured.fund_analytics(
                operation="distribution", years=[2021]
            )
