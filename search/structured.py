"""Deterministic structured query operations against Azure AI Search indexes.

Provides exact-match, filter-based retrieval from the ``fund-catalog-index``
and ``evaluation-facts-index``.  All queries use ``search_text="*"`` with OData
filters — no semantic, vector, or full-text search is performed.

Public functions
----------------
- ``list_funds``
- ``resolve_fund``
- ``get_fund_evaluations``
- ``aggregate_evaluations``

Internal client factories ``_catalog_client`` and ``_facts_client`` are
module-level callables so that tests can monkeypatch them without touching
network code.
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Literal

from azure.identity import DefaultAzureCredential
from azure.search.documents import SearchClient
from pydantic import BaseModel

from config.settings import get_settings
from ingest.catalog import FundCatalogEntry, normalize_fund_name
from ingest.facts import EvaluationFact, GRADE_RANKS, metric_code_for
from ingest.structured_indexer import decode_search_key

# ── Type alias requested by the brief ─────────────────────────────────────────

CatalogFund = FundCatalogEntry

# ── Internal client factories (monkeypatchable for testing) ──────────────────


def _catalog_client() -> SearchClient:
    s = get_settings()
    return SearchClient(
        endpoint=s.search_endpoint,
        index_name=s.search_index_catalog,
        credential=DefaultAzureCredential(),
    )


def _facts_client() -> SearchClient:
    s = get_settings()
    return SearchClient(
        endpoint=s.search_endpoint,
        index_name=s.search_index_facts,
        credential=DefaultAzureCredential(),
    )


# ── OData helpers ────────────────────────────────────────────────────────────


def _escape_odata(value: str) -> str:
    """Escape a string for use inside OData single-quoted literals."""
    return value.replace("'", "''")


def _eq(field: str, value: str) -> str:
    return f"{field} eq '{_escape_odata(value)}'"


def _eq_int(field: str, value: int) -> str:
    return f"{field} eq {value}"


def _and(*clauses: str) -> str:
    return " and ".join(clauses)


_ADJUSTMENT_ALIASES = frozenset({"가감점", "조정", "가점", "감점", "adjustment"})


def _metric_filter(metric: str) -> str:
    if metric.strip().casefold() in _ADJUSTMENT_ALIASES:
        return _eq("fact_type", "adjustment")
    escaped_metric = _escape_odata(metric)
    clauses = [
        f"metric_code eq '{escaped_metric}'",
        f"metric_name eq '{escaped_metric}'",
    ]
    normalized_code = metric_code_for(metric)
    if normalized_code != metric and not normalized_code.startswith("m_"):
        clauses.append(f"metric_code eq '{_escape_odata(normalized_code)}'")
    return "(" + " or ".join(clauses) + ")"


# ── Result deserialization ───────────────────────────────────────────────────

# Azure metadata keys to strip before feeding into Pydantic models
_AZURE_META_PREFIXES = ("@search.", "@odata.")


def _strip_azure_meta(row: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in row.items() if not any(k.startswith(p) for p in _AZURE_META_PREFIXES)}


def _to_catalog_entry(row: dict[str, Any]) -> FundCatalogEntry:
    data = _strip_azure_meta(row)
    data["id"] = decode_search_key(data["id"])
    return FundCatalogEntry.model_validate(data)


def _to_evaluation_fact(row: dict[str, Any]) -> EvaluationFact:
    data = _strip_azure_meta(row)
    data["id"] = decode_search_key(data["id"])
    return EvaluationFact.model_validate(data)


# ── Exhaustive iteration ────────────────────────────────────────────────────


def _collect_all(results: Any) -> list[dict[str, Any]]:
    """Iterate a paged Azure Search result completely and return raw dicts."""
    return [dict(r) for r in results]


# ── Catalog fields used in select ────────────────────────────────────────────

_CATALOG_FIELDS = [
    "id", "fund_id", "year", "doc_id", "toc_order", "canonical_name",
    "aliases", "ministry", "fund_scale", "start_page_printed",
    "end_page_printed", "start_page_physical", "end_page_physical",
    "source_page_physical",
]

_FACT_FIELDS = [
    "id", "fund_id", "fund_name", "doc_id", "year", "ministry",
    "fact_type", "metric_code", "metric_name", "metric_value", "unit",
    "score", "max_score", "pre_grade", "final_grade", "grade", "grade_rank",
    "adjustment", "source_scope", "population_scope",
    "source_chunk_id", "source_page_physical",
    "source_section_path", "source_text",
]


# ── Public aggregate model ───────────────────────────────────────────────────


class EvaluationAggregate(BaseModel):
    """Serializable result of ``aggregate_evaluations``."""

    year: int
    metric: str | None = None
    order: Literal["asc", "desc"] = "desc"
    limit: int = 3
    per_fund: bool = False
    ministry: str | None = None
    population_count: int
    matched_count: int
    missing_funds: list[str]
    rows: list[EvaluationFact]
    catalog_count: int | None = None
    population_basis: Literal["catalog", "annual_summary", "metric_available"] = "catalog"


AnalyticsOperation = Literal[
    "rank",
    "distribution",
    "compare_years",
    "grade_changes",
    "maintained_grade",
]
AnalyticsPopulation = Literal["metric", "evaluated"]


class AnalyticsYearSummary(BaseModel):
    year: int
    catalog_count: int
    population_count: int
    matched_count: int
    population_basis: Literal["catalog", "annual_summary", "metric_available"]
    missing_funds: list[str]
    grade_distribution: dict[str, int]


class AnalyticsRow(BaseModel):
    fund_id: str
    fund_name: str
    facts: list[EvaluationFact]
    direction: Literal["up", "down", "same"] | None = None


class FundAnalyticsResult(BaseModel):
    operation: AnalyticsOperation
    metric: str
    years: list[int]
    population: AnalyticsPopulation = "metric"
    grade: str | None = None
    summaries: list[AnalyticsYearSummary]
    common_count: int | None = None
    unchanged_count: int | None = None
    rows: list[AnalyticsRow]


# ═══════════════════════════════════════════════════════════════════════════════
# list_funds
# ═══════════════════════════════════════════════════════════════════════════════


def list_funds(year: int, ministry: str | None = None) -> list[FundCatalogEntry]:
    """Return the complete ordered fund population for *year*.

    Results are sorted deterministically by ``(toc_order, canonical_name)``.
    """
    filters = [_eq_int("year", year)]
    if ministry is not None:
        filters.append(_eq("ministry", ministry))

    client = _catalog_client()
    results = client.search(
        search_text="*",
        filter=_and(*filters),
        select=_CATALOG_FIELDS,
        order_by=["toc_order asc"],
    )
    rows = _collect_all(results)
    entries = [_to_catalog_entry(r) for r in rows]
    entries.sort(key=lambda e: (e.toc_order, e.canonical_name))
    return entries


# ═══════════════════════════════════════════════════════════════════════════════
# resolve_fund
# ═══════════════════════════════════════════════════════════════════════════════


def resolve_fund(name: str, year: int | None = None) -> FundCatalogEntry | None:
    """Resolve *name* to a single catalog entry by exact canonical or alias match.

    - With *year*: filter to that year and match canonical or alias.
    - Without *year*: fetch all years.  If all matches share the same ``fund_id``,
      return the entry from the latest year.  If matches span different ``fund_id``
      values, return ``None`` (ambiguous).
    """
    normalized = normalize_fund_name(name)
    escaped = _escape_odata(normalized)

    # Build OR: canonical_name match OR alias in aliases collection
    name_filter = (
        f"(canonical_name eq '{escaped}'"
        f" or aliases/any(a: a eq '{escaped}'))"
    )
    filters = [name_filter]
    if year is not None:
        filters.append(_eq_int("year", year))

    client = _catalog_client()
    results = client.search(
        search_text="*",
        filter=_and(*filters),
        select=_CATALOG_FIELDS,
    )
    rows = _collect_all(results)
    if not rows:
        return None

    entries = [_to_catalog_entry(r) for r in rows]

    if year is not None:
        # Scoped to a single year — should be at most one canonical hit
        return entries[0] if entries else None

    # Yearless: check if all entries share the same fund_id
    fund_ids = {e.fund_id for e in entries}
    if len(fund_ids) > 1:
        return None  # ambiguous

    # Same fund_id across years → pick the latest year
    entries.sort(key=lambda e: e.year, reverse=True)
    return entries[0]


# ═══════════════════════════════════════════════════════════════════════════════
# get_fund_evaluations
# ═══════════════════════════════════════════════════════════════════════════════


def get_fund_evaluations(
    fund_name: str, year: int, metric: str | None = None
) -> list[EvaluationFact]:
    """Return structured evaluation facts for a resolved fund.

    *metric* matches by stable ``metric_code`` or by exact normalized
    ``metric_name``. Adjustment aliases such as ``가감점`` match all
    ``fact_type='adjustment'`` rows. If the fund cannot be resolved, returns ``[]``.
    """
    entry = resolve_fund(fund_name, year=year)
    if entry is None:
        return []

    filters = [
        _eq("fund_id", entry.fund_id),
        _eq_int("year", year),
    ]
    if metric is not None:
        filters.append(_metric_filter(metric))

    client = _facts_client()
    results = client.search(
        search_text="*",
        filter=_and(*filters),
        select=_FACT_FIELDS,
    )
    rows = _collect_all(results)
    facts = [_to_evaluation_fact(r) for r in rows]
    facts.sort(key=lambda f: (f.metric_code, f.metric_name))
    return facts


# ═══════════════════════════════════════════════════════════════════════════════
# aggregate_evaluations
# ═══════════════════════════════════════════════════════════════════════════════


def _sort_key(fact: EvaluationFact, order: Literal["asc", "desc"]) -> tuple:
    """Return a sort key for ranking.

    Score-bearing facts rank before grade-only facts (tier 0 vs 1) so that
    incomparable numeric scales are never intermixed.  Within each tier the
    value is sorted by *order*.  Tie-breaker: ``fund_id`` ascending.
    """
    if fact.score is not None:
        tier = 0
        value = -fact.score if order == "desc" else fact.score
    elif fact.grade_rank is not None:
        tier = 1
        value = -float(fact.grade_rank) if order == "desc" else float(fact.grade_rank)
    else:
        tier = 2
        value = 0.0

    return (tier, value, fact.fund_id)


def _population_basis(
    facts: list[EvaluationFact],
    *,
    metric: str | None,
) -> Literal["catalog", "annual_summary", "metric_available"]:
    if metric is None or not facts:
        return "catalog"

    semantics = {(fact.source_scope, fact.population_scope) for fact in facts}
    if semantics == {("annual_summary", "evaluated")}:
        return "annual_summary"
    if {population_scope for _, population_scope in semantics} == {
        "metric_available"
    }:
        return "metric_available"
    if semantics == {("fund_detail", "catalog")}:
        return "catalog"
    raise ValueError(
        f"mixed population semantics for metric={metric!r}: "
        f"{sorted(semantics)}"
    )


def aggregate_evaluations(
    year: int,
    metric: str | None = None,
    *,
    order: Literal["asc", "desc"] = "desc",
    limit: int = 3,
    ministry: str | None = None,
    per_fund: bool = False,
) -> EvaluationAggregate:
    """Rank funds by score or grade with complete population coverage info.

    Returns an ``EvaluationAggregate`` with ``population_count``,
    ``matched_count``, and ``missing_funds`` computed *before* ``limit``
    truncation.
    """
    # ── Validate inputs ──────────────────────────────────────────────────
    if not (1 <= limit <= 100):
        raise ValueError(f"limit must be 1..100, got {limit}")
    if order not in ("asc", "desc"):
        raise ValueError(f"order must be 'asc' or 'desc', got {order!r}")

    # ── Fetch authoritative population ───────────────────────────────────
    population = list_funds(year=year, ministry=ministry)
    catalog_fund_ids = {e.fund_id for e in population}
    catalog_fund_id_list = [e.fund_id for e in population]  # preserves catalog order

    # ── Fetch bounded complete fact set ──────────────────────────────────
    fact_filters = [_eq_int("year", year)]
    if ministry is not None:
        fact_filters.append(_eq("ministry", ministry))
    if metric is not None:
        fact_filters.append(_metric_filter(metric))

    client = _facts_client()
    results = client.search(
        search_text="*",
        filter=_and(*fact_filters),
        select=_FACT_FIELDS,
    )
    all_facts = [_to_evaluation_fact(r) for r in _collect_all(results)]

    # Scope to catalog fund_ids
    scoped_facts = [f for f in all_facts if f.fund_id in catalog_fund_ids]

    # ── Coverage metrics (before limit truncation) ───────────────────────
    matched_fund_ids = {f.fund_id for f in scoped_facts}
    missing_fund_ids = [fid for fid in catalog_fund_id_list if fid not in matched_fund_ids]
    # Missing names: canonical names in catalog order
    fund_id_to_canonical = {e.fund_id: e.canonical_name for e in population}
    missing_funds = [fund_id_to_canonical[fid] for fid in missing_fund_ids]

    # ── Exclude facts with neither score nor grade_rank ──────────────────
    rankable = [f for f in scoped_facts if f.score is not None or f.grade_rank is not None]

    # ── Ranking ──────────────────────────────────────────────────────────
    if per_fund:
        # Group by fund_id, limit per fund, preserve catalog order
        fund_groups: dict[str, list[EvaluationFact]] = {}
        for fact in rankable:
            fund_groups.setdefault(fact.fund_id, []).append(fact)

        output_rows: list[EvaluationFact] = []
        for fund_id in catalog_fund_id_list:
            group = fund_groups.get(fund_id, [])
            group.sort(key=lambda f: _sort_key(f, order))
            output_rows.extend(group[:limit])
    else:
        rankable.sort(key=lambda f: _sort_key(f, order))
        output_rows = rankable[:limit]

    population_basis = _population_basis(scoped_facts, metric=metric)
    if population_basis in {"annual_summary", "metric_available"}:
        population_count = len(matched_fund_ids)
    else:
        population_count = len(population)

    return EvaluationAggregate(
        year=year,
        metric=metric,
        order=order,
        limit=limit,
        per_fund=per_fund,
        ministry=ministry,
        population_count=population_count,
        matched_count=len(matched_fund_ids),
        missing_funds=missing_funds,
        rows=output_rows,
        catalog_count=len(population),
        population_basis=population_basis,
    )


def _analytics_value(fact: EvaluationFact) -> tuple[str, float] | None:
    if fact.score is not None:
        return "score", fact.score
    if fact.adjustment is not None:
        return "adjustment", fact.adjustment
    if fact.metric_value is not None:
        return "metric_value", fact.metric_value
    if fact.grade_rank is not None:
        return "grade_rank", float(fact.grade_rank)
    return None


def _facts_by_fund(facts: list[EvaluationFact]) -> dict[str, EvaluationFact]:
    result: dict[str, EvaluationFact] = {}
    for fact in facts:
        if fact.fund_id in result:
            raise ValueError(
                f"analytics metric returned multiple facts for fund_id={fact.fund_id!r}"
            )
        result[fact.fund_id] = fact
    return result


def _scope_to_evaluated_population(
    metric_aggregate: EvaluationAggregate,
    evaluated_aggregate: EvaluationAggregate,
) -> EvaluationAggregate:
    if evaluated_aggregate.population_basis != "annual_summary":
        raise ValueError(
            "evaluated population requires annual overall_grade summary facts"
        )

    evaluated_by_fund = _facts_by_fund(evaluated_aggregate.rows)
    metric_by_fund = _facts_by_fund(metric_aggregate.rows)
    evaluated_fund_ids = set(evaluated_by_fund)
    scoped_rows = [
        fact
        for fact in metric_aggregate.rows
        if fact.fund_id in evaluated_fund_ids
    ]
    missing_funds = [
        fact.fund_name
        for fact in evaluated_aggregate.rows
        if fact.fund_id not in metric_by_fund
    ]
    return metric_aggregate.model_copy(
        update={
            "population_count": len(evaluated_fund_ids),
            "matched_count": len(evaluated_fund_ids & set(metric_by_fund)),
            "missing_funds": missing_funds,
            "rows": scoped_rows,
            "population_basis": "annual_summary",
        }
    )


def fund_analytics(
    operation: AnalyticsOperation,
    years: list[int],
    metric: str = "overall_grade",
    *,
    population: AnalyticsPopulation = "metric",
    grade: str | None = None,
    order: Literal["asc", "desc"] = "desc",
    limit: int = 3,
    ministry: str | None = None,
) -> FundAnalyticsResult:
    """Execute predefined ranking and multi-year comparisons in Python.

    Azure AI Search supplies complete normalized fact sets.  This function owns
    all arithmetic, sorting, set intersection, and grade-direction logic; callers
    only select the operation and parameters.
    """
    allowed: set[str] = {
        "rank", "distribution", "compare_years", "grade_changes", "maintained_grade"
    }
    if operation not in allowed:
        raise ValueError(f"unsupported analytics operation: {operation!r}")
    if not years or any(not (2000 <= year <= 2099) for year in years):
        raise ValueError("years must contain valid fiscal years in 2000..2099")
    if not (1 <= limit <= 100):
        raise ValueError(f"limit must be 1..100, got {limit}")
    if order not in ("asc", "desc"):
        raise ValueError(f"order must be 'asc' or 'desc', got {order!r}")
    if population not in ("metric", "evaluated"):
        raise ValueError(
            f"population must be 'metric' or 'evaluated', got {population!r}"
        )

    unique_years = sorted(set(years))
    comparison_ops = {"compare_years", "grade_changes", "maintained_grade"}
    if operation in comparison_ops and len(unique_years) < 2:
        raise ValueError(f"{operation} requires at least two distinct years")
    if operation in {"rank", "distribution"} and len(unique_years) != 1:
        raise ValueError(f"{operation} requires exactly one year")
    if operation == "grade_changes" and len(unique_years) != 2:
        raise ValueError("grade_changes requires exactly two distinct years")
    if operation == "maintained_grade" and grade not in GRADE_RANKS:
        raise ValueError("maintained_grade requires a recognized grade")

    aggregates: list[EvaluationAggregate] = []
    for year in unique_years:
        aggregate = aggregate_evaluations(
            year=year,
            metric=metric,
            order=order,
            limit=100,
            ministry=ministry,
        )
        if population == "evaluated":
            if metric == "overall_grade":
                evaluated_aggregate = aggregate
            else:
                evaluated_aggregate = aggregate_evaluations(
                    year=year,
                    metric="overall_grade",
                    order=order,
                    limit=100,
                    ministry=ministry,
                )
            aggregate = _scope_to_evaluated_population(
                aggregate,
                evaluated_aggregate,
            )
        aggregates.append(aggregate)
    unknown_grades = sorted(
        {
            fact.grade
            for aggregate in aggregates
            for fact in aggregate.rows
            if fact.grade is not None and fact.grade not in GRADE_RANKS
        }
    )
    if unknown_grades:
        raise ValueError(f"unrecognized grade values: {unknown_grades}")

    summaries = [
        AnalyticsYearSummary(
            year=aggregate.year,
            catalog_count=aggregate.catalog_count or aggregate.population_count,
            population_count=aggregate.population_count,
            matched_count=aggregate.matched_count,
            population_basis=aggregate.population_basis,
            missing_funds=aggregate.missing_funds,
            grade_distribution=dict(
                sorted(
                    Counter(
                        fact.grade for fact in aggregate.rows if fact.grade is not None
                    ).items(),
                    key=lambda item: -GRADE_RANKS[item[0]],
                )
            ),
        )
        for aggregate in aggregates
    ]

    if operation in {"rank", "distribution"}:
        selected = aggregates[0].rows
        if operation == "rank":
            selected = selected[:limit]
        rows = [
            AnalyticsRow(
                fund_id=fact.fund_id,
                fund_name=fact.fund_name,
                facts=[fact],
            )
            for fact in selected
        ]
        return FundAnalyticsResult(
            operation=operation,
            metric=metric,
            years=unique_years,
            population=population,
            grade=grade,
            summaries=summaries,
            rows=rows,
        )

    facts_by_year = {
        aggregate.year: _facts_by_fund(aggregate.rows) for aggregate in aggregates
    }
    common_fund_ids = set.intersection(
        *(set(facts_by_year[year]) for year in unique_years)
    )
    first_year = unique_years[0]
    last_year = unique_years[-1]
    comparison_rows: list[AnalyticsRow] = []
    unchanged_count = 0

    for fund_id in sorted(common_fund_ids):
        facts = [facts_by_year[year][fund_id] for year in unique_years]
        analytics_values = [_analytics_value(fact) for fact in facts]
        value_kinds = {
            value_kind
            for value in analytics_values
            if value is not None
            for value_kind in [value[0]]
        }
        if len(value_kinds) > 1:
            raise ValueError(
                "incompatible analytics value kinds for "
                f"fund_id={fund_id!r}: {sorted(value_kinds)}"
            )
        first_value = analytics_values[0]
        last_value = analytics_values[-1]
        if first_value is None or last_value is None:
            direction: Literal["up", "down", "same"] | None = None
        elif last_value[1] > first_value[1]:
            direction = "up"
        elif last_value[1] < first_value[1]:
            direction = "down"
        else:
            direction = "same"
            unchanged_count += 1

        if operation == "grade_changes" and direction in (None, "same"):
            continue
        if operation == "maintained_grade" and not all(
            fact.grade == grade for fact in facts
        ):
            continue

        comparison_rows.append(
            AnalyticsRow(
                fund_id=fund_id,
                fund_name=facts[-1].fund_name,
                facts=facts,
                direction=direction,
            )
        )

    comparison_rows.sort(key=lambda row: row.fund_name)
    return FundAnalyticsResult(
        operation=operation,
        metric=metric,
        years=unique_years,
        population=population,
        grade=grade,
        summaries=summaries,
        common_count=len(common_fund_ids),
        unchanged_count=unchanged_count,
        rows=comparison_rows,
    )
