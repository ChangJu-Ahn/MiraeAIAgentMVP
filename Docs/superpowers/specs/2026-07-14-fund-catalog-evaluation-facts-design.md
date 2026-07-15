# Fund Catalog and Evaluation Facts Design

## 1. Goal

Make fund-scoped and global comparison questions complete and deterministic across the
2021, 2022, and 2025 asset-management evaluation reports.

The system must not infer the population from semantic-search results. It must first know
the complete set of funds for the selected report year, then retrieve or aggregate facts
within that population.

Examples covered by this design:

- Which three funds have the highest quantitative performance score in 2025?
- Show the three highest-rated evaluation items for each fund.
- Compare a fund across 2021, 2022, and 2025.
- List every fund under a ministry and summarize each result.

## 2. Current Gap

The current `fund_name` field is a best-effort regular-expression extraction from each
chunk's `section_path`. It is useful as a search hint but is not an entity catalog.

Observed production-index failures include:

- The 2025 table of contents contains 25 fund sections, while the current facet contains
  only 21 valid fund names.
- `대상기금` is incorrectly extracted as a fund.
- Parenthesized names can be truncated, for example
  `국민체육진흥기금(국민체육진흥계정`.
- Some fund content exists but has `fund_name=null`.
- Ministry ownership is not retained on fund chunks.
- The agent cannot list the full population or perform deterministic numeric aggregation.

## 3. Chosen Architecture

Keep Azure AI Search as the only serving datastore and add two structured indexes:

1. `fund-catalog-index`: the authoritative year-specific fund population and aliases.
2. `evaluation-facts-index`: normalized scores and grades with source provenance.

The existing `narrative-index` and `table-index` remain the evidence stores. Their
documents gain authoritative catalog metadata: `fund_id`, canonical `fund_name`, and
`ministry`.

This avoids both weak prompt-only fan-out and a new database dependency.

## 4. Fund Catalog

### 4.1 Source of Truth

For each report, parse the numbered entries under the table-of-contents section matching
`기금별 자산운용평가 결과`. This section is the authoritative population for questions
about every evaluated fund.

The parser must support entries represented as either Document Intelligence paragraphs or
HTML/Markdown table cells. A ministry heading applies to subsequent fund entries until the
next ministry heading.

The separate `평가 대상기금` table remains searchable evidence but must not create catalog
entities because it can describe a broader or differently scoped population.

### 4.2 Catalog Record

Each record contains:

| Field | Type | Purpose |
|---|---|---|
| `id` | String key | Search document key |
| `fund_id` | String | Stable ID derived from canonical name |
| `year` | Int32 | Fiscal year |
| `doc_id` | String | Source report |
| `toc_order` | Int32 | Order in the report |
| `canonical_name` | String | Correct normalized full name |
| `aliases` | Collection(String) | OCR variants and common short names |
| `ministry` | String | Owning ministry or authority |
| `fund_scale` | String nullable | Report scale category when available |
| `start_page_printed` | Int32 | First printed page of the fund section |
| `end_page_printed` | Int32 | Last printed page before the next fund |
| `start_page_physical` | Int32 nullable | Resolved PDF page |
| `end_page_physical` | Int32 nullable | Resolved PDF page |
| `source_page_physical` | Int32 | TOC evidence page |

`fund_id` is stable across years. Catalog document `id` combines `year` and `fund_id`.

### 4.3 Normalization

- Strip numbering and whitespace artifacts without dropping balanced parentheses.
- Normalize internal whitespace and known ministry spacing variants.
- Apply a small reviewed alias map for known OCR errors and common names, including
  `농어가목돈마련저축장력기금` to `농어가목돈마련저축장려기금` and
  `사학연금기금` to `사립학교교직원연금기금`.
- Preserve account-qualified funds as distinct canonical entities.
- Never silently merge two catalog entries with different TOC order values.

### 4.4 Completeness Guard

Catalog extraction fails before upload when any of these conditions holds:

- TOC ordinals are not a contiguous sequence starting at 1.
- A record lacks a ministry, canonical name, or start page.
- Canonical names or year-specific IDs are duplicated.
- Page ranges overlap or are not increasing.
- A catalog fund receives no evidence chunks after page-range annotation.

The ingest report prints expected, extracted, and annotated fund counts per year.

## 5. Chunk Annotation

Catalog page ranges, not heading regexes, own fund assignment.

For every narrative, table, and figure chunk in a report:

1. Resolve its printed page, with physical page as fallback.
2. Find the single catalog range containing that page.
3. Set `fund_id`, canonical `fund_name`, and `ministry` from that catalog record.
4. Leave these fields null for overview and aggregate sections before the first fund range.

The existing heading-derived `fund_name` logic remains only as a diagnostic comparison
during migration and is not an authoritative assignment source.

## 6. Evaluation Facts

### 6.1 Scope

Extract deterministic facts from the report's aggregate result tables and each fund's
`평가결과 총괄표` or equivalent table. The first implementation covers:

- quantitative performance scores and their maximum scores;
- overall or final evaluation grades;
- non-quantitative category and sub-item grades;
- report-provided grouped grade tables.

Facts that cannot be parsed unambiguously remain in evidence chunks and are not guessed.

### 6.2 Fact Record

| Field | Type | Purpose |
|---|---|---|
| `id` | String key | Deterministic fact key |
| `fund_id` | String | Catalog entity |
| `fund_name` | String | Display name |
| `year` | Int32 | Fiscal year |
| `ministry` | String | Grouping field |
| `fact_type` | String | `score` or `grade` |
| `metric_code` | String | Stable normalized metric identifier |
| `metric_name` | String | Report label |
| `score` | Double nullable | Numeric score |
| `max_score` | Double nullable | Maximum score |
| `grade` | String nullable | Normalized report grade |
| `grade_rank` | Int32 nullable | Deterministic ordering, best grade first |
| `source_chunk_id` | String | Evidence chunk |
| `source_page_physical` | Int32 | Evidence page |
| `source_section_path` | String | Evidence section |
| `source_text` | String | Exact source row or compact evidence |

Fact extraction validates numeric bounds when `max_score` is available and rejects facts
whose fund cannot be resolved to the catalog.

## 7. Agent Tools and Routing

Add these deterministic tools:

- `list_funds(year, ministry=None)`: complete ordered population.
- `resolve_fund(name, year=None)`: canonical ID/name resolution using names and aliases.
- `get_fund_evaluations(fund_name, year, metric=None)`: structured facts for one fund.
- `aggregate_evaluations(year, metric, order="desc", limit=3, ministry=None)`: numeric
  or grade ranking with explicit coverage information.

Every aggregate result returns `population_count`, `matched_count`, and `missing_funds`.
The agent must disclose incomplete coverage rather than present a partial result as global.

Routing rules:

- Individual qualitative questions continue through hybrid RAG after entity resolution.
- Questions containing global intent such as `전체`, `각 기금`, `상위`, `하위`, `순위`,
  or `가장` must start with catalog or aggregation tools.
- Numeric sorting and grade ranking must not be performed by repeated top-k semantic search.
- Retrieved facts retain source IDs so final answers can cite the original report evidence.

## 8. Index Migration

1. Add `fund_id` and `ministry` fields to the two evidence-index schemas.
2. Create the catalog and fact indexes.
3. Parse all cached 2021, 2022, and 2025 reports.
4. Validate catalogs before any evidence upload.
5. Annotate, embed, and upload evidence chunks.
6. Extract, validate, and upload evaluation facts.
7. Verify index counts and representative source links.

Existing indexes are updated in place where Azure Search permits additive fields. The
pipeline must not delete a healthy index until replacement data has passed local catalog
and fact validation.

## 9. Tests

### Unit Tests

- Mixed paragraph/table TOC extraction and ministry carry-forward.
- Balanced parenthesized names and reviewed alias normalization.
- Contiguous ordinal and non-overlapping range validation.
- Page-range chunk annotation, including overview chunks remaining unassigned.
- Score and grade row parsing with source provenance.
- Deterministic sorting, grade ranking, and coverage reporting.
- Agent tool formatting and global-query routing instructions.

### Integration Tests

- 2025 catalog extracts exactly ordinals 1 through 25.
- Every 2025 catalog fund has evidence chunks and no evidence chunk uses `대상기금`.
- Parenthesized fund filters resolve and return results.
- Known workbook aggregate questions return the expected complete population and ranking.

### Regression and Evaluation

- Run the full network-free test suite.
- Run the live smoke test.
- Re-run all 16 Excel questions using the same five evaluators.
- Compare per-question scores, search/tool call counts, coverage, and latency against the
  prior artifact.

## 10. Acceptance Criteria

- Catalog extraction succeeds for 2021, 2022, and 2025 with contiguous ordinals.
- For 2025, exactly 25 canonical funds are cataloged and annotated.
- `대상기금` never appears as a canonical entity.
- Every fund-scoped evidence chunk uses a catalog `fund_id`, canonical name, and ministry.
- Global ranking answers report complete population coverage or explicitly identify gaps.
- Known top-three and per-fund grade questions use structured aggregation rather than
  repeated semantic top-k discovery.
- All tests pass and the new 16-row evaluation artifact is valid and comparable to the
  previous run.