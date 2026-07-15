# Fund Catalog and Evaluation Facts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a complete year-specific fund catalog and normalized evaluation-fact path so global and per-fund rankings do not depend on semantic top-k discovery, then re-run the 16-row Excel evaluation.

**Architecture:** Parse the authoritative fund population from each report's table of contents, use its page ranges to annotate existing evidence chunks, and extract normalized score/grade facts from per-fund result tables. Serve catalog and facts through two Azure AI Search indexes and deterministic agent tools while retaining the existing narrative/table indexes for cited evidence.

**Tech Stack:** Python 3.12, Pydantic, Azure AI Search, Azure Identity, Microsoft Agent Framework, pytest, uv, cached Azure Document Intelligence output.

## Global Constraints

- Cover report years 2021, 2022, and 2025; verified TOC populations are 33, 31, and 25 funds respectively.
- `fund-catalog-index` is authoritative for population and entity identity.
- `evaluation-facts-index` stores normalized scores/grades and exact source provenance.
- Existing narrative/table search remains the qualitative evidence path.
- Global ranking must report `population_count`, `matched_count`, and `missing_funds`.
- Ambiguous facts are omitted rather than guessed.
- No deployment may upload a partial catalog after completeness validation fails.
- Do not commit changes unless the user explicitly requests a commit.

---

### Task 1: Extract and Validate the Authoritative Fund Catalog

**Files:**
- Create: `ingest/catalog.py`
- Create: `tests/ingest/test_catalog.py`

**Interfaces:**
- Produces: `FundCatalogEntry`, `CatalogValidationError`, `extract_fund_catalog(doc, *, year, doc_id)`, `fund_id_for(name)`, `normalize_fund_name(name)`.
- Consumes: `ParsedDoc`, `ParsedParagraph` from `ingest.models`.

- [ ] **Step 1: Write failing pure unit tests for mixed TOC shapes**

Create fixtures containing inline `1. 기금 49` entries, split `18. 기금` + `393` entries, ministry carry-forward, parenthesized account names, and an end marker for the real report body.

```python
def test_extract_catalog_handles_inline_and_split_toc_entries():
    catalog = extract_fund_catalog(_mixed_toc_doc(), year=2025, doc_id="report-2025")
    assert [item.toc_order for item in catalog] == [1, 2, 3]
    assert catalog[1].canonical_name == "국민체육진흥기금(국민체육진흥계정)"
    assert catalog[2].ministry == "금융위원회"
    assert catalog[2].start_page_printed == 393
```

- [ ] **Step 2: Write failing validation and normalization tests**

```python
def test_catalog_rejects_non_contiguous_ordinals():
    with pytest.raises(CatalogValidationError, match="contiguous"):
        extract_fund_catalog(_toc_with_orders(1, 3), year=2025, doc_id="report-2025")

def test_normalize_fund_name_repairs_reviewed_ocr_alias():
    assert normalize_fund_name("농어가목돈마련저축장력기금") == "농어가목돈마련저축장려기금"
```

- [ ] **Step 3: Run focused tests and confirm RED**

Run: `$HOME/.local/bin/uv run pytest tests/ingest/test_catalog.py -q`

Expected: import failure because `ingest.catalog` does not exist.

- [ ] **Step 4: Implement catalog models and parser**

Use Pydantic models. Parse sorted paragraphs between `기금별 자산운용평가 결과` and the subsequent `Ⅰ.*기금운용평가.*개요` marker. Track `【...】` ministry headings and a pending entry whose page arrives in the next numeric paragraph.

```python
class FundCatalogEntry(BaseModel):
    id: str
    fund_id: str
    year: int
    doc_id: str
    toc_order: int
    canonical_name: str
    aliases: list[str] = Field(default_factory=list)
    ministry: str
    fund_scale: str | None = None
    start_page_printed: int
    end_page_printed: int
    start_page_physical: int | None = None
    end_page_physical: int | None = None
    source_page_physical: int

def extract_fund_catalog(
    doc: ParsedDoc, *, year: int, doc_id: str
) -> list[FundCatalogEntry]: ...
```

Resolve printed-to-physical pages from `pageNumber` paragraphs. Use the next catalog start minus one as each end page and the document's maximum printed page for the final record.

- [ ] **Step 5: Run focused tests and confirm GREEN**

Run: `$HOME/.local/bin/uv run pytest tests/ingest/test_catalog.py -q`

Expected: all catalog unit tests pass.

- [ ] **Step 6: Add cache-backed completeness test**

The test skips only when `.ingest_cache` is absent. Assert exact contiguous populations:

```python
@pytest.mark.parametrize(("doc_id", "year", "count"), [
    ("report-2021", 2021, 33),
    ("report-2022", 2022, 31),
    ("report-2025", 2025, 25),
])
def test_cached_report_catalog_is_complete(doc_id, year, count): ...
```

Run: `$HOME/.local/bin/uv run pytest tests/ingest/test_catalog.py -q`

Expected: 33/31/25 records with no ordinal gaps, duplicate IDs, or `대상기금` entity.

---

### Task 2: Assign Catalog Identity to Evidence Chunks

**Files:**
- Modify: `ingest/models.py`
- Modify: `ingest/indexer.py`
- Modify: `ingest/chunker.py`
- Modify: `ingest/figures.py`
- Modify: `tests/ingest/test_models.py`
- Modify: `tests/ingest/test_indexer.py`
- Modify: `tests/ingest/test_chunker.py`
- Modify: `tests/ingest/test_catalog.py`

**Interfaces:**
- Consumes: `list[FundCatalogEntry]` from Task 1 and `list[Chunk]`.
- Produces: `CatalogCoverage` and `annotate_chunks(chunks, catalog)` in `ingest.catalog`.

- [ ] **Step 1: Add failing tests for model/index fields**

Assert that `Chunk` supports optional `fund_id` and `ministry`, `_chunk_to_doc` writes non-null values, and both evidence indexes expose filterable/facetable fields.

```python
assert {"fund_id", "ministry"} <= {field.name for field in build_index("x").fields}
```

- [ ] **Step 2: Add failing page-range annotation tests**

```python
def test_annotate_chunks_uses_catalog_page_ranges():
    coverage = annotate_chunks(_chunks_on_pages(10, 11, 20), _two_fund_catalog())
    assert [chunk.fund_id for chunk in coverage.chunks] == ["fund-a", "fund-a", "fund-b"]
    assert coverage.missing_fund_ids == []

def test_overview_chunk_remains_unassigned(): ...
def test_annotation_rejects_catalog_fund_without_chunks(): ...
```

- [ ] **Step 3: Run focused tests and confirm RED**

Run: `$HOME/.local/bin/uv run pytest tests/ingest/test_catalog.py tests/ingest/test_models.py tests/ingest/test_indexer.py -q`

- [ ] **Step 4: Implement authoritative annotation**

```python
class CatalogCoverage(BaseModel):
    chunks: list[Chunk]
    population_count: int
    annotated_fund_count: int
    missing_fund_ids: list[str]

def annotate_chunks(
    chunks: list[Chunk], catalog: list[FundCatalogEntry]
) -> CatalogCoverage: ...
```

Use physical page ranges first and printed ranges as fallback. Override heading-derived
`fund_name` only inside a catalog range; leave overview chunks unassigned. Add `fund_id`
and `ministry` to evidence index schemas and serialization.

- [ ] **Step 5: Run focused tests and confirm GREEN**

Run: `$HOME/.local/bin/uv run pytest tests/ingest/test_catalog.py tests/ingest/test_models.py tests/ingest/test_indexer.py tests/ingest/test_chunker.py -q`

Expected: all pass; existing heading-derived tests remain valid as fallback diagnostics.

---

### Task 3: Extract Normalized Evaluation Facts

**Files:**
- Create: `ingest/facts.py`
- Create: `tests/ingest/test_facts.py`

**Interfaces:**
- Consumes: catalog-annotated table `Chunk` values.
- Produces: `EvaluationFact`, `extract_evaluation_facts(chunks)` and `metric_code_for(name)`.

- [ ] **Step 1: Write failing tests for five- and six-column result tables**

Use exact compact fixtures shaped like the verified 2021/2022 five-column and 2025 six-column tables.

```python
def test_extracts_asset_management_performance_score():
    facts = extract_evaluation_facts([_result_table_chunk(score="46.47", grade="탁월")])
    fact = next(f for f in facts if f.metric_code == "asset_management_performance")
    assert (fact.score, fact.max_score, fact.grade) == (46.47, 50.0, "탁월")
    assert fact.source_chunk_id == "report-2025-1"
```

- [ ] **Step 2: Write failing tests for grade rows, N/A, formulas, and duplicate facts**

Assert `48W` is not parsed as a numeric maximum, `N/A` creates no numeric score, recognized grades receive deterministic rank, and duplicate fact IDs are rejected.

- [ ] **Step 3: Run focused tests and confirm RED**

Run: `$HOME/.local/bin/uv run pytest tests/ingest/test_facts.py -q`

- [ ] **Step 4: Implement a parser for the strict DI-generated Markdown table format**

```python
class EvaluationFact(BaseModel):
    id: str
    fund_id: str
    fund_name: str
    year: int
    ministry: str
    fact_type: Literal["score", "grade"]
    metric_code: str
    metric_name: str
    score: float | None = None
    max_score: float | None = None
    grade: str | None = None
    grade_rank: int | None = None
    source_chunk_id: str
    source_page_physical: int
    source_section_path: str
    source_text: str

def extract_evaluation_facts(chunks: list[Chunk]) -> list[EvaluationFact]: ...
```

Track semantic column positions whenever a row starts with `평가지표 (비계량)` or
`평가지표 (계량)`. Parse only tables assigned to a catalog fund and containing recognized
result headers. Map known top-level metrics to stable codes; use a deterministic hash code
for unrecognized item labels.

- [ ] **Step 5: Run focused and cache-backed fact tests**

Run: `$HOME/.local/bin/uv run pytest tests/ingest/test_facts.py -q`

Expected: all pure tests pass and each cached report yields one
`asset_management_performance` fact per fund where the report provides a parseable score;
any missing funds are listed explicitly.

---

### Task 4: Create Structured Search Indexes and Replacement Uploads

**Files:**
- Create: `ingest/structured_indexer.py`
- Create: `tests/ingest/test_structured_indexer.py`
- Modify: `config/settings.py`
- Modify: `tests/test_settings.py`

**Interfaces:**
- Consumes: `FundCatalogEntry`, `EvaluationFact`.
- Produces: `build_catalog_index`, `build_facts_index`, `ensure_structured_indexes`, `replace_catalog`, `replace_facts`.

- [ ] **Step 1: Write failing schema tests**

Assert the catalog key and filter/sort fields, alias collection, numeric fact fields, grade rank, and source provenance.

```python
def test_fact_score_is_filterable_and_sortable():
    score = next(field for field in build_facts_index("x").fields if field.name == "score")
    assert score.filterable and score.sortable
```

- [ ] **Step 2: Add settings defaults and failing serialization tests**

Use `fund-catalog-index` and `evaluation-facts-index` defaults.

- [ ] **Step 3: Run focused tests and confirm RED**

Run: `$HOME/.local/bin/uv run pytest tests/ingest/test_structured_indexer.py tests/test_settings.py -q`

- [ ] **Step 4: Implement schemas and replace-by-doc upload semantics**

Delete existing catalog/fact document keys for the same `doc_id`, then upload the validated replacement set. Never delete old documents before the new set has passed local validation.

- [ ] **Step 5: Run focused tests and confirm GREEN**

Run: `$HOME/.local/bin/uv run pytest tests/ingest/test_structured_indexer.py tests/test_settings.py -q`

---

### Task 5: Add Deterministic Structured Query Operations

**Files:**
- Create: `search/structured.py`
- Create: `tests/search/test_structured.py`

**Interfaces:**
- Produces: `CatalogFund`, `EvaluationAggregate`, `list_funds`, `resolve_fund`, `get_fund_evaluations`, `aggregate_evaluations`.
- Consumes: index names from settings and Azure Search records from Task 4.

- [ ] **Step 1: Write failing tests using fake SearchClient results**

Cover ordered population, exact canonical/alias resolution, score ordering, grade ordering,
per-fund top three, and missing coverage.

```python
def test_aggregate_reports_population_coverage():
    result = aggregate_evaluations(year=2025, metric="asset_management_performance", limit=3)
    assert result.population_count == 25
    assert result.matched_count == 25
    assert result.missing_funds == []
```

- [ ] **Step 2: Run focused tests and confirm RED**

Run: `$HOME/.local/bin/uv run pytest tests/search/test_structured.py -q`

- [ ] **Step 3: Implement query functions**

```python
def list_funds(year: int, ministry: str | None = None) -> list[FundCatalogEntry]: ...
def resolve_fund(name: str, year: int | None = None) -> FundCatalogEntry | None: ...
def get_fund_evaluations(
    fund_name: str, year: int, metric: str | None = None
) -> list[EvaluationFact]: ...
def aggregate_evaluations(
    year: int,
    metric: str | None = None,
    *,
    order: Literal["asc", "desc"] = "desc",
    limit: int = 3,
    ministry: str | None = None,
    per_fund: bool = False,
) -> EvaluationAggregate: ...
```

Fetch up to the bounded complete fact set, group and sort deterministically in Python for
`per_fund=True`, and compute missing funds against `list_funds`.

- [ ] **Step 4: Run focused tests and confirm GREEN**

Run: `$HOME/.local/bin/uv run pytest tests/search/test_structured.py -q`

---

### Task 6: Expose Catalog and Aggregation Tools to the Agent

**Files:**
- Modify: `agent/tools.py`
- Modify: `agent/orchestrator.py`
- Modify: `tests/agent/test_tools.py`
- Modify: `tests/agent/test_orchestrator.py`

**Interfaces:**
- Consumes: structured search operations from Task 5.
- Produces: agent-callable `list_funds`, `resolve_fund`, `get_fund_evaluations`, and `aggregate_evaluations` closures with trace/source recording.

- [ ] **Step 1: Add failing tool-format and citation tests**

Assert aggregate output includes coverage, rows include `[출처 N]`, and fact sources are appended to `TraceRecorder.sources` with `chunk_type="fact"`.

- [ ] **Step 2: Add failing prompt-routing tests**

Assert the system prompt states that `전체`, `각 기금`, `상위`, `하위`, `순위`, and
`가장` start with structured tools and forbids repeated semantic top-k numeric sorting.

- [ ] **Step 3: Run focused tests and confirm RED**

Run: `$HOME/.local/bin/uv run pytest tests/agent/test_tools.py tests/agent/test_orchestrator.py -q`

- [ ] **Step 4: Implement agent wrappers and routing instructions**

Bound `limit` to 1..100, escape filters through the structured search layer, and disclose
missing coverage in Korean tool output. Add all four structured closures to
`make_search_tools` without changing existing function signatures.

- [ ] **Step 5: Run focused tests and confirm GREEN**

Run: `$HOME/.local/bin/uv run pytest tests/agent/test_tools.py tests/agent/test_orchestrator.py -q`

---

### Task 7: Integrate Validation and Structured Upload into Ingest

**Files:**
- Modify: `ingest/run.py`
- Modify: `tests/ingest/test_run.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: Tasks 1-4.
- Produces: `run(..., validate_only=False)` and CLI `--validate-only`.

- [ ] **Step 1: Write failing orchestration tests**

Mock Azure operations and assert report ingest order:

```text
analyze -> chunk -> catalog -> annotate -> facts -> validate
        -> embed -> evidence upload -> catalog replace -> fact replace
```

Guideline documents must skip catalog/fact work. `validate_only=True` must perform all pure
extraction and completeness checks without embeddings or Azure Search writes.

- [ ] **Step 2: Run focused tests and confirm RED**

Run: `$HOME/.local/bin/uv run pytest tests/ingest/test_run.py -q`

- [ ] **Step 3: Implement report-only structured ingest and CLI output**

Print one line per report containing `catalog`, `annotated`, `facts`, and missing fact
coverage counts. Add README commands:

```bash
uv run python -m ingest.run --all --validate-only
uv run python -m ingest.run --all
```

- [ ] **Step 4: Run focused and ingest regression tests**

Run: `$HOME/.local/bin/uv run pytest tests/ingest tests/search tests/agent/test_tools.py tests/agent/test_orchestrator.py -q`

Expected: all pass without network.

---

### Task 8: Migrate Azure Indexes, Verify Coverage, and Re-evaluate

**Files:**
- Update generated artifacts: `reports/eval-Chatbot_질문지리스트_20260713.md`
- Update generated artifacts: `reports/eval-Chatbot_질문지리스트_20260713.json`
- Create: `reports/eval-Chatbot_질문지리스트_20260713-before-structured.json`

**Interfaces:**
- Consumes: completed Tasks 1-7 and the existing real workbook.
- Produces: populated structured indexes and comparable 16-row evaluation artifacts.

- [ ] **Step 1: Preserve the prior JSON artifact**

Use a normal file copy command; do not modify its content.

- [ ] **Step 2: Run local validation-only ingest**

Run: `$HOME/.local/bin/uv run python -m ingest.run --all --validate-only`

Expected: 2021=33, 2022=31, 2025=25 catalog funds; no missing evidence fund.

- [ ] **Step 3: Run the real structured re-ingest**

Run: `$HOME/.local/bin/uv run python -m ingest.run --all`

Expected: all four indexes updated; no catalog completeness failure.

- [ ] **Step 4: Query live coverage and known rankings**

Verify:

- 2025 catalog has exactly 25 records.
- Every 2025 catalog fund has evidence chunks.
- `대상기금` is absent from canonical names.
- Parenthesized canonical filters return evidence.
- 2025 `asset_management_performance` ranking is backed by structured facts and reports its matched/population counts.

- [ ] **Step 5: Run complete local and live verification**

Run:

```bash
$HOME/.local/bin/uv run pytest -q
$HOME/.local/bin/uv run pytest tests/eval/test_runner_smoke.py -q -s
$HOME/.local/bin/uv lock --check
/opt/homebrew/bin/git diff --check
```

Expected: all tests pass, lock is current, no whitespace errors.

- [ ] **Step 6: Re-run the same 16-row workbook evaluation**

Run: `$HOME/.local/bin/uv run python -m eval.run_eval "Chatbot_질문지리스트_20260713"`

Validate exactly five finite scores in range 1..5, non-empty reasons/context/trace/sources,
and 16 rows.

- [ ] **Step 7: Compare before and after**

Report score deltas, structured versus semantic tool-call counts, total latency, global
question coverage, and any remaining missing facts. Do not claim a global answer is complete
when `matched_count < population_count`.