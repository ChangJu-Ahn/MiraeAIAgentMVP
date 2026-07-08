# 멀티-연도/유형 코퍼스 메타데이터 필터 인덱싱 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 확장된 코퍼스(보고서 2021/2022/2025 + 지침 2021/2022)를 2개 인덱스 + 메타데이터(year/doc_type/fund_name/fund_scale) 필터로 인제스트·검색한다.

**Architecture:** 2개 인덱스(narrative/table) 유지 + 문서·청크 메타데이터 필드 추가. 문서 레지스트리(`corpus.py`)로 5개 문서를 메타와 함께 재인제스트. 검색 도구가 OData 필터를 조립하고, 추론 모델이 질문에서 필터를 채운다. 오늘 날짜를 프롬프트에 주입해 연도 미지정 시 최신 연도 기본 조회.

**Tech Stack:** Python 3.12, pydantic, Azure AI Search SDK, agent_framework(Foundry), pytest, uv.

## Global Constraints
- 필수 Azure 스택 사용(DI/AI Search/Foundry), 키리스(`DefaultAzureCredential`).
- MVP 간결성: 새 추상화 최소화, 기존 패턴 따름. `chunk_document`/`build_figure_chunks`는 메타 인자를 **선택적**으로 받아 기존 호출 호환.
- 모든 테스트 실행 가능(실제 Azure 호출 허용). 테스트 러너: `uv run pytest`.
- 코드 스타일: 기존 파일 컨벤션 유지, 불필요한 주석 금지.
- 스키마 필드 추가라 최종 마이그레이션은 인덱스 재생성(`reset_indexes`) + 전체 재인제스트 1회.

---

### Task 1: Chunk 모델에 메타데이터 필드 추가

**Files:**
- Modify: `ingest/models.py` (class `Chunk`)
- Test: `tests/ingest/test_models.py`

**Interfaces:**
- Produces: `Chunk`에 `year: int|None`, `doc_type: str|None`, `fund_name: str|None`, `fund_scale: str|None` (모두 기본 None).

- [ ] **Step 1: 실패 테스트 작성** — `tests/ingest/test_models.py`의 `test_chunk_defaults`를 아래로 교체/추가

```python
def test_chunk_metadata_defaults():
    c = Chunk(
        id="d1-0", doc_id="d1", content="body", chunk_type="narrative",
        section_path="A", page_printed=24, page_physical=40,
    )
    assert c.year is None
    assert c.doc_type is None
    assert c.fund_name is None
    assert c.fund_scale is None


def test_chunk_metadata_set():
    c = Chunk(
        id="d1-0", doc_id="d1", content="body", chunk_type="table",
        section_path="A", page_physical=40,
        year=2022, doc_type="report", fund_name="국민연금기금", fund_scale="대규모",
    )
    assert (c.year, c.doc_type, c.fund_name, c.fund_scale) == (2022, "report", "국민연금기금", "대규모")
```

- [ ] **Step 2: 실패 확인** — Run: `uv run pytest tests/ingest/test_models.py -q` → Expected: FAIL (`year`/`doc_type` 등 미정의)

- [ ] **Step 3: 구현** — `ingest/models.py`의 `Chunk`를 아래로 수정

```python
class Chunk(BaseModel):
    id: str
    doc_id: str
    content: str
    chunk_type: str  # "narrative" | "table" | "figure"
    section_path: str
    page_printed: int | None = None
    page_physical: int
    year: int | None = None
    doc_type: str | None = None
    fund_name: str | None = None
    fund_scale: str | None = None
    content_vector: list[float] | None = None
```

- [ ] **Step 4: 통과 확인** — Run: `uv run pytest tests/ingest/test_models.py -q` → Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add ingest/models.py tests/ingest/test_models.py
git commit -m "feat(ingest): Chunk에 year/doc_type/fund_name/fund_scale 메타 필드 추가"
```

---

### Task 2: 메타데이터 파생 헬퍼 (fund_name / fund_scale)

**Files:**
- Modify: `ingest/chunker.py` (헬퍼 2개 추가)
- Test: `tests/ingest/test_chunker.py`

**Interfaces:**
- Produces:
  - `derive_fund_name(section_path: str) -> str | None`
  - `derive_fund_scale(section_path: str, default: str | None = None) -> str | None`

- [ ] **Step 1: 실패 테스트 작성** — `tests/ingest/test_chunker.py`에 추가

```python
def test_derive_fund_name():
    from ingest.chunker import derive_fund_name
    assert derive_fund_name("Ⅲ > 【보건복지부】 > 8. 국민연금기금 > 4.4 총평") == "국민연금기금"
    assert derive_fund_name("Ⅱ > 3. 방송통신발전기금") == "방송통신발전기금"
    assert derive_fund_name("Ⅰ 개요 > 1. 평가의 목적") is None
    assert derive_fund_name("") is None


def test_derive_fund_scale():
    from ingest.chunker import derive_fund_scale
    assert derive_fund_scale("Ⅱ > 3. 평가 결과(대규모 기금)") == "대규모"
    assert derive_fund_scale("Ⅱ > 2. 평가 결과(대형·중소형 기금)") == "대형중소형"
    assert derive_fund_scale("Ⅰ 개요", default="대형중소형") == "대형중소형"
    assert derive_fund_scale("Ⅰ 개요") is None
```

- [ ] **Step 2: 실패 확인** — Run: `uv run pytest tests/ingest/test_chunker.py -k derive -q` → Expected: FAIL (import error)

- [ ] **Step 3: 구현** — `ingest/chunker.py` 상단(`HEADING_ROLES` 아래)에 추가 (`import re`는 이미 존재)

```python
def derive_fund_name(section_path: str) -> str | None:
    """섹션 경로에서 '…기금/…계정' 형태의 기금명을 파생한다(가장 깊은 세그먼트 우선). 없으면 None."""
    for seg in reversed([s.strip() for s in section_path.split(">")]):
        m = re.search(r"([가-힣A-Za-z0-9·()]+(?:기금|계정))", seg)
        if m:
            return re.sub(r"^\d+\.\s*", "", m.group(1))
    return None


def derive_fund_scale(section_path: str, default: str | None = None) -> str | None:
    """섹션 경로 키워드로 기금 규모 유형을 파생한다. 없으면 default."""
    if "대규모" in section_path:
        return "대규모"
    if "대형" in section_path or "중소형" in section_path:
        return "대형중소형"
    return default
```

- [ ] **Step 4: 통과 확인** — Run: `uv run pytest tests/ingest/test_chunker.py -k derive -q` → Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add ingest/chunker.py tests/ingest/test_chunker.py
git commit -m "feat(ingest): fund_name/fund_scale 파생 헬퍼 추가"
```

---

### Task 3: chunk_document / build_figure_chunks에 메타 주입

**Files:**
- Modify: `ingest/chunker.py` (`chunk_document` 시그니처·Chunk 생성부)
- Modify: `ingest/figures.py` (`build_figure_chunks` 시그니처·Chunk 생성부)
- Test: `tests/ingest/test_chunker.py`

**Interfaces:**
- Consumes: `derive_fund_name`, `derive_fund_scale` (Task 2).
- Produces:
  - `chunk_document(doc, max_chars=3600, overlap_chars=540, *, year=None, doc_type=None, fund_scale_default=None) -> list[Chunk]`
  - `build_figure_chunks(doc, pdf_path, *, year=None, doc_type=None, fund_scale_default=None) -> list[Chunk]`

- [ ] **Step 1: 실패 테스트 작성** — `tests/ingest/test_chunker.py`에 추가

```python
def test_chunk_document_stamps_metadata():
    from ingest.chunker import chunk_document
    from tests.ingest.fixtures import make_doc
    chunks = chunk_document(make_doc(), year=2022, doc_type="report")
    assert chunks, "expected chunks"
    assert all(c.year == 2022 and c.doc_type == "report" for c in chunks)
    table = [c for c in chunks if c.chunk_type == "table"][0]
    assert table.fund_scale is None  # 헤딩에 규모 키워드 없음, default 없음
```

- [ ] **Step 2: 실패 확인** — Run: `uv run pytest tests/ingest/test_chunker.py -k stamps_metadata -q` → Expected: FAIL (`chunk_document() got unexpected keyword 'year'`)

- [ ] **Step 3: 구현 (chunker.py)** — `chunk_document` 시그니처 변경 및 Chunk 생성부에 메타 필드 추가

시그니처:
```python
def chunk_document(
    doc: ParsedDoc, max_chars: int = 3600, overlap_chars: int = 540,
    *, year: int | None = None, doc_type: str | None = None, fund_scale_default: str | None = None,
) -> list[Chunk]:
```

`flush()` 내부 narrative `Chunk(...)` 생성에 아래 4줄 추가(기존 `page_printed=...` 뒤). `section_path`는 `flush()`에 이미 있는 지역변수:
```python
                    year=year,
                    doc_type=doc_type,
                    fund_name=derive_fund_name(section_path),
                    fund_scale=derive_fund_scale(section_path, fund_scale_default),
```

표 브랜치(`elif item_type == "table":`)에서 인라인 `" > ".join(heading_stack)`을 지역변수로 만들고 메타 추가:
```python
            flush()
            t = item
            content = (f"{t.caption}\n" if t.caption else "") + t.markdown
            section_path = " > ".join(heading_stack)
            chunks.append(
                Chunk(
                    id=f"{doc.doc_id}-{idx}",
                    doc_id=doc.doc_id,
                    content=content,
                    chunk_type="table",
                    section_path=section_path,
                    page_physical=t.page,
                    page_printed=printed.get(t.page),
                    year=year,
                    doc_type=doc_type,
                    fund_name=derive_fund_name(section_path),
                    fund_scale=derive_fund_scale(section_path, fund_scale_default),
                )
            )
```

- [ ] **Step 4: 구현 (figures.py)** — `build_figure_chunks` 수정

```python
def build_figure_chunks(
    doc: ParsedDoc, pdf_path: str,
    *, year: int | None = None, doc_type: str | None = None, fund_scale_default: str | None = None,
) -> list[Chunk]:
    from ingest.chunker import derive_fund_name, derive_fund_scale

    chunks: list[Chunk] = []
    for i, fig in enumerate(doc.figures):
        try:
            png = render_figure_png(pdf_path, fig.page, fig.polygon)
            desc = describe_figure(png)
        except Exception as exc:  # noqa: BLE001
            desc = f"(그림 설명 생성 실패: {exc})"
        prefix = f"[그림] {fig.caption}\n" if fig.caption else "[그림] "
        section_path = heading_path_at(doc, fig.offset)
        chunks.append(
            Chunk(
                id=f"{doc.doc_id}-fig-{i}",
                doc_id=doc.doc_id,
                content=prefix + desc,
                chunk_type="figure",
                section_path=section_path,
                page_physical=fig.page,
                page_printed=None,
                year=year,
                doc_type=doc_type,
                fund_name=derive_fund_name(section_path),
                fund_scale=derive_fund_scale(section_path, fund_scale_default),
            )
        )
    return chunks
```

- [ ] **Step 5: 통과 확인** — Run: `uv run pytest tests/ingest/test_chunker.py -q` → Expected: PASS (기존 청커 테스트 포함)

- [ ] **Step 6: 커밋**

```bash
git add ingest/chunker.py ingest/figures.py tests/ingest/test_chunker.py
git commit -m "feat(ingest): 청크 생성 시 year/doc_type/fund_name/fund_scale 메타 주입"
```

---

### Task 4: 인덱스 스키마 필드 + _chunk_to_doc 적재

**Files:**
- Modify: `ingest/indexer.py` (`build_index` 필드, `_chunk_to_doc`)
- Test: `tests/ingest/test_indexer.py` (신규)

**Interfaces:**
- Consumes: `Chunk` 메타 필드(Task 1), `build_index(name) -> SearchIndex`(기존).
- Produces: 인덱스에 `year`(Int32), `doc_type`/`fund_name`/`fund_scale`(String) 필드; `_chunk_to_doc`가 non-null 메타 적재.

- [ ] **Step 1: 실패 테스트 작성** — `tests/ingest/test_indexer.py` 신규

```python
from ingest.indexer import build_index, _chunk_to_doc
from ingest.models import Chunk


def test_index_has_metadata_fields():
    names = {f.name for f in build_index("x").fields}
    assert {"year", "doc_type", "fund_name", "fund_scale"} <= names


def test_chunk_to_doc_writes_nonnull_metadata():
    c = Chunk(
        id="i", doc_id="d", content="c", chunk_type="table", section_path="s",
        page_physical=1, content_vector=[0.0], year=2022, doc_type="report",
        fund_name="국민연금기금", fund_scale=None,
    )
    doc = _chunk_to_doc(c)
    assert doc["year"] == 2022 and doc["doc_type"] == "report" and doc["fund_name"] == "국민연금기금"
    assert "fund_scale" not in doc  # None은 미적재
```

- [ ] **Step 2: 실패 확인** — Run: `uv run pytest tests/ingest/test_indexer.py -q` → Expected: FAIL (필드 없음 / year 미적재)

- [ ] **Step 3: 구현 (build_index)** — `ingest/indexer.py` `build_index`의 `section_path` 필드 다음에 4개 추가

```python
        SimpleField(name="doc_type", type=SearchFieldDataType.String, filterable=True, facetable=True),
        SimpleField(name="fund_name", type=SearchFieldDataType.String, filterable=True, facetable=True),
        SimpleField(name="fund_scale", type=SearchFieldDataType.String, filterable=True, facetable=True),
        SimpleField(name="year", type=SearchFieldDataType.Int32, filterable=True, facetable=True),
```

- [ ] **Step 4: 구현 (_chunk_to_doc)** — 마지막 반환 직전 로직을 아래로 교체

```python
    for k in ("year", "doc_type", "fund_name", "fund_scale", "page_printed"):
        v = getattr(chunk, k)
        if v is not None:
            doc[k] = v
    return doc
```

- [ ] **Step 5: 통과 확인** — Run: `uv run pytest tests/ingest/test_indexer.py -q` → Expected: PASS

- [ ] **Step 6: 커밋**

```bash
git add ingest/indexer.py tests/ingest/test_indexer.py
git commit -m "feat(ingest): 인덱스 스키마에 메타 필드 추가 + non-null 적재"
```

---

### Task 5: hybrid_search에 OData 필터 지원

**Files:**
- Modify: `search/hybrid.py` (`hybrid_search`)
- Test: `tests/search/test_hybrid.py`

**Interfaces:**
- Produces: `hybrid_search(index_name, query, top=5, odata_filter: str | None = None) -> list[SearchHit]`

- [ ] **Step 1: 실패 테스트 작성** — `tests/search/test_hybrid.py`에 추가(실제 Azure; **Task 9 재인제스트 이후에 통과**)

```python
def test_hybrid_search_accepts_odata_filter():
    from config.settings import get_settings
    from search.hybrid import hybrid_search
    s = get_settings()
    # 존재하지 않는 연도로 필터 → 0건(필터가 실제 적용됨을 확인)
    hits = hybrid_search(s.search_index_narrative, "평가", top=5, odata_filter="year eq 1900")
    assert hits == []
```

- [ ] **Step 2: 실패 확인** — Run: `uv run pytest tests/search/test_hybrid.py -k odata -q` → Expected: FAIL (`unexpected keyword 'odata_filter'`)

- [ ] **Step 3: 구현** — `search/hybrid.py` `hybrid_search` 시그니처와 `client.search` 호출 수정

```python
def hybrid_search(
    index_name: str, query: str, top: int = 5, odata_filter: str | None = None
) -> list[SearchHit]:
```
`client.search(...)` 호출에 `filter=odata_filter,` 인자 추가(예: `top=top,` 옆).

- [ ] **Step 4: 시그니처 확인** — Run: `uv run python -c "import inspect,search.hybrid as h; print('odata_filter' in inspect.signature(h.hybrid_search).parameters)"` → Expected: `True`. (실제 필터 동작 검증은 Task 9 Step 2에서.)

- [ ] **Step 5: 커밋**

```bash
git add search/hybrid.py tests/search/test_hybrid.py
git commit -m "feat(search): hybrid_search에 OData 필터 인자 추가"
```

---

### Task 6: 검색 도구에 필터 인자 + OData 조립

**Files:**
- Modify: `agent/tools.py` (`_run_tool`, `make_search_tools`, 필터 빌더 추가)
- Test: `tests/agent/test_tools.py`

**Interfaces:**
- Consumes: `hybrid_search(..., odata_filter=...)`(Task 5).
- Produces:
  - `_build_odata_filter(year=None, doc_type=None, fund_name=None, fund_scale=None) -> str | None`
  - 도구 `search_narrative(query, year=None, doc_type=None, fund_name=None, fund_scale=None)` / `search_tables(...)` 동일 시그니처.

- [ ] **Step 1: 실패 테스트 작성** — `tests/agent/test_tools.py`에 추가(순수 함수, Azure 불필요)

```python
def test_build_odata_filter_combines_nonnull():
    from agent.tools import _build_odata_filter
    assert _build_odata_filter(year=2022, doc_type="report") == "year eq 2022 and doc_type eq 'report'"
    assert _build_odata_filter() is None
    assert _build_odata_filter(fund_name="국민'연금") == "fund_name eq '국민''연금'"  # 작은따옴표 이스케이프
```

- [ ] **Step 2: 실패 확인** — Run: `uv run pytest tests/agent/test_tools.py -k odata -q` → Expected: FAIL (import error)

- [ ] **Step 3: 구현** — `agent/tools.py`에 필터 빌더 추가 및 도구/`_run_tool` 수정

```python
def _esc(v: str) -> str:
    return v.replace("'", "''")


def _build_odata_filter(
    year: int | None = None, doc_type: str | None = None,
    fund_name: str | None = None, fund_scale: str | None = None,
) -> str | None:
    clauses: list[str] = []
    if year is not None:
        clauses.append(f"year eq {int(year)}")
    if doc_type:
        clauses.append(f"doc_type eq '{_esc(doc_type)}'")
    if fund_name:
        clauses.append(f"fund_name eq '{_esc(fund_name)}'")
    if fund_scale:
        clauses.append(f"fund_scale eq '{_esc(fund_scale)}'")
    return " and ".join(clauses) or None
```

`_run_tool` 시그니처에 `odata_filter: str | None = None` 추가하고 내부 호출을 `hybrid_search(index_name, query, top=top, odata_filter=odata_filter)`로 변경.

`make_search_tools` 내부 두 도구를 필터 인자 받도록 수정:
```python
    def search_narrative(
        query: str, year: int | None = None, doc_type: str | None = None,
        fund_name: str | None = None, fund_scale: str | None = None,
    ) -> str:
        """기금운용평가보고서의 서술형 본문에서 검색합니다.

        Args:
            query: 한국어 검색 질의.
            year: 회계연도(예: 2022). 질문에 연도가 명시되면 채우세요.
            doc_type: 'report'(보고서) 또는 'guideline'(지침).
            fund_name: 개별 기금명(예: 국민연금기금).
            fund_scale: '대형중소형' 또는 '대규모'.
        """
        f = _build_odata_filter(year, doc_type, fund_name, fund_scale)
        return _run_tool(recorder, "search_narrative", settings.search_index_narrative, query, odata_filter=f)

    def search_tables(
        query: str, year: int | None = None, doc_type: str | None = None,
        fund_name: str | None = None, fund_scale: str | None = None,
    ) -> str:
        """기금운용평가보고서의 표(수치/정형 데이터)에서 검색합니다.

        Args:
            query: 한국어 검색 질의.
            year: 회계연도(예: 2022).
            doc_type: 'report' 또는 'guideline'.
            fund_name: 개별 기금명.
            fund_scale: '대형중소형' 또는 '대규모'.
        """
        f = _build_odata_filter(year, doc_type, fund_name, fund_scale)
        return _run_tool(recorder, "search_tables", settings.search_index_table, query, odata_filter=f)
```

- [ ] **Step 4: 통과 확인** — Run: `uv run pytest tests/agent/test_tools.py -q` → Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add agent/tools.py tests/agent/test_tools.py
git commit -m "feat(agent): 검색 도구에 메타 필터 인자 + OData 조립 추가"
```

---

### Task 7: 오늘 날짜 주입 + 필터/최신연도 프롬프트 규칙

**Files:**
- Modify: `agent/orchestrator.py` (`SYSTEM_PROMPT`, `build_agent`)
- Test: `tests/agent/test_orchestrator.py`

**Interfaces:**
- Consumes: 필터 지원 도구(Task 6).
- Produces: `build_agent`가 오늘 날짜를 주입한 instructions로 에이전트 생성.

- [ ] **Step 1: 실패 테스트 작성** — `tests/agent/test_orchestrator.py`에 추가

```python
def test_system_prompt_has_today_placeholder_and_filter_rule():
    from agent.orchestrator import SYSTEM_PROMPT
    assert "{today}" in SYSTEM_PROMPT
    assert "필터" in SYSTEM_PROMPT and "최신" in SYSTEM_PROMPT
```

- [ ] **Step 2: 실패 확인** — Run: `uv run pytest tests/agent/test_orchestrator.py -k today -q` → Expected: FAIL

- [ ] **Step 3: 구현** — `agent/orchestrator.py`

파일 상단 import에 추가:
```python
from datetime import date
```

`SYSTEM_PROMPT` 마지막 규칙(현재 6번) 다음, 닫는 `"""` 앞에 규칙 7 추가:
```
7. 오늘은 {today}이다. 질문에 연도·문서유형(보고서=report/지침=guideline)·기금명·기금규모(대형중소형/대규모)가 명시되면 검색 도구의 해당 필터 인자를 채워라. 연도를 지정하지 않으면 현재 시점 기준 가장 최신 회계연도 보고서를 기본으로 조회하라. '작년/최근' 등 상대 표현은 오늘 날짜 기준으로 해석하라. 여러 연도를 비교하는 질문이면 연도별로 각각 검색하라. fund_name/fund_scale 필터로 0건이면 해당 필터를 빼고 재검색하라.
```

`build_agent`의 `return client.as_agent(...)`를 아래로 수정(오늘 날짜 주입):
```python
    instructions = SYSTEM_PROMPT.replace("{today}", date.today().isoformat())
    return client.as_agent(
        name="mirae-fund-agent",
        instructions=instructions,
        tools=tools,
        default_options={"reasoning": {"effort": "medium", "summary": "auto"}},
    )
```

- [ ] **Step 4: 통과 확인** — Run: `uv run pytest tests/agent/test_orchestrator.py -q` → Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add agent/orchestrator.py tests/agent/test_orchestrator.py
git commit -m "feat(agent): 오늘 날짜 주입 + 메타 필터/최신연도 기본 프롬프트 규칙"
```

---

### Task 8: 문서 레지스트리 + run.py 재인제스트 CLI

**Files:**
- Create: `ingest/corpus.py`
- Modify: `ingest/run.py` (`run` 시그니처, `run_corpus`, `main`)
- Test: `tests/ingest/test_corpus.py` (신규)

**Interfaces:**
- Consumes: `chunk_document(..., year=, doc_type=, fund_scale_default=)`, `build_figure_chunks(..., year=, doc_type=, fund_scale_default=)`(Task 3), `reset_indexes()`/`ensure_indexes()`(기존).
- Produces:
  - `ingest/corpus.py`: `class CorpusDoc(BaseModel)`(`pdf,doc_id,year,doc_type,fund_scale`), `CORPUS: list[CorpusDoc]`, `get_doc(doc_id) -> CorpusDoc | None`.
  - `run(pdf, doc_id, pages, use_cache, figures=True, reset=False, year=None, doc_type=None, fund_scale=None) -> int`
  - `run_corpus(reset=False, use_cache=True, figures=True) -> int`

- [ ] **Step 1: 실패 테스트 작성** — `tests/ingest/test_corpus.py` 신규

```python
import os
from ingest.corpus import CORPUS, get_doc


def test_corpus_entries_valid():
    assert len(CORPUS) == 5
    ids = [d.doc_id for d in CORPUS]
    assert len(set(ids)) == 5  # doc_id 유일
    for d in CORPUS:
        assert d.doc_type in ("report", "guideline")
        assert 2000 <= d.year <= 2100
        assert os.path.exists(d.pdf), f"missing pdf: {d.pdf}"


def test_get_doc_lookup():
    assert get_doc("report-2025").year == 2025
    assert get_doc("nope") is None
```

- [ ] **Step 2: 실패 확인** — Run: `uv run pytest tests/ingest/test_corpus.py -q` → Expected: FAIL (module 없음)

- [ ] **Step 3: 구현 (corpus.py)** — 파일명은 `Docs/` 실제 파일과 정확히 일치해야 함(`ls Docs/*.pdf`로 대조)

```python
from __future__ import annotations

from pydantic import BaseModel


class CorpusDoc(BaseModel):
    pdf: str
    doc_id: str
    year: int
    doc_type: str  # "report" | "guideline"
    fund_scale: str | None = None


CORPUS: list[CorpusDoc] = [
    CorpusDoc(pdf="Docs/2025회계연도 기금운용평가보고서(자산운용부문).pdf", doc_id="report-2025", year=2025, doc_type="report"),
    CorpusDoc(pdf="Docs/2022회계연도기금운용평가보고서Ⅱ(자산운용부문).pdf", doc_id="report-2022", year=2022, doc_type="report"),
    CorpusDoc(pdf="Docs/2021회계연도 기금운용평가보고서Ⅱ(자산운용부문).pdf", doc_id="report-2021", year=2021, doc_type="report"),
    CorpusDoc(pdf="Docs/2021회계연도 기금운용평가지침1(대형중소형).pdf", doc_id="guideline-2021-dh", year=2021, doc_type="guideline", fund_scale="대형중소형"),
    CorpusDoc(pdf="Docs/2022회계연도 기금운용평가지침1(대형중소형부문).pdf", doc_id="guideline-2022-dh", year=2022, doc_type="guideline", fund_scale="대형중소형"),
]


def get_doc(doc_id: str) -> CorpusDoc | None:
    return next((d for d in CORPUS if d.doc_id == doc_id), None)
```

- [ ] **Step 4: 구현 (run.py)** — `run` 시그니처 확장 + `run_corpus` 추가 + `main` 재작성

`run`:
```python
def run(pdf: str, doc_id: str, pages: str | None, use_cache: bool, figures: bool = True,
        reset: bool = False, year: int | None = None, doc_type: str | None = None,
        fund_scale: str | None = None) -> int:
    reset_indexes() if reset else ensure_indexes()
    doc = analyze_pdf(pdf, doc_id, pages=pages, use_cache=use_cache)
    chunks = chunk_document(doc, year=year, doc_type=doc_type, fund_scale_default=fund_scale)
    if figures:
        chunks += build_figure_chunks(doc, pdf, year=year, doc_type=doc_type, fund_scale_default=fund_scale)
    vectors = embed_texts([c.content for c in chunks])
    for c, v in zip(chunks, vectors):
        c.content_vector = v
    total = upload_chunks(chunks)
    n_table = sum(1 for c in chunks if c.chunk_type == "table")
    n_fig = sum(1 for c in chunks if c.chunk_type == "figure")
    print(f"doc_id={doc_id} chunks={total} (narrative={total - n_table - n_fig}, table={n_table}, figure={n_fig})")
    return total


def run_corpus(reset: bool = False, use_cache: bool = True, figures: bool = True) -> int:
    from ingest.corpus import CORPUS
    total = 0
    for i, d in enumerate(CORPUS):
        total += run(d.pdf, d.doc_id, None, use_cache, figures,
                     reset=(reset and i == 0),  # 재생성은 첫 문서에서 1회만
                     year=d.year, doc_type=d.doc_type, fund_scale=d.fund_scale)
    return total
```
`import`에 `reset_indexes` 추가(`from ingest.indexer import ensure_indexes, reset_indexes, upload_chunks`).

`main` 재작성:
```python
def main() -> None:
    from agent.observability import setup_observability
    from ingest.corpus import get_doc

    setup_observability()
    ap = argparse.ArgumentParser(description="Ingest fund-evaluation PDFs into Azure AI Search")
    ap.add_argument("--all", action="store_true", help="레지스트리 전체 인제스트")
    ap.add_argument("--doc-id", help="레지스트리의 특정 문서만 인제스트")
    ap.add_argument("--pages", default=None, help="예: '1-100' (DI 페이지 범위)")
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--no-figures", action="store_true", help="그림 설명 인덱싱 비활성")
    ap.add_argument("--reset", action="store_true", help="인덱스 삭제 후 재생성(스키마 반영)")
    args = ap.parse_args()

    if args.all:
        run_corpus(reset=args.reset, use_cache=not args.no_cache, figures=not args.no_figures)
        return
    if not args.doc_id:
        ap.error("--all 또는 --doc-id 중 하나가 필요합니다")
    d = get_doc(args.doc_id)
    if d is None:
        ap.error(f"레지스트리에 없는 doc_id: {args.doc_id}")
    run(d.pdf, d.doc_id, args.pages, use_cache=not args.no_cache, figures=not args.no_figures,
        reset=args.reset, year=d.year, doc_type=d.doc_type, fund_scale=d.fund_scale)
```

- [ ] **Step 5: 통과 확인** — Run: `uv run pytest tests/ingest/test_corpus.py -q` → Expected: PASS. 또한 `uv run python -c "import ingest.run"` → import 에러 없음.

- [ ] **Step 6: 커밋**

```bash
git add ingest/corpus.py ingest/run.py tests/ingest/test_corpus.py
git commit -m "feat(ingest): 문서 레지스트리(corpus) + run --all/--doc-id/--reset 재인제스트"
```

---

### Task 9: 마이그레이션 — 인덱스 재생성 + 전체 재인제스트 + 검증

**Files:**
- 없음(운영 태스크).

**Interfaces:**
- Consumes: `run_corpus`, `hybrid_search(odata_filter=...)`, 인덱스 스키마(Task 4~8).

- [ ] **Step 1: 전체 재인제스트(재생성 포함)** — Run:

```bash
uv run python -m ingest.run --all --reset
```
Expected: 5개 문서 각각 `doc_id=... chunks=N (...)` 출력. 최초 문서에서 인덱스 재생성. DI는 신규 4개만 호출(2025 캐시), 수 분 소요.

- [ ] **Step 2: 필터 동작 검증** — Run:

```bash
uv run python -c "
from config.settings import get_settings
from search.hybrid import hybrid_search
s=get_settings()
a=hybrid_search(s.search_index_narrative,'평가 개요',top=5,odata_filter=\"year eq 2022\")
b=hybrid_search(s.search_index_narrative,'평가 개요',top=5,odata_filter=\"doc_type eq 'guideline'\")
print('year=2022 hits:',len(a))
print('guideline hits:',len(b))
assert a and b
"
```
Expected: `year=2022 hits: >0`, `guideline hits: >0`, 에러 없음.

- [ ] **Step 3: 전체 회귀 테스트** — Run: `uv run pytest -q` → Expected: 전부 PASS (Task 5의 hybrid 필터 테스트 포함).

- [ ] **Step 4: 커밋(코드 변경 없으면 생략)** — 검증용 임시 파일은 만들지 않음.

---

## Self-Review

**Spec coverage:**
- 인덱스 스키마(§3) → Task 1,4 ✅
- 메타데이터 추출(§4) → Task 2,3 ✅
- 레지스트리/파이프라인(§5) → Task 8 ✅
- 검색/도구 필터(§6) → Task 5,6 ✅
- 오늘 날짜 주입(§6) → Task 7 ✅
- 마이그레이션(§7) → Task 9 ✅
- 테스트(§8) → 각 Task TDD + Task 9 통합 ✅

**Placeholder scan:** 각 코드 스텝에 실제 코드 포함, "TBD/적절히 처리" 없음.

**Type consistency:** `derive_fund_name`/`derive_fund_scale`(Task 2)가 Task 3에서 동일 사용; `_build_odata_filter`/`odata_filter` 인자명이 Task 5·6 일치; `CorpusDoc` 필드가 Task 8 전반 일치.

**실행 순서 주의:** Task 5의 실제 필터 동작(`year eq 1900`/`year eq 2022`)은 **인덱스에 year 필드가 생기고(Task 4) 재인제스트(Task 9)된 이후** 통과한다. 따라서 Task 5 Step 4는 시그니처만 확인하고, 필터 실동작·회귀 그린은 Task 9에서 확정한다.
