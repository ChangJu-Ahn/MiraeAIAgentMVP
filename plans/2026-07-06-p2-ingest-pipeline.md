# P2: 인제스트 파이프라인 (DI 파싱 → 레이아웃 청킹 → 임베딩 → 하이브리드 인덱스) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 실제 기금운용평가보고서 PDF를 Azure Document Intelligence(prebuilt-layout, 마크다운)로 파싱하고, 레이아웃 인지 계층 청킹(표는 통째로)으로 나눈 뒤 Microsoft Foundry 임베딩을 계산하여 Azure AI Search의 2개 하이브리드 인덱스(narrative-index, table-index)에 적재하고, 인덱스별 하이브리드(벡터+BM25+시맨틱) 검색 헬퍼를 제공한다.

**Architecture:** `ingest/`가 4단계 파이프라인을 담당: (1) DI 분석 → 정규화된 `ParsedDoc`(+원본 JSON 캐시), (2) `ParsedDoc` → `list[Chunk]` 레이아웃 청킹, (3) Foundry 배치 임베딩, (4) AI Search 인덱스 생성 + upsert. `search/`가 하이브리드 검색 헬퍼를 제공(P3 에이전트가 사용). DI 결과는 로컬 캐시하여 청킹/임베딩 반복 시 재호출·재과금을 피한다. 청킹은 SDK와 분리된 순수 함수로 유닛 테스트한다.

**Tech Stack:** Python 3.12(uv), azure-ai-documentintelligence 1.0.2, azure-search-documents 12.0.0, openai(AzureOpenAI, Foundry), azure-identity(DefaultAzureCredential), pydantic, pytest.

## Global Constraints

- 필수 Azure 서비스만 사용: Document Intelligence(파싱/마크다운), AI Search(검색+벡터), Foundry(임베딩). (스펙 §1)
- 키리스: 모든 클라이언트는 `DefaultAzureCredential` 사용. API 키 금지. (스펙 §1)
- 설정은 `config.settings.get_settings()`에서만 읽는다(엔드포인트/배포명/인덱스명). 하드코딩 금지. 모델 교체성 유지. (스펙 §1, §2)
- 임베딩 모델은 `text-embedding-3-large`, 차원 **3072**. 인덱스 벡터 필드 차원과 반드시 일치.
- 청킹 전략 A(레이아웃 인지 계층): 표는 분할 금지(단일 청크), 섹션 헤딩 계층으로 `section_path` 구성, 긴 섹션은 문단 경계로 재분할(목표 ≈800~1000 토큰, 오버랩 ≈15%). (스펙 §3)
- 인덱스 2개: `narrative-index`(서술 청크), `table-index`(표 청크). 각각 벡터+BM25+시맨틱. (스펙 §3)
- DI 결과는 `.ingest_cache/`에 캐시(gitignore). PDF 원본은 `Docs/`(기존).
- 모든 커밋 끝에 트레일러 포함:
  `Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>`
- 실 배포된 리소스 사용: RG `rg-mirae-ai-agent-poc`(koreacentral). 실제 Azure 호출 테스트 허용.

---

## File Structure

- `ingest/__init__.py`
- `ingest/models.py` — `ParsedParagraph`, `ParsedTable`, `ParsedDoc`, `Chunk` (pydantic 모델)
- `ingest/parser.py` — DI 호출 + `AnalyzeResult` → `ParsedDoc` 정규화 + 로컬 캐시
- `ingest/chunker.py` — `ParsedDoc` → `list[Chunk]` (순수 함수, 레이아웃 인지)
- `ingest/embedder.py` — Foundry 배치 임베딩
- `ingest/indexer.py` — AI Search 인덱스 스키마 생성(2개) + 청크 upsert
- `ingest/run.py` — CLI 오케스트레이터 (analyze→chunk→embed→upload)
- `search/__init__.py`
- `search/hybrid.py` — 인덱스별 하이브리드 검색 헬퍼
- `tests/ingest/__init__.py`
- `tests/ingest/test_chunker.py` — 청킹 유닛 테스트(합성 fixture)
- `tests/ingest/test_models.py` — 모델 검증
- `tests/ingest/fixtures.py` — 합성 `ParsedDoc` 빌더
- `tests/search/__init__.py`
- `tests/search/test_hybrid.py` — 실 Search 대상 하이브리드 검색 통합 테스트
- `.gitignore` (수정: `.ingest_cache/` 추가)

---

## Task 1: 데이터 모델 (ingest/models.py)

**Files:**
- Create: `ingest/__init__.py`, `ingest/models.py`, `tests/ingest/__init__.py`, `tests/ingest/test_models.py`

**Interfaces:**
- Produces:
  - `ParsedParagraph(role: str | None, content: str, page: int)`
  - `ParsedTable(markdown: str, page: int, caption: str | None = None)`
  - `ParsedDoc(doc_id: str, markdown: str, paragraphs: list[ParsedParagraph], tables: list[ParsedTable])`
  - `Chunk(id: str, doc_id: str, content: str, chunk_type: str, section_path: str, page_printed: int | None, page_physical: int, year: int | None = None, fund_name: str | None = None, content_vector: list[float] | None = None)`
  - `chunk_type` ∈ {"narrative", "table"}.

- [ ] **Step 1: 실패하는 테스트 작성**

Create `tests/ingest/__init__.py` (empty), then `tests/ingest/test_models.py`:
```python
from ingest.models import Chunk, ParsedDoc, ParsedParagraph, ParsedTable


def test_parsed_doc_holds_elements():
    doc = ParsedDoc(
        doc_id="d1",
        markdown="# T",
        paragraphs=[ParsedParagraph(role="title", content="T", page=1)],
        tables=[ParsedTable(markdown="| a |\n|---|", page=2, caption="cap")],
    )
    assert doc.paragraphs[0].role == "title"
    assert doc.tables[0].page == 2


def test_chunk_defaults():
    c = Chunk(
        id="d1-0",
        doc_id="d1",
        content="body",
        chunk_type="narrative",
        section_path="Ⅱ > 1 > 가",
        page_printed=24,
        page_physical=40,
    )
    assert c.year is None
    assert c.fund_name is None
    assert c.content_vector is None
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/ingest/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ingest'`

- [ ] **Step 3: 모델 구현**

Create `ingest/__init__.py` (empty). Create `ingest/models.py`:
```python
from __future__ import annotations

from pydantic import BaseModel


class ParsedParagraph(BaseModel):
    role: str | None
    content: str
    page: int


class ParsedTable(BaseModel):
    markdown: str
    page: int
    caption: str | None = None


class ParsedDoc(BaseModel):
    doc_id: str
    markdown: str
    paragraphs: list[ParsedParagraph]
    tables: list[ParsedTable]


class Chunk(BaseModel):
    id: str
    doc_id: str
    content: str
    chunk_type: str  # "narrative" | "table"
    section_path: str
    page_printed: int | None = None
    page_physical: int
    year: int | None = None
    fund_name: str | None = None
    content_vector: list[float] | None = None
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/ingest/test_models.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add ingest/__init__.py ingest/models.py tests/ingest/__init__.py tests/ingest/test_models.py
git commit -m "feat(ingest): add ParsedDoc and Chunk data models

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 2: 레이아웃 인지 청커 (ingest/chunker.py)

**Files:**
- Create: `ingest/chunker.py`, `tests/ingest/fixtures.py`, `tests/ingest/test_chunker.py`

**Interfaces:**
- Consumes: `ParsedDoc`, `ParsedParagraph`, `ParsedTable` (Task 1).
- Produces:
  - `chunk_document(doc: ParsedDoc, max_chars: int = 3600, overlap_chars: int = 540) -> list[Chunk]`
  - 규칙: (a) 각 `ParsedTable`은 정확히 1개의 `chunk_type="table"` 청크가 된다(분할 금지, 캡션 포함). (b) 서술 문단은 헤딩 role(`title`,`sectionHeading`)로 섹션을 나누고 각 섹션 텍스트를 `max_chars` 기준으로 문단 경계에서 분할(연속 청크는 `overlap_chars` 만큼 겹침), `chunk_type="narrative"`. (c) `section_path`는 현재까지의 헤딩 스택을 " > "로 결합. (d) `page_physical`은 청크 시작 문단/표의 page. (e) `page_printed`는 같은 페이지의 role=="pageNumber" 문단에서 정수 파싱 가능 시 채움. (f) `id`는 `f"{doc_id}-{running_index}"`.
  - `max_chars=3600`은 대략 900 토큰(한글 ~4자/토큰 가정), `overlap_chars=540`은 15%.

- [ ] **Step 1: 합성 fixture 작성**

Create `tests/ingest/fixtures.py`:
```python
from ingest.models import ParsedDoc, ParsedParagraph, ParsedTable


def make_doc() -> ParsedDoc:
    paras = [
        ParsedParagraph(role="title", content="Ⅱ. 자산운용부문 평가결과", page=1),
        ParsedParagraph(role="sectionHeading", content="1. 평가 개요", page=1),
        ParsedParagraph(role="sectionHeading", content="가. 평가의 특징", page=1),
        ParsedParagraph(role=None, content="가나다 " * 500, page=1),  # 긴 문단 → 분할
        ParsedParagraph(role="pageNumber", content="- 24 -", page=1),
        ParsedParagraph(role="sectionHeading", content="나. 평가결과 공개", page=2),
        ParsedParagraph(role=None, content="짧은 문단.", page=2),
    ]
    tables = [ParsedTable(markdown="| 등급 | 내용 |\n|---|---|\n| 탁월 | 높음 |", page=2, caption="종합등급")]
    return ParsedDoc(doc_id="d1", markdown="", paragraphs=paras, tables=tables)
```

- [ ] **Step 2: 실패하는 테스트 작성**

Create `tests/ingest/test_chunker.py`:
```python
from ingest.chunker import chunk_document
from tests.ingest.fixtures import make_doc


def test_tables_are_single_chunks():
    chunks = chunk_document(make_doc())
    tables = [c for c in chunks if c.chunk_type == "table"]
    assert len(tables) == 1
    assert "종합등급" in tables[0].content
    assert "| 등급 | 내용 |" in tables[0].content


def test_section_path_built_from_headings():
    chunks = chunk_document(make_doc())
    narrative = [c for c in chunks if c.chunk_type == "narrative"]
    # 긴 문단은 "가. 평가의 특징" 섹션에 속한다
    long_chunks = [c for c in narrative if "가나다" in c.content]
    assert long_chunks
    assert long_chunks[0].section_path == "Ⅱ. 자산운용부문 평가결과 > 1. 평가 개요 > 가. 평가의 특징"


def test_long_section_is_split_with_overlap():
    chunks = chunk_document(make_doc(), max_chars=400, overlap_chars=60)
    long_chunks = [c for c in chunks if c.chunk_type == "narrative" and "가나다" in c.content]
    assert len(long_chunks) >= 2
    # 오버랩: 다음 청크 시작이 이전 청크 끝 일부를 포함
    assert long_chunks[0].content[-30:] in long_chunks[1].content


def test_printed_page_number_captured():
    chunks = chunk_document(make_doc())
    page1 = [c for c in chunks if c.page_physical == 1 and c.chunk_type == "narrative"]
    assert any(c.page_printed == 24 for c in page1)


def test_ids_unique_and_prefixed():
    chunks = chunk_document(make_doc())
    ids = [c.id for c in chunks]
    assert len(ids) == len(set(ids))
    assert all(i.startswith("d1-") for i in ids)
```

- [ ] **Step 3: 테스트 실패 확인**

Run: `uv run pytest tests/ingest/test_chunker.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ingest.chunker'`

- [ ] **Step 4: 청커 구현**

Create `ingest/chunker.py`:
```python
from __future__ import annotations

import re

from ingest.models import Chunk, ParsedDoc, ParsedParagraph

HEADING_ROLES = {"title", "sectionHeading"}


def _printed_pages(doc: ParsedDoc) -> dict[int, int]:
    """physical page -> printed page number (from role=='pageNumber' paragraphs)."""
    out: dict[int, int] = {}
    for p in doc.paragraphs:
        if p.role == "pageNumber":
            m = re.search(r"\d+", p.content)
            if m:
                out[p.page] = int(m.group())
    return out


def _split_text(text: str, max_chars: int, overlap_chars: int) -> list[str]:
    text = text.strip()
    if len(text) <= max_chars:
        return [text] if text else []
    parts: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        parts.append(text[start:end])
        if end >= len(text):
            break
        start = end - overlap_chars
    return parts


def chunk_document(doc: ParsedDoc, max_chars: int = 3600, overlap_chars: int = 540) -> list[Chunk]:
    printed = _printed_pages(doc)
    chunks: list[Chunk] = []
    idx = 0
    heading_stack: list[str] = []
    buffer: list[ParsedParagraph] = []

    def flush() -> None:
        nonlocal idx
        if not buffer:
            return
        section_path = " > ".join(heading_stack)
        text = "\n".join(p.content for p in buffer).strip()
        start_page = buffer[0].page
        for piece in _split_text(text, max_chars, overlap_chars):
            chunks.append(
                Chunk(
                    id=f"{doc.doc_id}-{idx}",
                    doc_id=doc.doc_id,
                    content=piece,
                    chunk_type="narrative",
                    section_path=section_path,
                    page_physical=start_page,
                    page_printed=printed.get(start_page),
                )
            )
            idx += 1
        buffer.clear()

    for p in doc.paragraphs:
        if p.role == "pageNumber":
            continue
        if p.role in HEADING_ROLES:
            flush()
            # 헤딩 레벨: title=0, sectionHeading은 번호 패턴으로 깊이 추정
            if p.role == "title":
                heading_stack = [p.content]
            else:
                depth = _heading_depth(p.content)
                heading_stack = heading_stack[:depth] + [p.content]
            continue
        buffer.append(p)
    flush()

    for t in doc.tables:
        content = (f"{t.caption}\n" if t.caption else "") + t.markdown
        chunks.append(
            Chunk(
                id=f"{doc.doc_id}-{idx}",
                doc_id=doc.doc_id,
                content=content,
                chunk_type="table",
                section_path=" > ".join(heading_stack),
                page_physical=t.page,
                page_printed=printed.get(t.page),
            )
        )
        idx += 1
    return chunks


def _heading_depth(text: str) -> int:
    """번호 스타일로 헤딩 깊이 추정: '1.'→1, '가.'→2, 'ㅇ'→3, 기타→1."""
    t = text.strip()
    if re.match(r"^\d+\.", t):
        return 1
    if re.match(r"^[가-힣]\.", t):
        return 2
    if t.startswith("ㅇ") or t.startswith("-"):
        return 3
    return 1
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `uv run pytest tests/ingest/test_chunker.py -v`
Expected: PASS (5 passed). 필요 시 `section_path` 기대값이 `_heading_depth` 로직과 일치하도록 조정하되, 테스트 의도(계층 결합·표 단일화·오버랩·printed page)는 유지.

- [ ] **Step 6: Commit**

```bash
git add ingest/chunker.py tests/ingest/fixtures.py tests/ingest/test_chunker.py
git commit -m "feat(ingest): add layout-aware hierarchical chunker

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 3: DI 파서 + 캐시 (ingest/parser.py)

**Files:**
- Create: `ingest/parser.py`
- Modify: `.gitignore` (add `.ingest_cache/`)

**Interfaces:**
- Consumes: `config.settings.get_settings()`, `DefaultAzureCredential`, `ParsedDoc` 모델.
- Produces:
  - `analyze_pdf(pdf_path: str, doc_id: str, pages: str | None = None, use_cache: bool = True) -> ParsedDoc`
    - DI `prebuilt-layout`를 `output_content_format=MARKDOWN`, `features=[KEY_VALUE_PAIRS]`로 호출.
    - 원본 결과(`result.as_dict()`)를 `.ingest_cache/{doc_id}.json`에 저장/재사용.
    - `AnalyzeResult` → `ParsedDoc`: `markdown=result.content`; paragraphs는 `result.paragraphs`의 `role`,`content` + 첫 bounding_region의 `page_number`; tables는 `result.tables`를 마크다운 문자열로 변환(행/열 재구성) + 표 직전/직후 캡션 문단 추정은 생략(간단히 None).
- 참고: 큰 PDF는 단일 analyze 호출(S0 tier, 532p 허용). 타임아웃/한도 시 `pages`(예 "1-100")로 분할 호출 후 병합 가능.

- [ ] **Step 1: parser 구현**

Create `ingest/parser.py`:
```python
from __future__ import annotations

import json
import os
from pathlib import Path

from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.ai.documentintelligence.models import (
    AnalyzeDocumentRequest,
    AnalyzeResult,
    DocumentAnalysisFeature,
    DocumentContentFormat,
)
from azure.identity import DefaultAzureCredential

from config.settings import get_settings
from ingest.models import ParsedDoc, ParsedParagraph, ParsedTable

CACHE_DIR = Path(".ingest_cache")


def _table_to_markdown(table: dict) -> str:
    rows = table["rowCount"]
    cols = table["columnCount"]
    grid = [["" for _ in range(cols)] for _ in range(rows)]
    for cell in table["cells"]:
        r, c = cell["rowIndex"], cell["columnIndex"]
        if r < rows and c < cols:
            grid[r][c] = (cell.get("content") or "").replace("\n", " ").strip()
    lines = ["| " + " | ".join(grid[0]) + " |", "|" + "|".join(["---"] * cols) + "|"]
    for row in grid[1:]:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def _page_of(element: dict) -> int:
    regions = element.get("boundingRegions") or []
    return regions[0]["pageNumber"] if regions else 1


def _result_to_parsed(doc_id: str, data: dict) -> ParsedDoc:
    paragraphs = [
        ParsedParagraph(role=p.get("role"), content=p.get("content", ""), page=_page_of(p))
        for p in data.get("paragraphs", [])
    ]
    tables = [
        ParsedTable(markdown=_table_to_markdown(t), page=_page_of(t))
        for t in data.get("tables", [])
    ]
    return ParsedDoc(
        doc_id=doc_id,
        markdown=data.get("content", ""),
        paragraphs=paragraphs,
        tables=tables,
    )


def analyze_pdf(
    pdf_path: str, doc_id: str, pages: str | None = None, use_cache: bool = True
) -> ParsedDoc:
    CACHE_DIR.mkdir(exist_ok=True)
    cache_file = CACHE_DIR / f"{doc_id}.json"
    if use_cache and cache_file.exists():
        data = json.loads(cache_file.read_text(encoding="utf-8"))
        return _result_to_parsed(doc_id, data)

    s = get_settings()
    client = DocumentIntelligenceClient(
        endpoint=s.doc_intelligence_endpoint, credential=DefaultAzureCredential()
    )
    with open(pdf_path, "rb") as f:
        poller = client.begin_analyze_document(
            "prebuilt-layout",
            AnalyzeDocumentRequest(bytes_source=f.read()),
            pages=pages,
            output_content_format=DocumentContentFormat.MARKDOWN,
            features=[DocumentAnalysisFeature.KEY_VALUE_PAIRS],
        )
    result: AnalyzeResult = poller.result()
    data = result.as_dict()
    cache_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return _result_to_parsed(doc_id, data)
```

- [ ] **Step 2: .gitignore 갱신**

Edit `.gitignore` — add under "Local artifacts":
```
.ingest_cache/
```

- [ ] **Step 3: 실제 소규모 분석으로 검증 (1페이지)**

Run:
```bash
uv run python -c "
from ingest.parser import analyze_pdf
d = analyze_pdf('Docs/2025회계연도 기금운용평가보고서(자산운용부문).pdf', 'probe-p1', pages='1', use_cache=False)
print('paragraphs:', len(d.paragraphs))
print('roles:', sorted({p.role for p in d.paragraphs if p.role}))
print('markdown head:', d.markdown[:120].replace(chr(10),' '))
"
```
Expected: paragraphs > 0, roles에 'title'/'sectionHeading' 류 포함, markdown에 한글 텍스트. (DI 실호출; 수십 초 소요) 이후 `.ingest_cache/probe-p1.json` 생성.

- [ ] **Step 4: Commit**

```bash
git add ingest/parser.py .gitignore
git commit -m "feat(ingest): add Document Intelligence layout parser with cache

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 4: Foundry 임베딩 (ingest/embedder.py)

**Files:**
- Create: `ingest/embedder.py`

**Interfaces:**
- Consumes: `config.settings.get_settings()`, `DefaultAzureCredential`.
- Produces:
  - `embed_texts(texts: list[str], batch_size: int = 32) -> list[list[float]]` — Foundry `text-embedding-3-large`(3072차원) 배치 임베딩. 입력 순서 보존.
  - 내부: `AzureOpenAI`(azure_ad_token_provider), endpoint는 `foundry_project_endpoint`에서 `/api/projects`앞 베이스 사용(P1 smoke_test와 동일 방식), `api_version=settings.foundry_api_version`, `model=settings.foundry_embedding_deployment`.

- [ ] **Step 1: embedder 구현**

Create `ingest/embedder.py`:
```python
from __future__ import annotations

from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from openai import AzureOpenAI

from config.settings import get_settings

_SCOPE = "https://cognitiveservices.azure.com/.default"


def _client() -> tuple[AzureOpenAI, str]:
    s = get_settings()
    base = s.foundry_project_endpoint.split("/api/projects")[0]
    provider = get_bearer_token_provider(DefaultAzureCredential(), _SCOPE)
    client = AzureOpenAI(
        azure_endpoint=base,
        api_version=s.foundry_api_version,
        azure_ad_token_provider=provider,
    )
    return client, s.foundry_embedding_deployment


def embed_texts(texts: list[str], batch_size: int = 32) -> list[list[float]]:
    if not texts:
        return []
    client, deployment = _client()
    vectors: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        resp = client.embeddings.create(model=deployment, input=batch)
        vectors.extend(item.embedding for item in resp.data)
    return vectors
```

- [ ] **Step 2: 실제 임베딩 검증 (차원 3072)**

Run:
```bash
uv run python -c "
from ingest.embedder import embed_texts
v = embed_texts(['국민연금기금 평가 등급', '자산운용 수익률'])
print('count:', len(v), 'dim:', len(v[0]))
assert len(v) == 2 and len(v[0]) == 3072
print('OK')
"
```
Expected: `count: 2 dim: 3072` 그리고 `OK`. (Foundry 실호출)

- [ ] **Step 3: Commit**

```bash
git add ingest/embedder.py
git commit -m "feat(ingest): add Foundry batch embedder (text-embedding-3-large, 3072d)

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 5: AI Search 인덱스 스키마 (ingest/indexer.py — 스키마 부분)

**Files:**
- Create: `ingest/indexer.py`

**Interfaces:**
- Consumes: `config.settings.get_settings()`, `DefaultAzureCredential`.
- Produces:
  - `build_index(name: str) -> SearchIndex` — 필드: `id`(key), `content`(searchable, ko.lucene analyzer), `content_vector`(Collection(Edm.Single), 3072, HNSW profile), `doc_id`/`chunk_type`/`section_path`/`fund_name`(filterable), `page_physical`/`page_printed`/`year`(filterable, Edm.Int32). 벡터: HNSW config + profile `hnsw-profile`. 시맨틱: config `sem` (content 우선).
  - `ensure_indexes() -> None` — narrative-index, table-index 두 개를 `create_or_update_index`로 생성/갱신(idempotent).

- [ ] **Step 1: indexer 스키마 구현**

Create `ingest/indexer.py`:
```python
from __future__ import annotations

from azure.identity import DefaultAzureCredential
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    HnswAlgorithmConfiguration,
    SearchableField,
    SearchField,
    SearchFieldDataType,
    SearchIndex,
    SemanticConfiguration,
    SemanticField,
    SemanticPrioritizedFields,
    SemanticSearch,
    SimpleField,
    VectorSearch,
    VectorSearchProfile,
)

from config.settings import get_settings

EMBED_DIM = 3072


def build_index(name: str) -> SearchIndex:
    fields = [
        SimpleField(name="id", type=SearchFieldDataType.String, key=True),
        SearchableField(name="content", type=SearchFieldDataType.String, analyzer_name="ko.lucene"),
        SearchField(
            name="content_vector",
            type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
            searchable=True,
            vector_search_dimensions=EMBED_DIM,
            vector_search_profile_name="hnsw-profile",
        ),
        SimpleField(name="doc_id", type=SearchFieldDataType.String, filterable=True),
        SimpleField(name="chunk_type", type=SearchFieldDataType.String, filterable=True, facetable=True),
        SearchableField(name="section_path", type=SearchFieldDataType.String, filterable=True),
        SimpleField(name="fund_name", type=SearchFieldDataType.String, filterable=True, facetable=True),
        SimpleField(name="year", type=SearchFieldDataType.Int32, filterable=True, facetable=True),
        SimpleField(name="page_physical", type=SearchFieldDataType.Int32, filterable=True),
        SimpleField(name="page_printed", type=SearchFieldDataType.Int32, filterable=True),
    ]
    vector_search = VectorSearch(
        algorithms=[HnswAlgorithmConfiguration(name="hnsw")],
        profiles=[VectorSearchProfile(name="hnsw-profile", algorithm_configuration_name="hnsw")],
    )
    semantic = SemanticSearch(
        default_configuration_name="sem",
        configurations=[
            SemanticConfiguration(
                name="sem",
                prioritized_fields=SemanticPrioritizedFields(
                    title_field=SemanticField(field_name="section_path"),
                    content_fields=[SemanticField(field_name="content")],
                ),
            )
        ],
    )
    return SearchIndex(
        name=name, fields=fields, vector_search=vector_search, semantic_search=semantic
    )


def ensure_indexes() -> None:
    s = get_settings()
    client = SearchIndexClient(endpoint=s.search_endpoint, credential=DefaultAzureCredential())
    for name in (s.search_index_narrative, s.search_index_table):
        client.create_or_update_index(build_index(name))
```

- [ ] **Step 2: 실제 인덱스 생성 검증**

Run:
```bash
uv run python -c "
from ingest.indexer import ensure_indexes
from azure.identity import DefaultAzureCredential
from azure.search.documents.indexes import SearchIndexClient
from config.settings import get_settings
ensure_indexes()
s=get_settings(); c=SearchIndexClient(endpoint=s.search_endpoint, credential=DefaultAzureCredential())
for n in (s.search_index_narrative, s.search_index_table):
    idx=c.get_index(n); print(n, 'fields:', [f.name for f in idx.fields])
print('OK')
"
```
Expected: 두 인덱스 모두 생성되고 필드 목록에 `content`,`content_vector`,`section_path` 등 포함, `OK`.

- [ ] **Step 3: Commit**

```bash
git add ingest/indexer.py
git commit -m "feat(ingest): add AI Search index schema (vector+semantic, 2 indexes)

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 6: 청크 upsert (ingest/indexer.py — 업로드 부분)

**Files:**
- Modify: `ingest/indexer.py`

**Interfaces:**
- Consumes: `Chunk` (Task 1), `get_settings()`.
- Produces:
  - `upload_chunks(chunks: list[Chunk]) -> int` — `chunk_type`에 따라 narrative/table 인덱스로 분기하여 `SearchClient.upload_documents`로 upsert. 각 문서는 벡터 포함(`content_vector`는 반드시 채워져 있어야 함). 반환: 업로드한 총 문서 수.
  - 문서 dict 키는 인덱스 필드명과 일치. `None` 값 필드는 제외.

- [ ] **Step 1: upload_chunks 추가**

Add to `ingest/indexer.py` (imports 상단에 추가): `from azure.search.documents import SearchClient`, `from ingest.models import Chunk`.

Append:
```python
def _chunk_to_doc(chunk: Chunk) -> dict:
    doc = {
        "id": chunk.id,
        "content": chunk.content,
        "content_vector": chunk.content_vector,
        "doc_id": chunk.doc_id,
        "chunk_type": chunk.chunk_type,
        "section_path": chunk.section_path,
        "page_physical": chunk.page_physical,
    }
    for k in ("year", "fund_name", "page_printed"):
        v = getattr(chunk, k)
        if v is not None:
            doc[k] = v
    return doc


def upload_chunks(chunks: list[Chunk]) -> int:
    s = get_settings()
    cred = DefaultAzureCredential()
    buckets: dict[str, list[dict]] = {s.search_index_narrative: [], s.search_index_table: []}
    for c in chunks:
        if c.content_vector is None:
            raise ValueError(f"chunk {c.id} has no embedding")
        target = s.search_index_table if c.chunk_type == "table" else s.search_index_narrative
        buckets[target].append(_chunk_to_doc(c))
    total = 0
    for index_name, docs in buckets.items():
        if not docs:
            continue
        client = SearchClient(endpoint=s.search_endpoint, index_name=index_name, credential=cred)
        for i in range(0, len(docs), 1000):
            client.upload_documents(documents=docs[i : i + 1000])
        total += len(docs)
    return total
```

- [ ] **Step 2: 실제 upsert 왕복 검증**

Run:
```bash
uv run python -c "
from ingest.indexer import ensure_indexes, upload_chunks
from ingest.embedder import embed_texts
from ingest.models import Chunk
ensure_indexes()
vecs = embed_texts(['탁월 등급은 매우 높은 성과', '표 데이터 샘플'])
chunks = [
  Chunk(id='t-n1', doc_id='t', content='탁월 등급은 매우 높은 성과', chunk_type='narrative', section_path='S', page_physical=1, content_vector=vecs[0]),
  Chunk(id='t-t1', doc_id='t', content='| 등급 | 내용 |', chunk_type='table', section_path='S', page_physical=1, content_vector=vecs[1]),
]
print('uploaded:', upload_chunks(chunks))
"
```
Expected: `uploaded: 2`. (실 Search 적재; 다음 태스크의 검색 테스트가 이 문서를 사용)

- [ ] **Step 3: Commit**

```bash
git add ingest/indexer.py
git commit -m "feat(ingest): add chunk upsert routing to narrative/table indexes

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 7: 하이브리드 검색 헬퍼 (search/hybrid.py)

**Files:**
- Create: `search/__init__.py`, `search/hybrid.py`, `tests/search/__init__.py`, `tests/search/test_hybrid.py`

**Interfaces:**
- Consumes: `get_settings()`, `DefaultAzureCredential`, `ingest.embedder.embed_texts`.
- Produces:
  - `SearchHit(id: str, content: str, section_path: str, page_physical: int, score: float, chunk_type: str)` (pydantic)
  - `hybrid_search(index_name: str, query: str, top: int = 5) -> list[SearchHit]` — 쿼리 임베딩 1회 계산 → `SearchClient.search(search_text=query, vector_queries=[VectorizedQuery(...)], query_type="semantic", semantic_configuration_name="sem", top=top)`. BM25(search_text) + 벡터 + 시맨틱 재정렬을 결합.

- [ ] **Step 1: 실패하는 통합 테스트 작성**

Create `tests/search/__init__.py` (empty), then `tests/search/test_hybrid.py`:
```python
from config.settings import get_settings
from search.hybrid import hybrid_search


def test_hybrid_search_narrative_returns_relevant_hit():
    s = get_settings()
    hits = hybrid_search(s.search_index_narrative, "탁월 등급의 의미", top=5)
    assert hits, "expected at least one hit"
    assert any("탁월" in h.content for h in hits)
    assert all(h.score >= 0 for h in hits)


def test_hybrid_search_table_index():
    s = get_settings()
    hits = hybrid_search(s.search_index_table, "등급 내용 표", top=5)
    assert hits
    assert hits[0].chunk_type == "table"
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/search/test_hybrid.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'search.hybrid'`

- [ ] **Step 3: hybrid 구현**

Create `search/__init__.py` (empty). Create `search/hybrid.py`:
```python
from __future__ import annotations

from azure.identity import DefaultAzureCredential
from azure.search.documents import SearchClient
from azure.search.documents.models import VectorizedQuery
from pydantic import BaseModel

from config.settings import get_settings
from ingest.embedder import embed_texts


class SearchHit(BaseModel):
    id: str
    content: str
    section_path: str
    page_physical: int
    score: float
    chunk_type: str


def hybrid_search(index_name: str, query: str, top: int = 5) -> list[SearchHit]:
    s = get_settings()
    vector = embed_texts([query])[0]
    client = SearchClient(
        endpoint=s.search_endpoint, index_name=index_name, credential=DefaultAzureCredential()
    )
    results = client.search(
        search_text=query,
        vector_queries=[
            VectorizedQuery(vector=vector, k_nearest_neighbors=top, fields="content_vector")
        ],
        query_type="semantic",
        semantic_configuration_name="sem",
        top=top,
    )
    hits: list[SearchHit] = []
    for r in results:
        hits.append(
            SearchHit(
                id=r["id"],
                content=r["content"],
                section_path=r.get("section_path", ""),
                page_physical=r.get("page_physical", 0),
                score=r["@search.score"],
                chunk_type=r.get("chunk_type", ""),
            )
        )
    return hits
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/search/test_hybrid.py -v`
Expected: PASS (2 passed). Task 6에서 적재한 문서가 검색됨. 실패 시 인덱스 반영 지연 가능 → 5~10초 후 재시도.

- [ ] **Step 5: Commit**

```bash
git add search/ tests/search/
git commit -m "feat(search): add hybrid (vector+BM25+semantic) search helper

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 8: 인제스트 CLI + 실제 전체 문서 적재 (ingest/run.py)

**Files:**
- Create: `ingest/run.py`
- Modify: `README.md` (인제스트 사용법 추가)

**Interfaces:**
- Consumes: `analyze_pdf`, `chunk_document`, `embed_texts`, `ensure_indexes`, `upload_chunks`.
- Produces:
  - CLI: `python -m ingest.run --pdf <path> --doc-id <id> [--pages RANGE] [--no-cache]`
  - 흐름: ensure_indexes → analyze_pdf(캐시) → chunk_document → embed(청크 content) → content_vector 주입 → upload_chunks → 요약 출력(narrative/table 개수).
  - 반환/출력: 적재 청크 수.

- [ ] **Step 1: run.py 구현**

Create `ingest/run.py`:
```python
from __future__ import annotations

import argparse

from ingest.chunker import chunk_document
from ingest.embedder import embed_texts
from ingest.indexer import ensure_indexes, upload_chunks
from ingest.parser import analyze_pdf


def run(pdf: str, doc_id: str, pages: str | None, use_cache: bool) -> int:
    ensure_indexes()
    doc = analyze_pdf(pdf, doc_id, pages=pages, use_cache=use_cache)
    chunks = chunk_document(doc)
    vectors = embed_texts([c.content for c in chunks])
    for c, v in zip(chunks, vectors):
        c.content_vector = v
    total = upload_chunks(chunks)
    n_table = sum(1 for c in chunks if c.chunk_type == "table")
    print(f"doc_id={doc_id} chunks={total} (narrative={total - n_table}, table={n_table})")
    return total


def main() -> None:
    ap = argparse.ArgumentParser(description="Ingest a PDF into Azure AI Search")
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--doc-id", required=True)
    ap.add_argument("--pages", default=None, help="e.g. '1-100' (DI page range)")
    ap.add_argument("--no-cache", action="store_true")
    args = ap.parse_args()
    run(args.pdf, args.doc_id, args.pages, use_cache=not args.no_cache)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 실제 전체 문서 적재 실행**

Run:
```bash
uv run python -m ingest.run --pdf "Docs/2025회계연도 기금운용평가보고서(자산운용부문).pdf" --doc-id "gicheum-2025-asset"
```
Expected: DI 분석(수 분, 첫 실행)→청킹→임베딩→적재. 출력 예 `doc_id=gicheum-2025-asset chunks=<N> (narrative=..., table=...)`, N은 수백 규모. `.ingest_cache/gicheum-2025-asset.json` 생성. (실 Azure, 과금 발생 — 승인됨)

- [ ] **Step 3: 실제 검색 스모크 (전체 문서 대상)**

Run:
```bash
uv run python -c "
from search.hybrid import hybrid_search
from config.settings import get_settings
s=get_settings()
for q in ['자산운용 평가 등급 기준', '평가의 목적']:
    hits=hybrid_search(s.search_index_narrative, q, top=3)
    print(q, '->', [(round(h.score,3), h.section_path[:30]) for h in hits])
    assert hits
print('OK')
"
```
Expected: 각 질의가 관련 섹션 청크를 반환, `OK`.

- [ ] **Step 4: README 갱신**

Edit `README.md` — under "인프라 배포 (P1)" 아래에 추가:
```markdown
## 문서 인제스트 (P2)
```bash
# PDF를 파싱·청킹·임베딩하여 AI Search 2개 인덱스에 적재
uv run python -m ingest.run --pdf "Docs/<파일>.pdf" --doc-id "<고유ID>"
```
추가 자료는 전달받는 대로 동일 명령을 새 --doc-id로 재실행하면 upsert 됩니다.
```

- [ ] **Step 5: Commit**

```bash
git add ingest/run.py README.md
git commit -m "feat(ingest): add ingest CLI orchestrator and document usage

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Self-Review 결과

- **Spec coverage:** DI 최대활용 파싱(Task 3, roles/tables/markdown), 레이아웃 인지 청킹·표 단일화·section_path·오버랩(Task 2), Foundry 임베딩 3072(Task 4), 2개 하이브리드 인덱스 벡터+BM25+시맨틱(Task 5,7), upsert 라우팅(Task 6), 재실행 CLI(Task 8). V1/V4(표)=table-index, V3(서술)=narrative, V5/다년도 기반 메타데이터(doc_id/section_path/year/fund_name) 마련. 관리형 Knowledge Base 기반 agentic retrieval과 에이전트 오케스트레이션은 P3.
- **Placeholder scan:** 모든 코드/명령 구체화. 청킹 section_path 기대값은 `_heading_depth`와 일치하도록 Step 5에서 조정 지점 명시.
- **Type consistency:** `Chunk` 필드 ↔ `_chunk_to_doc` 키 ↔ 인덱스 필드명(id, content, content_vector, doc_id, chunk_type, section_path, page_physical/printed, year, fund_name) 일치. `embed_texts`/`hybrid_search`/`VectorizedQuery(fields="content_vector")` 차원 3072 = 인덱스 `vector_search_dimensions` 일치. 인덱스명은 `settings.search_index_narrative/table`로 통일.

## 후속 플랜
- **P3**: Microsoft Agent Framework 오케스트레이터 + 도구(다중 인덱스 하이브리드 조회·질문 분해·교차참조·인용) = agentic retrieval 검증. (+ 관리형 Knowledge Base 대안 평가)
- **P4**: Chainlit UI. **P5**: Foundry Evaluation + Golden Q&A.
