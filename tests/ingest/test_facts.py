"""Tests for ingest.facts — TDD: write tests first, run RED, then implement."""
from __future__ import annotations

from pathlib import Path

import pytest

from ingest.models import Chunk
from ingest.catalog import FundCatalogEntry

CACHE_DIR = Path(".ingest_cache")

# ---------------------------------------------------------------------------
# Helpers: import targets (will fail until ingest/facts.py exists)
# ---------------------------------------------------------------------------

from ingest.facts import (  # noqa: E402  (intentionally after comment)
    EvaluationFact,
    GRADE_RANKS,
    extract_evaluation_facts,
    metric_code_for,
)

# ---------------------------------------------------------------------------
# Pure compact fixtures
# ---------------------------------------------------------------------------

def _make_chunk(
    content: str,
    *,
    doc_id: str = "report-2025",
    chunk_idx: int = 1,
    fund_id: str = "국유재산관리기금",
    fund_name: str = "국유재산관리기금",
    ministry: str = "기획재정부",
    year: int = 2025,
    chunk_type: str = "table",
    page_physical: int = 10,
    section_path: str = "Ⅲ. 기금별 자산운용평가 결과 > 기획재정부 > 국유재산관리기금",
) -> Chunk:
    return Chunk(
        id=f"{doc_id}-{chunk_idx}",
        doc_id=doc_id,
        content=content,
        chunk_type=chunk_type,
        section_path=section_path,
        page_physical=page_physical,
        year=year,
        doc_type="report",
        fund_id=fund_id,
        fund_name=fund_name,
        ministry=ministry,
    )


def _result_table_chunk(
    score: str = "26.15",
    grade: str = "보통",
    doc_id: str = "report-2025",
    chunk_idx: int = 1,
) -> Chunk:
    """Six-column 2025-style result table chunk (계량 section only)."""
    content = (
        "| 평가지표 (계량) |  | 배점 | 지표값 | 평가점수 | 최종등급 |\n"
        "|---|---|---|---|---|---|\n"
        f"| (4) 자산운용 성과 |  | 50.0 |  | {score} | {grade} |\n"
        f"| 계량지표 합계 |  | 50.0 |  | {score} | {grade} |\n"
    )
    return _make_chunk(content, doc_id=doc_id, chunk_idx=chunk_idx)


def _result_table_chunk_5col(
    score: str = "26.15",
    grade: str = "보통",
    doc_id: str = "report-2021",
    chunk_idx: int = 1,
) -> Chunk:
    """Five-column 2021-style result table chunk (계량 section only)."""
    content = (
        "| 평가지표 (계량) | 배점 | 지표값 | 평가점수 | 최종등급 |\n"
        "|---|---|---|---|---|\n"
        f"| (4) 자산운용 성과 | 50.0 |  | {score} | {grade} |\n"
        f"| 계량지표 합계 | 50.0 | :selected: | {score} | {grade} |\n"
    )
    return _make_chunk(content, doc_id=doc_id, chunk_idx=chunk_idx, year=2021)


def _full_table_chunk_5col(doc_id: str = "report-2021", chunk_idx: int = 1) -> Chunk:
    """Full 2021-style result table with both 비계량 and 계량 sections."""
    content = (
        "| 평가지표 (비계량) | 배점 | 지표값 | 투자풀가점 반영 전 등급 | 최종등급 |\n"
        "|---|---|---|---|---|\n"
        "| (1) 자산운용 체계 | 13.0 |  | 양호 | 탁월 |\n"
        "| 1 자산운용관련 거버넌스의 적정성 | 8.0 |  | 양호 | 탁월 |\n"
        "| 비계량지표 합계 | 50.0 |  | 양호 | 우수 |\n"
        "| 평가지표 (계량) | 배점 | 지표값 | 평가점수 | 최종등급 |\n"
        "|---|---|---|---|---|\n"
        "| (4) 자산운용 성과 | 50.0 |  | 26.15 | 보통 |\n"
        "| 1. 단기자산의 수익률 | 48W |  | 2.27 | 양호 |\n"
        "| 1 현금성자금 운용수익률 | 17Wa | 0.82% | 0.75 | 보통 |\n"
        "| 3 유동성자금 운용수익률 | 17Wb | - | - | - |\n"
        "| 계량지표 합계 | 50.0 | :selected: | 26.15 | 보통 |\n"
    )
    return _make_chunk(content, doc_id=doc_id, chunk_idx=chunk_idx, year=2021)


# ---------------------------------------------------------------------------
# Step 1: Five- and six-column result table parsing
# ---------------------------------------------------------------------------


def test_extracts_asset_management_performance_score_6col():
    """Brief-specified test for 6-column 2025 table."""
    facts = extract_evaluation_facts([_result_table_chunk(score="46.47", grade="탁월")])
    fact = next(f for f in facts if f.metric_code == "asset_management_performance")
    assert (fact.score, fact.max_score, fact.grade) == (46.47, 50.0, "탁월")
    assert fact.source_chunk_id == "report-2025-1"


def test_extracts_asset_management_performance_score_5col():
    """5-column 2021 table also parses correctly."""
    facts = extract_evaluation_facts([_result_table_chunk_5col(score="26.15", grade="보통")])
    fact = next(f for f in facts if f.metric_code == "asset_management_performance")
    assert (fact.score, fact.max_score, fact.grade) == (26.15, 50.0, "보통")
    assert fact.source_chunk_id == "report-2021-1"


def test_full_5col_table_sections_parsed():
    """Full 2021 table: 비계량 and 계량 sections both parsed."""
    facts = extract_evaluation_facts([_full_table_chunk_5col()])
    codes = {f.metric_code for f in facts}
    assert "asset_management_performance" in codes
    assert "qualitative_total" in codes
    assert "quantitative_total" in codes


def test_qualitative_fact_type_is_grade():
    """비계량 rows have fact_type='grade' (no 평가점수 column)."""
    facts = extract_evaluation_facts([_full_table_chunk_5col()])
    qt = next(f for f in facts if f.metric_code == "qualitative_total")
    assert qt.fact_type == "grade"
    assert qt.score is None
    assert qt.grade == "우수"


def test_quantitative_fact_type_is_score():
    """계량 rows with numeric 평가점수 have fact_type='score'."""
    facts = extract_evaluation_facts([_result_table_chunk()])
    amp = next(f for f in facts if f.metric_code == "asset_management_performance")
    assert amp.fact_type == "score"


def test_grade_rank_populated():
    """EvaluationFact.grade_rank is set from GRADE_RANKS for recognized grades."""
    facts = extract_evaluation_facts([_result_table_chunk(grade="탁월")])
    amp = next(f for f in facts if f.metric_code == "asset_management_performance")
    assert amp.grade == "탁월"
    assert amp.grade_rank == GRADE_RANKS["탁월"]


def test_preserves_metric_value_unit_and_grade_semantics():
    content = (
        "| 평가지표 (비계량) | 배점 | 지표값 | 투자풀가점 반영 전 등급 | 최종등급 |\n"
        "|---|---|---|---|---|\n"
        "| 2 자산운용 위험관리의 효율성 | 11 |  | 양호 | 우수 |\n"
        "| 평가지표 (계량) | 배점 | 지표값 | 평가점수 | 최종등급 |\n"
        "|---|---|---|---|---|\n"
        "| 1 중장기자산 3년 운용수익률 | 16(1-W) | 12.21% | 9.60 | 탁월 |\n"
    )

    facts = extract_evaluation_facts([_make_chunk(content)])

    yield_fact = next(f for f in facts if "3년 운용수익률" in f.metric_name)
    assert yield_fact.metric_code == "medium_long_term_three_year_yield"
    assert yield_fact.metric_value == pytest.approx(12.21)
    assert yield_fact.unit == "%"
    assert yield_fact.score == pytest.approx(9.60)
    assert yield_fact.pre_grade is None
    assert yield_fact.final_grade == "탁월"

    risk_fact = next(f for f in facts if "위험관리의 효율성" in f.metric_name)
    assert risk_fact.metric_code == "risk_management_efficiency"
    assert risk_fact.pre_grade == "양호"
    assert risk_fact.final_grade == "우수"
    assert risk_fact.grade == "우수"


def test_extracts_adjustment_row_without_llm_calculation():
    content = (
        "| 평가지표 (계량) |  | 배점 | 지표값 | 평가점수 | 최종등급 |\n"
        "|---|---|---|---|---|---|\n"
        "| (4) 자산운용 성과 |  | 50.0 |  | 30.69 | 양호 |\n"
        "| 조정 | 가 점 | 혁신성 | 장 투자 | 1.00 |  |\n"
        "| 전체 합계 |  | 100.0 |  | :selected: | 양호 |\n"
    )

    facts = extract_evaluation_facts([_make_chunk(content, fund_name="고용보험기금")])

    adjustment = next(f for f in facts if f.fact_type == "adjustment")
    assert adjustment.metric_code == "adjustment_innovation_growth"
    assert adjustment.metric_name == "혁신성장 투자"
    assert adjustment.adjustment == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Step 2: Grade rows, N/A, formulas, and duplicate facts
# ---------------------------------------------------------------------------


def test_formula_배점_not_parsed_as_max_score():
    """48W, 32(1-W), 17Wa etc. must not produce a numeric max_score.

    The leaf row '1. 단기자산의 수익률' has 배점='48W' and a numeric 평가점수=2.27,
    so a score fact MUST be emitted and max_score MUST be None.
    """
    facts = extract_evaluation_facts([_full_table_chunk_5col()])
    # leaf row '1. 단기자산의 수익률' has 배점='48W' and score=2.27 → MUST emit
    leaf = next((f for f in facts if "단기자산" in f.metric_name), None)
    assert leaf is not None, "Score fact for '단기자산의 수익률' must be emitted (score=2.27 is parseable)"
    assert leaf.score == pytest.approx(2.27), "Numeric 평가점수 must be preserved"
    assert leaf.max_score is None, "Formula 48W must not be parsed as max_score"


def test_na_score_row_produces_no_fact():
    """Row with '-' in score and grade columns is omitted entirely."""
    facts = extract_evaluation_facts([_full_table_chunk_5col()])
    # row '3 유동성자금 운용수익률' has both score='-' and grade='-'
    names = [f.metric_name for f in facts]
    assert not any("유동성자금 운용수익률" in n for n in names)


def test_unrecognized_grade_does_not_set_grade_rank():
    """Row with numeric score + unrecognized grade: fact emitted, grade/grade_rank are None.

    Spec: unrecognized grade strings (e.g. '신설') → grade=None, grade_rank=None.
    The row still has a numeric 배점 and a parseable 평가점수, so a score fact IS emitted.
    """
    # 비계량 section has no 평가점수 column — use 계량 section so score is parseable
    content = (
        "| 평가지표 (계량) | 배점 | 지표값 | 평가점수 | 최종등급 |\n"
        "|---|---|---|---|---|\n"
        "| 계량지표 합계 | 50.0 |  | 38.50 | 신설 |\n"
    )
    chunk = _make_chunk(content, year=2021)
    facts = extract_evaluation_facts([chunk])
    qt = next((f for f in facts if f.metric_code == "quantitative_total"), None)
    assert qt is not None, "Score fact must be emitted for row with numeric 평가점수 even if grade is unrecognized"
    assert qt.score == pytest.approx(38.50)
    assert qt.grade is None, "Unrecognized grade must produce grade=None"
    assert qt.grade_rank is None, "Unrecognized grade must produce grade_rank=None"


def test_duplicate_fact_id_rejected():
    """Passing the same chunk twice raises ValueError for duplicate IDs."""
    chunk = _result_table_chunk()
    with pytest.raises(ValueError, match="Duplicate fact ID"):
        extract_evaluation_facts([chunk, chunk])


# ---------------------------------------------------------------------------
# Unit tests for metric_code_for
# ---------------------------------------------------------------------------


def test_metric_code_for_known_bare():
    assert metric_code_for("자산운용 성과") == "asset_management_performance"


def test_metric_code_for_known_section_prefix():
    """(4) prefix must be stripped before lookup."""
    assert metric_code_for("(4) 자산운용 성과") == "asset_management_performance"


def test_metric_code_for_known_number_dot_prefix():
    assert metric_code_for("1. 단기자산의 수익률") == "short_term_yield"


def test_metric_code_for_unknown_deterministic():
    """Unknown labels get a deterministic hash code that starts with 'm_'."""
    code1 = metric_code_for("완전히 모르는 지표")
    code2 = metric_code_for("완전히 모르는 지표")
    assert code1 == code2
    assert code1.startswith("m_")


def test_metric_code_for_different_unknowns_different_codes():
    c1 = metric_code_for("알 수 없는 지표 A")
    c2 = metric_code_for("알 수 없는 지표 B")
    assert c1 != c2


# ---------------------------------------------------------------------------
# Misc guard tests
# ---------------------------------------------------------------------------


def test_non_table_chunks_ignored():
    """Narrative chunks are skipped even if they have fund_id."""
    chunk = _make_chunk("some narrative text", chunk_type="narrative")
    assert extract_evaluation_facts([chunk]) == []


def test_unannotated_chunk_ignored():
    """Chunks without fund_id are skipped."""
    content = (
        "| 평가지표 (계량) |  | 배점 | 지표값 | 평가점수 | 최종등급 |\n"
        "|---|---|---|---|---|---|\n"
        "| (4) 자산운용 성과 |  | 50.0 |  | 26.15 | 보통 |\n"
    )
    chunk = _make_chunk(content)
    chunk2 = chunk.model_copy(update={"fund_id": None})
    assert extract_evaluation_facts([chunk2]) == []


def test_table_chunk_without_result_header_ignored():
    """Table chunks whose content has no recognized result header are skipped."""
    content = "| 구 분 | 연중 운용평잔 | 자산별 비중 |\n|---|---|---|\n| 단기자산 | 78,971 | 8.83% |\n"
    chunk = _make_chunk(content)
    assert extract_evaluation_facts([chunk]) == []


# ---------------------------------------------------------------------------
# Finding 4: Single-record semantics — one fact per fund/year/metric
# ---------------------------------------------------------------------------


def test_single_record_score_row_carries_grade():
    """Spec: a row with numeric 평가점수 AND recognized grade → one fact_type='score' fact
    carrying both score and grade/grade_rank.  No duplicate 'grade' fact is created.
    """
    facts = extract_evaluation_facts([_result_table_chunk(score="46.47", grade="탁월")])
    amp_facts = [f for f in facts if f.metric_code == "asset_management_performance"]
    assert len(amp_facts) == 1, "Exactly one fact per fund/year/metric — no duplicates"
    f = amp_facts[0]
    assert f.fact_type == "score"
    assert f.score == pytest.approx(46.47)
    assert f.grade == "탁월"
    assert f.grade_rank == GRADE_RANKS["탁월"]


def test_single_record_grade_only_row():
    """Spec: a 비계량 row with no 평가점수 column but a recognized grade → one fact_type='grade' fact.
    score is None; grade/grade_rank are populated.
    """
    content = (
        "| 평가지표 (비계량) | 배점 | 지표값 | 투자풀가점 반영 전 등급 | 최종등급 |\n"
        "|---|---|---|---|---|\n"
        "| 비계량지표 합계 | 50.0 |  | 우수 | 우수 |\n"
    )
    chunk = _make_chunk(content, year=2021)
    facts = extract_evaluation_facts([chunk])
    qt_facts = [f for f in facts if f.metric_code == "qualitative_total"]
    assert len(qt_facts) == 1, "Exactly one fact for grade-only row"
    f = qt_facts[0]
    assert f.fact_type == "grade"
    assert f.score is None
    assert f.grade == "우수"
    assert f.grade_rank == GRADE_RANKS["우수"]


# ---------------------------------------------------------------------------
# Grade rank table
# ---------------------------------------------------------------------------


def test_grade_ranks_complete():
    expected = {"탁월": 5, "우수": 4, "양호": 3, "보통": 2, "미흡": 1, "아주미흡": 0}
    assert GRADE_RANKS == expected


def _catalog_entry(order: int, name: str) -> FundCatalogEntry:
    return FundCatalogEntry(
        id=f"report-2025/{order:03d}",
        fund_id=name,
        year=2025,
        doc_id="report-2025",
        toc_order=order,
        canonical_name=name,
        ministry="테스트부처",
        start_page_printed=100 + order,
        end_page_printed=100 + order,
        source_page_physical=3,
    )


def test_extracts_authoritative_overall_grades_using_catalog_names():
    catalog = [
        _catalog_entry(1, "사립학교교직원연금기금"),
        _catalog_entry(2, "공무원연금기금"),
        _catalog_entry(3, "장애인고용촉진및직업재활기금"),
        _catalog_entry(4, "중소벤처기업창업및진흥기금"),
    ]
    content = (
        "참고 7 기금 유형별 평가결과\n"
        "| 분류 | 평가결과 | 기금명 |\n"
        "|---|---|---|\n"
        "| 사회보험성 | 탁월 | 사립학교교직원연금기금 |\n"
        "|  | 우수 | 공무원연금기금 |\n"
        "| 사업성 | 탁월 | 장애인고용촉진 및직업재활기금 중소벤처기업창업및진흥기금 |\n"
    )
    chunk = _make_chunk(
        content,
        fund_id="",
        fund_name="",
        page_physical=41,
        section_path="Ⅱ. 평가결과 종합 > 참고 7 기금 유형별 평가결과",
    )

    facts = extract_evaluation_facts([chunk], catalog=catalog)

    overall = [f for f in facts if f.metric_code == "overall_grade"]
    assert len(overall) == 4
    assert {f.fund_name: f.grade for f in overall} == {
        "사립학교교직원연금기금": "탁월",
        "공무원연금기금": "우수",
        "장애인고용촉진및직업재활기금": "탁월",
        "중소벤처기업창업및진흥기금": "탁월",
    }
    assert all(f.source_chunk_id == chunk.id for f in overall)


def test_overall_grade_matching_does_not_confuse_overlapping_fund_names():
    catalog = [
        _catalog_entry(1, "산업기반신용보증기금"),
        _catalog_entry(2, "신용보증기금"),
        _catalog_entry(3, "주택금융신용보증기금"),
    ]
    content = (
        "참고 7 기금 유형별 평가결과\n"
        "| 분류 | 평가결과 | 기금명 |\n"
        "|---|---|---|\n"
        "| 금융성 | 우수 | 산업기반신용보증기금, 주택금융신용보증기금 |\n"
        "|  | 양호 | 신용보증기금 |\n"
    )
    chunk = _make_chunk(
        content,
        fund_id="",
        fund_name="",
        section_path="Ⅱ. 평가결과 종합 > 참고 7 기금 유형별 평가결과",
    )

    facts = extract_evaluation_facts([chunk], catalog=catalog)

    overall = [f for f in facts if f.metric_code == "overall_grade"]
    assert len(overall) == 3
    assert {f.fund_name for f in overall} == {
        "산업기반신용보증기금",
        "신용보증기금",
        "주택금융신용보증기금",
    }
    assert {f.fund_name: f.grade for f in overall} == {
        "산업기반신용보증기금": "우수",
        "신용보증기금": "양호",
        "주택금융신용보증기금": "우수",
    }


def test_overall_grade_row_rejects_partially_unresolved_names():
    catalog = [_catalog_entry(1, "신용보증기금")]
    content = (
        "참고 7 기금 유형별 평가결과\n"
        "| 분류 | 평가결과 | 기금명 |\n"
        "|---|---|---|\n"
        "| 금융성 | 양호 | 신용보증기금, 미확인기금 |\n"
    )
    chunk = _make_chunk(
        content,
        fund_id="",
        fund_name="",
        section_path="Ⅱ. 평가결과 종합 > 참고 7 기금 유형별 평가결과",
    )

    with pytest.raises(ValueError, match="Unresolved fund text"):
        extract_evaluation_facts([chunk], catalog=catalog)


def test_extracted_fact_doc_id_equals_source_chunk_doc_id():
    """EvaluationFact.doc_id must equal its source Chunk.doc_id."""
    chunk = _result_table_chunk(doc_id="report-2025")
    facts = extract_evaluation_facts([chunk])
    assert len(facts) > 0
    for f in facts:
        assert f.doc_id == "report-2025"


# ---------------------------------------------------------------------------
# Cache-backed integration tests
# ---------------------------------------------------------------------------


def _run_pipeline(cache_file: str, doc_id: str, year: int):
    import json
    from ingest.parser import _result_to_parsed
    from ingest.catalog import extract_fund_catalog, annotate_chunks
    from ingest.chunker import chunk_document

    data = json.load(open(cache_file))
    doc = _result_to_parsed(doc_id, data)
    catalog = extract_fund_catalog(doc, year=year, doc_id=doc_id)
    chunks = chunk_document(doc, year=year, doc_type="report")
    coverage = annotate_chunks(chunks, catalog)
    facts = extract_evaluation_facts(coverage.chunks, catalog=catalog)
    amp_facts = [f for f in facts if f.metric_code == "asset_management_performance"]
    overall_facts = [f for f in facts if f.metric_code == "overall_grade"]
    fund_ids_with_fact = {f.fund_id for f in amp_facts}
    catalog_fund_ids = {e.fund_id for e in catalog}
    missing = sorted(catalog_fund_ids - fund_ids_with_fact)
    return catalog, amp_facts, overall_facts, missing


@pytest.mark.skipif(not (CACHE_DIR / "report-2021.json").exists(), reason="cache unavailable")
def test_cache_2021_asset_management_performance():
    catalog, amp_facts, _overall_facts, missing = _run_pipeline(
        str(CACHE_DIR / "report-2021.json"), "report-2021", 2021
    )
    print(f"\n[2021] catalog={len(catalog)}, amp_facts={len(amp_facts)}, missing={len(missing)}")
    if missing:
        print(f"  missing fund_ids: {missing}")
    assert len(catalog) == 33, f"2021 catalog must have 33 funds, got {len(catalog)}"
    assert len(amp_facts) == 33, f"2021 must yield 33 asset_management_performance facts, got {len(amp_facts)}"
    assert missing == [], f"2021 missing funds: {missing}"


@pytest.mark.skipif(not (CACHE_DIR / "report-2022.json").exists(), reason="cache unavailable")
def test_cache_2022_asset_management_performance():
    catalog, amp_facts, _overall_facts, missing = _run_pipeline(
        str(CACHE_DIR / "report-2022.json"), "report-2022", 2022
    )
    print(f"\n[2022] catalog={len(catalog)}, amp_facts={len(amp_facts)}, missing={len(missing)}")
    if missing:
        print(f"  missing fund_ids: {missing}")
    assert len(catalog) == 31, f"2022 catalog must have 31 funds, got {len(catalog)}"
    assert len(amp_facts) == 31, f"2022 must yield 31 asset_management_performance facts, got {len(amp_facts)}"
    assert missing == [], f"2022 missing funds: {missing}"


@pytest.mark.skipif(not (CACHE_DIR / "report-2025.json").exists(), reason="cache unavailable")
def test_cache_2025_asset_management_performance():
    catalog, amp_facts, _overall_facts, missing = _run_pipeline(
        str(CACHE_DIR / "report-2025.json"), "report-2025", 2025
    )
    print(f"\n[2025] catalog={len(catalog)}, amp_facts={len(amp_facts)}, missing={len(missing)}")
    if missing:
        print(f"  missing fund_ids: {missing}")
    assert len(catalog) == 25, f"2025 catalog must have 25 funds, got {len(catalog)}"
    assert len(amp_facts) == 25, f"2025 must yield 25 asset_management_performance facts, got {len(amp_facts)}"
    assert missing == [], f"2025 missing funds: {missing}"


@pytest.mark.parametrize(
    ("doc_id", "year", "expected_count", "expected_grades"),
    [
        ("report-2021", 2021, 32, {"탁월": 5, "우수": 9, "양호": 16, "보통": 1, "아주미흡": 1}),
        ("report-2022", 2022, 30, {"탁월": 4, "우수": 9, "양호": 11, "보통": 5, "미흡": 1}),
        ("report-2025", 2025, 24, {"탁월": 3, "우수": 9, "양호": 10, "보통": 1, "아주미흡": 1}),
    ],
)
def test_cached_overall_grade_population(
    doc_id: str,
    year: int,
    expected_count: int,
    expected_grades: dict[str, int],
):
    from collections import Counter

    cache_file = CACHE_DIR / f"{doc_id}.json"
    if not cache_file.exists():
        pytest.skip("cache unavailable")

    catalog, _amp_facts, overall_facts, _missing = _run_pipeline(
        str(cache_file), doc_id, year
    )

    assert len(overall_facts) == expected_count
    assert Counter(f.grade for f in overall_facts) == expected_grades
    excluded = {entry.fund_id for entry in catalog} - {
        fact.fund_id for fact in overall_facts
    }
    assert excluded == {"국민연금기금"}
