"""Extract normalized evaluation facts from catalog-annotated table Chunks.

Parses the DI-generated Markdown result tables from annual fund evaluation reports
and emits ``EvaluationFact`` records with exact source provenance.

Supported table formats
-----------------------
* Five-column (2021/2022 reports):
  ``평가지표 (비계량) | 배점 | 지표값 | 투자풀가점 반영 전 등급 | 최종등급``
  ``평가지표 (계량)   | 배점 | 지표값 | 평가점수 | 최종등급``

* Six-column (2025 reports):
  ``평가지표 (비계량) |  | 배점 | 지표값 | 투자풀가점 반영 전 등급 | 최종등급``
  ``평가지표 (계량)   |  | 배점 | 지표값 | 평가점수 | 최종등급``

Column positions are resolved semantically from the header row so that
new padding columns added in future reports do not break parsing.
"""
from __future__ import annotations

import hashlib
import re
from typing import Final, Literal

from pydantic import BaseModel

from ingest.catalog import FundCatalogEntry
from ingest.models import Chunk

# ── Grade → rank mapping ──────────────────────────────────────────────────────

GRADE_RANKS: Final[dict[str, int]] = {
    "탁월": 5,
    "우수": 4,
    "양호": 3,
    "보통": 2,
    "미흡": 1,
    "아주미흡": 0,
}

# ── Known metric name → stable code ──────────────────────────────────────────
# Keys are bare metric names after stripping "(N) ", "N. ", "N " prefixes.

_KNOWN_CODES: Final[dict[str, str]] = {
    "자산운용 성과": "asset_management_performance",
    "자산운용 체계": "asset_management_framework",
    "자산운용 정책": "asset_management_policy",
    "자산운용 집행": "asset_management_execution",
    "비계량지표 합계": "qualitative_total",
    "계량지표 합계": "quantitative_total",
    "전체 합계": "overall_grade",
    # sub-items
    "단기자산의 수익률": "short_term_yield",
    "중장기자산의 수익률": "medium_long_term_yield",
    "중장기자산 3년 운용수익률": "medium_long_term_three_year_yield",
    "위험대비 성과": "risk_adjusted_performance",
    "운용상품집중도": "product_concentration",
    "공공성확보 노력도": "public_interest_effort",
    "자산운용 위험관리의 효율성": "risk_management_efficiency",
    "혁신성장 투자": "adjustment_innovation_growth",
    "단기자금 통합": "adjustment_short_term_pool",
}

# ── Compiled patterns ─────────────────────────────────────────────────────────

# Recognized result-table header markers
_NONQUANT_HDR_RE: Final = re.compile(r"평가지표\s*\(비계량\)")
_QUANT_HDR_RE: Final = re.compile(r"평가지표\s*\(계량\)")

# Separator rows like |---|---|...
_SEPARATOR_CELL_RE: Final = re.compile(r"^[-:]+$")

# Formula배점 values: e.g. 48W, 32(1-W), 17Wa, 17Wb, 48W, 16(1-W)
_FORMULA_RE: Final = re.compile(r"^\d+[A-Za-z(]")

# Prefix-stripping patterns for metric names
_SECTION_PREFIX_RE: Final = re.compile(r"^\(\d+\)\s*")
_DOT_PREFIX_RE: Final = re.compile(r"^\d+\.\s*")
_LEAF_PREFIX_RE: Final = re.compile(r"^\d+\s+")

# Row type filter: only rows that look like legitimate metric rows are processed.
# Accepts: (N) …, N. …, N …, or rows ending with 합계
_METRIC_ROW_RE: Final = re.compile(
    r"^\(\d+\)|^\d+\.\s|^\d+\s|합계$"
)


# ── Public model ──────────────────────────────────────────────────────────────


class EvaluationFact(BaseModel):
    id: str
    fund_id: str
    fund_name: str
    doc_id: str
    year: int
    ministry: str
    fact_type: Literal["score", "grade", "adjustment"]
    metric_code: str
    metric_name: str
    metric_value: float | None = None
    unit: str | None = None
    score: float | None = None
    max_score: float | None = None
    pre_grade: str | None = None
    final_grade: str | None = None
    grade: str | None = None
    grade_rank: int | None = None
    adjustment: float | None = None
    source_scope: Literal["fund_detail", "annual_summary"] = "fund_detail"
    population_scope: Literal["catalog", "evaluated", "metric_available"] = "catalog"
    source_chunk_id: str
    source_page_physical: int
    source_section_path: str
    source_text: str


# ── Column layout (resolved from header row) ──────────────────────────────────


class _ColLayout:
    """Semantic column positions derived from a header row."""

    __slots__ = (
        "max_score_col",
        "metric_value_col",
        "score_col",
        "pre_grade_col",
        "grade_col",
    )

    def __init__(self, cells: list[str]) -> None:
        self.max_score_col: int | None = None
        self.metric_value_col: int | None = None
        self.score_col: int | None = None
        self.pre_grade_col: int | None = None
        self.grade_col: int | None = None
        for i, h in enumerate(cells):
            if h == "배점":
                self.max_score_col = i
            elif h == "지표값":
                self.metric_value_col = i
            elif h == "평가점수":
                self.score_col = i
            elif "반영 전 등급" in h:
                self.pre_grade_col = i
            elif h == "최종등급":
                self.grade_col = i

    @property
    def is_quant(self) -> bool:
        """True when the section has a numeric 평가점수 column."""
        return self.score_col is not None


# ── Helpers ───────────────────────────────────────────────────────────────────


def metric_code_for(name: str) -> str:
    """Return a stable metric code for *name*.

    Known metric names map to explicit ASCII codes.  Unknown names map to a
    deterministic ``m_<sha1[:8]>`` code so that any label can round-trip
    without ambiguity.

    Only ``(N)`` section-header prefixes and ``N.`` dot-separated sub-section
    prefixes are stripped before the lookup.  Leaf-item prefixes of the form
    ``N `` (digit followed by a space) are intentionally *not* stripped: doing
    so would produce the same code for a sub-section header (``4. 운용상품집중도``)
    and a same-named leaf item (``1 운용상품집중도``), causing a duplicate fact ID
    within the same table.
    """
    # Strip (N) and N. prefixes only — NOT the N-space leaf prefix
    cleaned = _SECTION_PREFIX_RE.sub("", name).strip()
    cleaned = _DOT_PREFIX_RE.sub("", cleaned).strip()

    if cleaned in _KNOWN_CODES:
        return _KNOWN_CODES[cleaned]
    if name in _KNOWN_CODES:
        return _KNOWN_CODES[name]

    leaf_cleaned = _LEAF_PREFIX_RE.sub("", name).strip()
    if leaf_cleaned in _KNOWN_CODES:
        code = _KNOWN_CODES[leaf_cleaned]
        if leaf_cleaned in {"운용상품집중도", "공공성확보 노력도"}:
            return f"{code}_value"
        return code

    return "m_" + hashlib.sha1(name.encode()).hexdigest()[:8]


def _parse_cells(line: str) -> list[str]:
    """Split a pipe-delimited Markdown row into stripped cell strings."""
    if not line.startswith("|"):
        return []
    parts = line.split("|")
    return [p.strip() for p in parts[1:-1]]


def _is_formula(value: str) -> bool:
    """True if *value* is a weighted-formula배점 (e.g. ``48W``, ``32(1-W)``)."""
    return bool(_FORMULA_RE.match(value.strip()))


def _parse_float(value: str) -> float | None:
    """Parse *value* as float; return None for empty, dashes, N/A, or checkboxes."""
    v = value.strip()
    if not v or v in ("-", "N/A", "n/a", ":selected:", ":unselected:"):
        return None
    # Strip trailing % or p (percentage point suffix) before float parse
    v_clean = re.sub(r"%p$|[%p]$", "", v).replace(",", "")
    try:
        return float(v_clean)
    except ValueError:
        return None


def _parse_metric_value(value: str) -> tuple[float | None, str | None]:
    """Parse a numeric metric value while retaining its report unit."""
    raw = value.strip()
    if raw.endswith("%p"):
        unit = "%p"
    elif raw.endswith("%"):
        unit = "%"
    else:
        unit = None
    return _parse_float(raw), unit


def _is_separator(cells: list[str]) -> bool:
    return bool(cells) and all(
        _SEPARATOR_CELL_RE.match(c) for c in cells if c
    )


# ── Core extraction ───────────────────────────────────────────────────────────


def extract_evaluation_facts(
    chunks: list[Chunk],
    *,
    catalog: list[FundCatalogEntry] | None = None,
) -> list[EvaluationFact]:
    """Extract normalized ``EvaluationFact`` records from catalog-annotated chunks.

    Only ``chunk_type='table'`` chunks with a ``fund_id`` that contain a
    recognized result-table header (``평가지표 (비계량)`` or ``평가지표 (계량)``)
    are processed.  Ambiguous rows are omitted; duplicate fact IDs raise
    ``ValueError``.
    """
    facts: list[EvaluationFact] = []
    seen_ids: set[str] = set()

    if catalog is not None:
        for chunk in chunks:
            if chunk.chunk_type != "table":
                continue
            if "참고 7 기금 유형별 평가결과" not in (
                f"{chunk.section_path}\n{chunk.content}"
            ):
                continue
            _parse_overall_grade_table(chunk, catalog, facts, seen_ids)

    for chunk in chunks:
        if chunk.chunk_type != "table":
            continue
        if not chunk.fund_id:
            continue
        if not (
            _NONQUANT_HDR_RE.search(chunk.content)
            or _QUANT_HDR_RE.search(chunk.content)
        ):
            continue

        _parse_result_table(chunk, facts, seen_ids)

    return facts


def _parse_result_table(
    chunk: Chunk,
    facts: list[EvaluationFact],
    seen_ids: set[str],
) -> None:
    """Parse one result-table chunk, appending facts into *facts*."""
    layout: _ColLayout | None = None

    for raw_line in chunk.content.split("\n"):
        line = raw_line.strip()
        if not line or not line.startswith("|"):
            continue

        cells = _parse_cells(line)
        if not cells:
            continue
        if _is_separator(cells):
            continue

        first = cells[0]

        # ── Detect section header rows and update layout ─────────────────────
        if _NONQUANT_HDR_RE.match(first):
            layout = _ColLayout(cells)
            continue
        if _QUANT_HDR_RE.match(first):
            layout = _ColLayout(cells)
            continue

        if layout is None:
            continue

        adjustment = _parse_adjustment_row(chunk, cells, layout)
        if adjustment is not None:
            if adjustment.id in seen_ids:
                raise ValueError(f"Duplicate fact ID: {adjustment.id!r}")
            seen_ids.add(adjustment.id)
            facts.append(adjustment)
            continue

        # ── Skip rows that don't look like metric rows ────────────────────────
        if not _METRIC_ROW_RE.search(first):
            continue

        # ── Extract values by semantic column position ────────────────────────
        max_score: float | None = None
        if layout.max_score_col is not None and layout.max_score_col < len(cells):
            raw_max = cells[layout.max_score_col]
            if not _is_formula(raw_max):
                max_score = _parse_float(raw_max)

        score: float | None = None
        if layout.score_col is not None and layout.score_col < len(cells):
            score = _parse_float(cells[layout.score_col])

        metric_value: float | None = None
        unit: str | None = None
        if (
            layout.metric_value_col is not None
            and layout.metric_value_col < len(cells)
        ):
            metric_value, unit = _parse_metric_value(
                cells[layout.metric_value_col]
            )

        pre_grade: str | None = None
        if layout.pre_grade_col is not None and layout.pre_grade_col < len(cells):
            candidate = cells[layout.pre_grade_col]
            if candidate in GRADE_RANKS:
                pre_grade = candidate

        raw_grade: str | None = None
        if layout.grade_col is not None and layout.grade_col < len(cells):
            g = cells[layout.grade_col]
            if g and g not in ("-", "N/A", "n/a"):
                raw_grade = g

        # Only recognized grades produce a grade field
        grade = raw_grade if (raw_grade in GRADE_RANKS) else None
        final_grade = grade
        grade_rank = GRADE_RANKS.get(grade) if grade else None

        has_score = layout.is_quant and score is not None
        has_grade = grade is not None

        if not has_score and not has_grade:
            continue  # ambiguous row — omit

        fact_type: Literal["score", "grade"] = "score" if has_score else "grade"

        metric_code = metric_code_for(first)
        fund_id = chunk.fund_id or ""
        fact_id = f"{chunk.doc_id}/{fund_id}/{metric_code}"

        if fact_id in seen_ids:
            if metric_code == "overall_grade":
                continue
            raise ValueError(f"Duplicate fact ID: {fact_id!r}")
        seen_ids.add(fact_id)

        facts.append(
            EvaluationFact(
                id=fact_id,
                fund_id=fund_id,
                fund_name=chunk.fund_name or fund_id,
                doc_id=chunk.doc_id,
                year=chunk.year or 0,
                ministry=chunk.ministry or "",
                fact_type=fact_type,
                metric_code=metric_code,
                metric_name=first,
                metric_value=metric_value,
                unit=unit,
                score=score,
                max_score=max_score,
                pre_grade=pre_grade,
                final_grade=final_grade,
                grade=grade,
                grade_rank=grade_rank,
                source_chunk_id=chunk.id,
                source_page_physical=chunk.page_physical,
                source_section_path=chunk.section_path,
                source_text=line,
            )
        )


def _parse_adjustment_row(
    chunk: Chunk,
    cells: list[str],
    layout: _ColLayout,
) -> EvaluationFact | None:
    compact = re.sub(r"\s+", "", "".join(cells))
    if not compact.startswith("조정"):
        return None

    adjustment: float | None = None
    if layout.score_col is not None and layout.score_col < len(cells):
        adjustment = _parse_float(cells[layout.score_col])
    if adjustment is None:
        return None
    if "감점" in compact:
        adjustment = -abs(adjustment)

    names: list[str] = []
    if "혁신성장투자" in compact:
        names.append("혁신성장 투자")
    if "단기자금통합" in compact:
        names.append("단기자금 통합")
    if not names:
        names.append("가감점")

    metric_name = " + ".join(names)
    metric_code = (
        metric_code_for(names[0])
        if len(names) == 1
        else "adjustment_combined"
    )
    fund_id = chunk.fund_id or ""
    return EvaluationFact(
        id=f"{chunk.doc_id}/{fund_id}/{metric_code}",
        fund_id=fund_id,
        fund_name=chunk.fund_name or fund_id,
        doc_id=chunk.doc_id,
        year=chunk.year or 0,
        ministry=chunk.ministry or "",
        fact_type="adjustment",
        metric_code=metric_code,
        metric_name=metric_name,
        adjustment=adjustment,
        source_chunk_id=chunk.id,
        source_page_physical=chunk.page_physical,
        source_section_path=chunk.section_path,
        source_text="| " + " | ".join(cells) + " |",
    )


def _compact_name(value: str) -> str:
    return re.sub(r"[\s,·]", "", value)


def _match_catalog_entries(
    fund_cell: str,
    catalog: list[FundCatalogEntry],
) -> tuple[list[FundCatalogEntry], str]:
    candidates: list[tuple[int, int, FundCatalogEntry]] = []
    for entry in catalog:
        for variant in {entry.canonical_name, *entry.aliases}:
            compact_variant = _compact_name(variant)
            for match in re.finditer(re.escape(compact_variant), fund_cell):
                candidate = (match.start(), match.end(), entry)
                if candidate not in candidates:
                    candidates.append(candidate)

    candidates.sort(key=lambda item: (-(item[1] - item[0]), item[0], item[2].toc_order))
    occupied: list[tuple[int, int]] = []
    selected: dict[str, FundCatalogEntry] = {}
    for start, end, entry in candidates:
        if entry.fund_id in selected:
            continue
        if any(start < used_end and used_start < end for used_start, used_end in occupied):
            continue
        selected[entry.fund_id] = entry
        occupied.append((start, end))

    unresolved = "".join(
        character
        for index, character in enumerate(fund_cell)
        if not any(start <= index < end for start, end in occupied)
    )
    return sorted(selected.values(), key=lambda entry: entry.toc_order), unresolved


def _parse_overall_grade_table(
    chunk: Chunk,
    catalog: list[FundCatalogEntry],
    facts: list[EvaluationFact],
    seen_ids: set[str],
) -> None:
    for raw_line in chunk.content.splitlines():
        cells = _parse_cells(raw_line.strip())
        if len(cells) < 3:
            continue
        grade = cells[1].replace(" ", "")
        if grade not in GRADE_RANKS or not cells[2].strip():
            continue

        fund_cell = _compact_name(cells[2])
        matched, unresolved = _match_catalog_entries(fund_cell, catalog)

        if not matched:
            raise ValueError(
                f"No catalog fund resolved from overall-grade row: {raw_line!r}"
            )
        if unresolved:
            raise ValueError(
                f"Unresolved fund text {unresolved!r} in overall-grade row: {raw_line!r}"
            )

        for entry in matched:
            fact_id = f"{chunk.doc_id}/{entry.fund_id}/overall_grade"
            if fact_id in seen_ids:
                raise ValueError(f"Duplicate fact ID: {fact_id!r}")
            seen_ids.add(fact_id)
            facts.append(
                EvaluationFact(
                    id=fact_id,
                    fund_id=entry.fund_id,
                    fund_name=entry.canonical_name,
                    doc_id=chunk.doc_id,
                    year=chunk.year or entry.year,
                    ministry=entry.ministry,
                    fact_type="grade",
                    metric_code="overall_grade",
                    metric_name="종합등급",
                    final_grade=grade,
                    grade=grade,
                    grade_rank=GRADE_RANKS[grade],
                    source_scope="annual_summary",
                    population_scope="evaluated",
                    source_chunk_id=chunk.id,
                    source_page_physical=chunk.page_physical,
                    source_section_path=chunk.section_path,
                    source_text=raw_line.strip(),
                )
            )
