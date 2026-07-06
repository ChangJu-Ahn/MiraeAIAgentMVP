# P6: 그림 이해 (DI figures → 멀티모달 설명 → RAG 인덱싱) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Azure Document Intelligence가 인식한 그림(figures, 12개)을 추출해 해당 영역을 이미지로 렌더하고, **Microsoft Foundry gpt-4o 멀티모달**로 한국어 설명을 생성하여 `chunk_type="figure"` 청크로 AI Search에 적재한다. 이로써 그림/차트 내용이 RAG 컨텍스트로 검색·인용 가능해진다(현재 갭 해소).

**Architecture:** `ingest/parser.py`가 DI 결과의 `figures`(page·polygon·offset·caption)를 `ParsedDoc.figures`로 정규화한다. `ingest/figures.py`가 그림 영역을 `pdftoppm`+Pillow로 크롭 렌더하고, Foundry gpt-4o(멀티모달, 키리스)로 설명을 생성해 figure 청크를 만든다. `ingest/run.py`가 서술/표 청크에 figure 청크를 합쳐 임베딩·적재한다(figure는 narrative-index로 라우팅). 문서 순서(offset)로 그림의 `section_path`를 부여한다.

**Tech Stack:** Python 3.12(uv), azure-ai-documentintelligence(figures), pdftoppm(poppler), Pillow(크롭), openai(AzureOpenAI 멀티모달, Foundry gpt-4o), azure-identity, P2 임베더/인덱서, pytest.

## Global Constraints

- 그림 설명 생성은 **Microsoft Foundry gpt-4o 멀티모달**(키리스). 파싱은 Document Intelligence. 검색/적재는 AI Search. (스펙 §1, 메모리)
- 키리스: gpt-4o 호출은 `AzureOpenAI(azure_endpoint=<foundry base>, azure_ad_token_provider=get_bearer_token_provider(DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default"), api_version=settings.foundry_api_version)`, `model=settings.foundry_chat_deployment`. API 키 금지.
- figure 청크는 `chunk_type="figure"`, `content` = (캡션 +) 한국어 설명, `section_path`는 문서 위치(offset) 기준, `page_physical`=그림 페이지. figure 청크 id는 `f"{doc_id}-fig-{i}"`(기존 수치 id와 충돌 방지).
- 원문 PDF 경로는 설정값 `source_pdf_path`(config)로 주입. DI 결과는 `.ingest_cache/`(기존) 재사용.
- 검색/임베딩은 P2 모듈(`embed_texts`, `upload_chunks`)만 사용. figure 청크는 narrative-index로 라우팅(기존 else 분기).
- 실제 배포 리소스·실제 Azure 호출 테스트 허용. 재적재로 figure 청크 반영.
- 모든 커밋 끝에 트레일러:
  `Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>`

## 확정된 사실 (검증됨)
- 캐시 DI 결과 `figures` 12개. 각 figure: `boundingRegions[0].pageNumber`, `polygon`(8 float, 단위 inch), `spans[0].offset`, `caption`(대개 None → 설명 필수). 페이지 단위 inch(8.5 x 11.9167).
- gpt-4o 멀티모달·키리스 호출은 P2 임베더/P3와 동일 엔드포인트 규칙으로 동작(검증된 경로).
- Pillow 미설치 → 의존성 추가 필요. pdftoppm 사용 가능.

---

## File Structure

- `ingest/models.py` (수정) — `ParsedFigure(page, polygon, offset, caption)` + `ParsedDoc.figures`
- `ingest/parser.py` (수정) — DI figures → ParsedFigure 정규화
- `ingest/figures.py` (신규) — `render_figure_png`, `describe_figure`, `heading_path_at`, `build_figure_chunks`
- `ingest/run.py` (수정) — figure 청크 병합 + `--no-figures` 플래그
- `config/settings.py` (수정) — `source_pdf_path` 필드
- `tests/ingest/test_figures.py` (신규) — 렌더/설명/청크 (통합)
- `README.md` (수정)

---

## Task 1: 모델 + 파서 figure 캡처

**Files:**
- Modify: `ingest/models.py`, `ingest/parser.py`, `config/settings.py`
- Test: `tests/ingest/test_figures.py` (일부)

**Interfaces:**
- Produces:
  - `ParsedFigure(BaseModel)`: `page: int`, `polygon: list[float]`, `offset: int = 0`, `caption: str | None = None`.
  - `ParsedDoc.figures: list[ParsedFigure] = []` (기존 필드 유지, 하위호환).
  - `parser._result_to_parsed` 가 `data["figures"]`를 ParsedFigure로 채움: page=`_page_of(fig)`, polygon=`fig["boundingRegions"][0]["polygon"]`, offset=`_offset_of(fig)`, caption=`fig.get("caption",{}).get("content")`.
  - `Settings.source_pdf_path: str = "Docs/2025회계연도 기금운용평가보고서(자산운용부문).pdf"`.

- [ ] **Step 1: 실패하는 테스트 작성**

Create `tests/ingest/test_figures.py`:
```python
import json
from pathlib import Path

from ingest.models import ParsedDoc, ParsedFigure
from ingest.parser import _result_to_parsed


def test_parsed_figure_model():
    f = ParsedFigure(page=1, polygon=[0.0, 0.0, 1.0, 0.0, 1.0, 1.0, 0.0, 1.0], offset=10)
    assert f.page == 1 and len(f.polygon) == 8 and f.caption is None


def test_parser_captures_figures_from_cache():
    cache = Path(".ingest_cache/gicheum-2025-asset.json")
    if not cache.exists():
        import pytest
        pytest.skip("DI cache not present")
    data = json.loads(cache.read_text(encoding="utf-8"))
    doc = _result_to_parsed("gicheum-2025-asset", data)
    assert isinstance(doc, ParsedDoc)
    assert len(doc.figures) >= 1
    assert all(len(fig.polygon) >= 8 for fig in doc.figures)
    assert all(fig.page >= 1 for fig in doc.figures)
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/ingest/test_figures.py -v`
Expected: FAIL — `ImportError: cannot import name 'ParsedFigure'`

- [ ] **Step 3: 모델·파서·설정 구현**

Edit `ingest/models.py` — add after `ParsedTable`:
```python
class ParsedFigure(BaseModel):
    page: int
    polygon: list[float]
    offset: int = 0
    caption: str | None = None
```
And add `figures` to `ParsedDoc`:
```python
class ParsedDoc(BaseModel):
    doc_id: str
    markdown: str
    paragraphs: list[ParsedParagraph]
    tables: list[ParsedTable]
    figures: list[ParsedFigure] = []
```

Edit `ingest/parser.py` — import `ParsedFigure`, and in `_result_to_parsed` add figure extraction before the return:
```python
    figures = [
        ParsedFigure(
            page=_page_of(f),
            polygon=((f.get("boundingRegions") or [{}])[0].get("polygon") or []),
            offset=_offset_of(f),
            caption=(f.get("caption") or {}).get("content"),
        )
        for f in data.get("figures", [])
        if (f.get("boundingRegions") or [{}])[0].get("polygon")
    ]
    return ParsedDoc(
        doc_id=doc_id,
        markdown=data.get("content", ""),
        paragraphs=paragraphs,
        tables=tables,
        figures=figures,
    )
```
(`_offset_of` already exists from P2 fix; reuse it.)

Edit `config/settings.py` — add field to `Settings`:
```python
    source_pdf_path: str = "Docs/2025회계연도 기금운용평가보고서(자산운용부문).pdf"
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/ingest/test_figures.py -v`
Expected: PASS (2 passed) — 캐시의 12개 figure 캡처 확인.

- [ ] **Step 5: Commit**

```bash
git add ingest/models.py ingest/parser.py config/settings.py tests/ingest/test_figures.py
git commit -m "feat(ingest): capture DI figures into ParsedDoc

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 2: 그림 렌더 + 멀티모달 설명 (ingest/figures.py)

**Files:**
- Create: `ingest/figures.py`
- Modify: `pyproject.toml` (add Pillow)
- Test: `tests/ingest/test_figures.py` (append)

**Interfaces:**
- Consumes: `pdftoppm`, Pillow, `AzureOpenAI`(Foundry, 키리스), `get_settings`.
- Produces:
  - `render_figure_png(pdf_path: str, page: int, polygon: list[float], dpi: int = 150, pad_in: float = 0.1) -> bytes` — 해당 페이지를 렌더 후 polygon bbox(+여백)로 크롭한 PNG 바이트.
  - `describe_figure(png: bytes) -> str` — Foundry gpt-4o 멀티모달로 한국어 설명(2~4문장).

- [ ] **Step 1: Pillow 추가**

Run: `uv add pillow`
Expected: 설치 성공.

- [ ] **Step 2: figures.py 구현 (렌더·설명)**

Create `ingest/figures.py`:
```python
from __future__ import annotations

import base64
import io
import os
import subprocess
import tempfile

from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from openai import AzureOpenAI
from PIL import Image

from config.settings import get_settings

_SCOPE = "https://cognitiveservices.azure.com/.default"
_PROMPT = (
    "이 그림/차트를 한국어로 2~4문장으로 설명하세요. "
    "제목, 축·범례, 핵심 수치나 추세를 최대한 구체적으로 포함하세요. "
    "그림이 표 형태면 어떤 항목들이 있는지 요약하세요."
)


def render_figure_png(
    pdf_path: str, page: int, polygon: list[float], dpi: int = 150, pad_in: float = 0.1
) -> bytes:
    xs = polygon[0::2]
    ys = polygon[1::2]
    left = max(min(xs) - pad_in, 0.0)
    top = max(min(ys) - pad_in, 0.0)
    right = max(xs) + pad_in
    bottom = max(ys) + pad_in
    with tempfile.TemporaryDirectory() as d:
        prefix = os.path.join(d, "pg")
        subprocess.run(
            ["pdftoppm", "-f", str(page), "-l", str(page), "-r", str(dpi), "-png", pdf_path, prefix],
            check=True,
            capture_output=True,
        )
        pngs = sorted(f for f in os.listdir(d) if f.endswith(".png"))
        img = Image.open(os.path.join(d, pngs[0]))
        box = (int(left * dpi), int(top * dpi), int(right * dpi), int(bottom * dpi))
        crop = img.crop(box)
        buf = io.BytesIO()
        crop.save(buf, format="PNG")
        return buf.getvalue()


def describe_figure(png: bytes) -> str:
    s = get_settings()
    base = s.foundry_project_endpoint.split("/api/projects")[0]
    provider = get_bearer_token_provider(DefaultAzureCredential(), _SCOPE)
    client = AzureOpenAI(
        azure_endpoint=base, api_version=s.foundry_api_version, azure_ad_token_provider=provider
    )
    b64 = base64.b64encode(png).decode()
    resp = client.chat.completions.create(
        model=s.foundry_chat_deployment,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _PROMPT},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                ],
            }
        ],
        max_tokens=400,
    )
    return (resp.choices[0].message.content or "").strip()
```

- [ ] **Step 3: 통합 테스트 append**

Append to `tests/ingest/test_figures.py`:
```python
def test_render_and_describe_first_figure():
    import pytest
    from ingest.parser import analyze_pdf
    from ingest.figures import render_figure_png, describe_figure
    from config.settings import get_settings

    s = get_settings()
    doc = analyze_pdf(s.source_pdf_path, "gicheum-2025-asset", use_cache=True)
    if not doc.figures:
        pytest.skip("no figures")
    fig = doc.figures[0]
    png = render_figure_png(s.source_pdf_path, fig.page, fig.polygon)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"  # PNG magic
    desc = describe_figure(png)
    assert desc and len(desc) > 10
```

- [ ] **Step 4: 통합 테스트 통과 확인**

Run: `uv run pytest tests/ingest/test_figures.py::test_render_and_describe_first_figure -v`
Expected: PASS — 첫 그림을 렌더(PNG 매직바이트)하고 gpt-4o가 한국어 설명 반환. (실 pdftoppm + Foundry, ~10~20초)

- [ ] **Step 5: Commit**

```bash
git add ingest/figures.py pyproject.toml uv.lock tests/ingest/test_figures.py
git commit -m "feat(ingest): render figure crops and describe via Foundry gpt-4o (keyless)

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 3: figure 청크 생성 + 인제스트 통합 + 재적재

**Files:**
- Modify: `ingest/figures.py` (append `heading_path_at`, `build_figure_chunks`), `ingest/run.py`, `README.md`
- Test: `tests/ingest/test_figures.py` (append)

**Interfaces:**
- Consumes: `ParsedDoc`, `Chunk`, `chunker._heading_depth`(재사용), `render_figure_png`, `describe_figure`.
- Produces:
  - `heading_path_at(doc: ParsedDoc, offset: int) -> str` — 문서 순서상 offset 이전 헤딩 스택을 " > "로 결합(청커와 동일 규칙).
  - `build_figure_chunks(doc: ParsedDoc, pdf_path: str) -> list[Chunk]` — 각 figure를 렌더·설명해 `Chunk(chunk_type="figure", id=f"{doc_id}-fig-{i}", content=(캡션+)설명, section_path=heading_path_at, page_physical=fig.page)`.
  - `ingest/run.py`: figure 청크를 합쳐 임베딩·적재. `--no-figures`로 비활성. 요약에 figure 개수 표시.

- [ ] **Step 1: heading_path_at + build_figure_chunks 구현**

Append to `ingest/figures.py`:
```python
from ingest.chunker import HEADING_ROLES, _heading_depth
from ingest.models import Chunk, ParsedDoc


def heading_path_at(doc: ParsedDoc, offset: int) -> str:
    stack: list[str] = []
    for p in sorted(doc.paragraphs, key=lambda x: x.offset if hasattr(x, "offset") else 0):
        p_off = getattr(p, "offset", 0)
        if p_off > offset:
            break
        if p.role in HEADING_ROLES:
            if p.role == "title":
                stack = [p.content]
            else:
                depth = _heading_depth(p.content)
                stack = stack[:depth] + [p.content]
    return " > ".join(stack)


def build_figure_chunks(doc: ParsedDoc, pdf_path: str) -> list[Chunk]:
    chunks: list[Chunk] = []
    for i, fig in enumerate(doc.figures):
        try:
            png = render_figure_png(pdf_path, fig.page, fig.polygon)
            desc = describe_figure(png)
        except Exception as exc:  # noqa: BLE001
            desc = f"(그림 설명 생성 실패: {exc})"
        prefix = f"[그림] {fig.caption}\n" if fig.caption else "[그림] "
        chunks.append(
            Chunk(
                id=f"{doc.doc_id}-fig-{i}",
                doc_id=doc.doc_id,
                content=prefix + desc,
                chunk_type="figure",
                section_path=heading_path_at(doc, fig.offset),
                page_physical=fig.page,
                page_printed=None,
            )
        )
    return chunks
```
**Note:** `ingest/parser.py`의 `ParsedParagraph`는 P2 offset 수정으로 `offset` 필드를 가진다(Task/P2에서 추가됨). 확인 후 사용.

*Prerequisite check:* `ingest/chunker.py`에 `HEADING_ROLES`와 `_heading_depth`가 모듈 수준으로 존재함(P2). import 가능해야 함.

- [ ] **Step 2: run.py 통합**

Edit `ingest/run.py` — update `run()` to include figures:
```python
from ingest.figures import build_figure_chunks


def run(pdf: str, doc_id: str, pages: str | None, use_cache: bool, figures: bool = True) -> int:
    ensure_indexes()
    doc = analyze_pdf(pdf, doc_id, pages=pages, use_cache=use_cache)
    chunks = chunk_document(doc)
    if figures:
        chunks += build_figure_chunks(doc, pdf)
    vectors = embed_texts([c.content for c in chunks])
    for c, v in zip(chunks, vectors):
        c.content_vector = v
    total = upload_chunks(chunks)
    n_table = sum(1 for c in chunks if c.chunk_type == "table")
    n_fig = sum(1 for c in chunks if c.chunk_type == "figure")
    print(
        f"doc_id={doc_id} chunks={total} "
        f"(narrative={total - n_table - n_fig}, table={n_table}, figure={n_fig})"
    )
    return total
```
And in `main()` add the flag + pass it:
```python
    ap.add_argument("--no-figures", action="store_true", help="그림 설명 인덱싱 비활성")
    ...
    run(args.pdf, args.doc_id, args.pages, use_cache=not args.no_cache, figures=not args.no_figures)
```

- [ ] **Step 3: figure 청크 빌드 통합 테스트 (소규모)**

Append to `tests/ingest/test_figures.py`:
```python
def test_build_figure_chunks_subset():
    from ingest.parser import analyze_pdf
    from ingest.figures import build_figure_chunks
    from config.settings import get_settings
    import pytest

    s = get_settings()
    doc = analyze_pdf(s.source_pdf_path, "gicheum-2025-asset", use_cache=True)
    if not doc.figures:
        pytest.skip("no figures")
    # 첫 2개만 빌드해 속도 제한
    doc.figures = doc.figures[:2]
    chunks = build_figure_chunks(doc, s.source_pdf_path)
    assert len(chunks) == 2
    assert all(c.chunk_type == "figure" for c in chunks)
    assert all(c.id.startswith("gicheum-2025-asset-fig-") for c in chunks)
    assert all("[그림]" in c.content for c in chunks)
```

- [ ] **Step 4: 통합 테스트 통과 확인**

Run: `uv run pytest tests/ingest/test_figures.py::test_build_figure_chunks_subset -v`
Expected: PASS — 2개 figure 청크 생성(chunk_type=figure, id·content 규칙). (실 렌더+gpt-4o)

- [ ] **Step 5: 실제 전체 재적재 (그림 포함)**

Run:
```bash
uv run python -m ingest.run --pdf "Docs/2025회계연도 기금운용평가보고서(자산운용부문).pdf" --doc-id "gicheum-2025-asset"
```
Expected: DI 캐시 사용 → 서술/표 + **figure 12개** 청크 임베딩·적재. 출력 예 `... (narrative=606, table=199, figure=12)`. (수 분, 실 Azure)

- [ ] **Step 6: figure 검색 검증**

Run:
```bash
uv run python -c "
from search.hybrid import hybrid_search
from config.settings import get_settings
s=get_settings()
hits=hybrid_search(s.search_index_narrative, '그림에 나타난 수익률 추이', top=5)
figs=[h for h in hits if h.chunk_type=='figure']
print('figure hits:', len(figs))
for h in figs[:2]: print('-', h.section_path[:40], '| p.', h.page_physical, '|', h.content[:80])
assert figs, 'expected at least one figure chunk retrievable'
print('OK')
"
```
Expected: figure 청크가 검색됨(`OK`). 그림 설명이 RAG 컨텍스트로 조회 가능함을 확인.

- [ ] **Step 7: README 갱신 + 회귀**

Edit `README.md` — "문서 인제스트 (P2)" 섹션에 한 줄 추가:
```markdown
> 그림(figures)은 Foundry gpt-4o 멀티모달로 설명을 생성해 함께 인덱싱합니다(`--no-figures`로 비활성).
```

Run: `uv run pytest -q -k "not test_orchestrator and not runner_smoke"`
Expected: 순수/그림 테스트 PASS (느린 e2e 제외).

- [ ] **Step 8: Commit**

```bash
git add ingest/figures.py ingest/run.py README.md tests/ingest/test_figures.py
git commit -m "feat(ingest): index figure descriptions as retrievable chunks

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Self-Review 결과

- **Spec coverage:** DI figures 추출(Task 1), Foundry gpt-4o 멀티모달 설명(Task 2), figure 청크 RAG 인덱싱·재적재·검색 검증(Task 3) → "그림 설명을 RAG 컨텍스트로 추가" 갭 해소. 키리스·설정 주입·P2 모듈 재사용 준수.
- **Placeholder scan:** 코드/명령 구체화. figure 렌더는 pdftoppm+Pillow, 설명은 gpt-4o. build_figure_chunks는 실패 시 방어(설명 실패 문자열).
- **Type consistency:** `ParsedFigure`/`ParsedDoc.figures`(Task 1) ↔ `build_figure_chunks`/`heading_path_at`(Task 3) ↔ `Chunk`(P2) 일치. figure 청크는 `chunk_type="figure"` → `upload_chunks` else 분기로 narrative-index 적재(P2와 정합). offset 필드는 P2에서 ParsedParagraph/기타에 추가됨(재사용).

## 후속
- **P7**: 답변 시각화 UI(make_table/make_chart/show_source_page + Chainlit 바인딩) — 이제 그림 설명이 컨텍스트에 있어 이미지/그림 관련 질의가 근거를 가진다.
- figure 청크에 대한 별도 인덱스/필터(선택), 그림 영역 크롭 정밀도 향상(폴리곤 정확 크롭).
