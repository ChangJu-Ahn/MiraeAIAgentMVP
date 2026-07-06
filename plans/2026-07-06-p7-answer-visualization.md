# P7: 답변 시각화 (표·차트·이미지) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 에이전트가 필요 시 시각화 도구(make_table/make_chart/show_source_page)를 호출해 구조화된 시각 페이로드를 반환하고, Chainlit UI가 이를 `cl.Dataframe`(표)·`cl.Plotly`(차트)·`cl.Image`(원문 페이지)로 바인딩해 답변과 함께 렌더한다.

**Architecture:** `agent/visuals.py`가 시각물 모델(TableVisual/ChartVisual/ImageVisual)과 `VisualRecorder`, `make_visual_tools(recorder)`(3개 도구 클로저)를 제공한다. 도구는 LLM이 호출하면 구조화된 Visual을 recorder에 기록한다(P3 TraceRecorder와 동일 패턴). `agent/orchestrator.py`는 검색 도구 + 시각화 도구를 함께 에이전트에 주고, `AnswerResult`에 `visuals`를 추가해 반환한다. `app/chat.py`는 `result.visuals`를 순회하며 Chainlit 요소로 바인딩한다. 순수 변환(Visual→pandas/plotly figure)은 `app/visual_bind.py`로 분리해 유닛 테스트한다.

**Tech Stack:** Python 3.12(uv), agent-framework(FoundryChatClient as_agent tools), chainlit(cl.Dataframe/Plotly/Image), plotly, pandas, pdftoppm+Pillow(원문 페이지 렌더, P6 재사용), pytest.

## Global Constraints

- 에이전트/LLM은 Microsoft Foundry + Agent Framework(P3). UI는 Chainlit(P4). 검색/그림 렌더는 P2/P6 모듈 재사용. (스펙 §1,§5, 메모리)
- 시각화 도구는 **일반 파이썬 함수**로 as_agent(tools=...)에 전달(P3 방식). LLM 인자는 단순 타입/JSON 문자열.
- 시각물은 `VisualRecorder`에 기록하고 `AnswerResult.visuals: list[Visual]`로 반환(관측/바인딩). ask()는 요청마다 새 recorder(누수 방지).
- 원문 페이지 이미지는 P6 `ingest.figures.render_page_png` 계열 방식(pdftoppm) 사용, PDF 경로는 `settings.source_pdf_path`. 키리스 유지(이미지 렌더는 로컬).
- 차트/표 데이터는 에이전트가 검색 결과에서 추출해 도구 인자로 전달(RAG 근거 기반). 허구 금지 원칙은 P3 시스템 프롬프트 유지.
- plotly 의존성 추가. pandas·Pillow·pdftoppm은 이미 존재.
- 실제 Azure 호출 테스트 허용. UI 서버 부팅 스모크로 검증.
- 모든 커밋 끝에 트레일러:
  `Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>`

## 확정된 API (검증됨)
- Chainlit 2.11.1: `cl.Dataframe`, `cl.Plotly`, `cl.Image` 요소 존재. 요소는 `cl.Message(content=..., elements=[...])`로 첨부.
- P3: `client.as_agent(tools=[callables])`; `AnswerResult(answer, steps, sources)` — 여기에 `visuals` 추가.
- P6: `ingest/figures.py`에 pdftoppm 렌더 로직 존재(페이지 렌더 함수 추가/재사용).

---

## File Structure

- `agent/visuals.py` — `TableVisual`/`ChartVisual`/`ImageVisual`/`Visual`, `VisualRecorder`, `make_visual_tools(recorder)`
- `agent/orchestrator.py` (수정) — 시각화 도구 결합, `AnswerResult.visuals`, 시스템 프롬프트 보강
- `app/visual_bind.py` — `table_to_dataframe(v)`, `chart_to_figure(v)` (순수 변환)
- `app/chat.py` (수정) — visuals → cl.Dataframe/Plotly/Image 바인딩
- `ingest/figures.py` (수정) — `render_page_png(pdf_path, page)` 페이지 전체 렌더(원문 이미지)
- `config/settings.py` (이미 source_pdf_path 있음)
- `tests/agent/test_visuals.py` — 도구/모델 (순수)
- `tests/app/test_visual_bind.py` — 변환 (순수, plotly/pandas)
- `README.md` (수정)

---

## Task 1: 시각물 모델 + 시각화 도구 (agent/visuals.py)

**Files:**
- Create: `agent/visuals.py`, `tests/agent/test_visuals.py`
- Modify: `ingest/figures.py` (add `render_page_png`)

**Interfaces:**
- Produces:
  - `TableVisual(kind="table", title: str, columns: list[str], rows: list[list[str]])`
  - `ChartVisual(kind="chart", title: str, chart_kind: str, x_label: str, y_label: str, x: list[str], series: list[dict])` — series item: `{"name": str, "y": list[float]}`.
  - `ImageVisual(kind="image", title: str, path: str)`
  - `Visual = TableVisual | ChartVisual | ImageVisual` (Union).
  - `VisualRecorder(BaseModel)`: `items: list[Visual]`; `.reset()`.
  - `make_visual_tools(recorder) -> list[Callable]` — `make_table`, `make_chart`, `show_source_page` (모두 docstring/타입힌트). 인자는 JSON 문자열로 받아 파싱(LLM 친화). 성공 시 recorder.items에 append하고 사람이 읽을 확인 문자열 반환.

- [ ] **Step 1: render_page_png 추가 (ingest/figures.py)**

Add to `ingest/figures.py`:
```python
def render_page_png(pdf_path: str, page: int, dpi: int = 130) -> bytes:
    import io
    import os
    import subprocess
    import tempfile

    from PIL import Image

    with tempfile.TemporaryDirectory() as d:
        prefix = os.path.join(d, "pg")
        subprocess.run(
            ["pdftoppm", "-f", str(page), "-l", str(page), "-r", str(dpi), "-png", pdf_path, prefix],
            check=True,
            capture_output=True,
        )
        pngs = sorted(f for f in os.listdir(d) if f.endswith(".png"))
        img = Image.open(os.path.join(d, pngs[0]))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
```

- [ ] **Step 2: 실패하는 테스트 작성**

Create `tests/agent/test_visuals.py`:
```python
import json

from agent.visuals import ChartVisual, TableVisual, VisualRecorder, make_visual_tools


def test_make_table_records_table_visual():
    rec = VisualRecorder()
    make_table, _chart, _page = make_visual_tools(rec)
    out = make_table(
        title="등급 분포",
        columns_json=json.dumps(["등급", "개수"], ensure_ascii=False),
        rows_json=json.dumps([["탁월", "3"], ["우수", "5"]], ensure_ascii=False),
    )
    assert "등급 분포" in out
    assert len(rec.items) == 1
    v = rec.items[0]
    assert isinstance(v, TableVisual)
    assert v.columns == ["등급", "개수"]
    assert v.rows[0] == ["탁월", "3"]


def test_make_chart_records_chart_visual():
    rec = VisualRecorder()
    _table, make_chart, _page = make_visual_tools(rec)
    make_chart(
        title="등급 추세",
        chart_kind="line",
        x_label="연도",
        y_label="점수",
        x_json=json.dumps(["2023", "2024", "2025"]),
        series_json=json.dumps([{"name": "국민연금", "y": [80.0, 82.5, 85.0]}], ensure_ascii=False),
    )
    assert len(rec.items) == 1
    v = rec.items[0]
    assert isinstance(v, ChartVisual)
    assert v.chart_kind == "line"
    assert v.series[0]["name"] == "국민연금"


def test_reset_clears_items():
    rec = VisualRecorder()
    make_table, _c, _p = make_visual_tools(rec)
    make_table(title="t", columns_json="[\"a\"]", rows_json="[[\"1\"]]")
    rec.reset()
    assert rec.items == []
```

- [ ] **Step 3: 테스트 실패 확인**

Run: `uv run pytest tests/agent/test_visuals.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent.visuals'`

- [ ] **Step 4: visuals 구현**

Create `agent/visuals.py`:
```python
from __future__ import annotations

import json
from typing import Callable, Literal, Union

from pydantic import BaseModel

from config.settings import get_settings


class TableVisual(BaseModel):
    kind: Literal["table"] = "table"
    title: str
    columns: list[str]
    rows: list[list[str]]


class ChartVisual(BaseModel):
    kind: Literal["chart"] = "chart"
    title: str
    chart_kind: str  # "line" | "bar"
    x_label: str
    y_label: str
    x: list[str]
    series: list[dict]  # {"name": str, "y": list[float]}


class ImageVisual(BaseModel):
    kind: Literal["image"] = "image"
    title: str
    path: str


Visual = Union[TableVisual, ChartVisual, ImageVisual]


class VisualRecorder(BaseModel):
    items: list[Visual] = []

    def reset(self) -> None:
        self.items.clear()


def make_visual_tools(recorder: VisualRecorder) -> list[Callable[..., str]]:
    settings = get_settings()

    def make_table(title: str, columns_json: str, rows_json: str) -> str:
        """표(정형 데이터)를 사용자 화면에 표시합니다. 검색으로 확인한 실제 값만 사용하세요.

        Args:
            title: 표 제목.
            columns_json: 열 이름 배열의 JSON 문자열. 예: '["등급","개수"]'
            rows_json: 행 배열의 JSON 문자열(각 행은 문자열 배열). 예: '[["탁월","3"],["우수","5"]]'
        """
        columns = json.loads(columns_json)
        rows = json.loads(rows_json)
        recorder.items.append(TableVisual(title=title, columns=columns, rows=rows))
        return f"표 '{title}' 표시함 ({len(rows)}행)"

    def make_chart(
        title: str, chart_kind: str, x_label: str, y_label: str, x_json: str, series_json: str
    ) -> str:
        """차트(추세/비교)를 사용자 화면에 표시합니다. 검색으로 확인한 실제 수치만 사용하세요.

        Args:
            title: 차트 제목.
            chart_kind: 'line' 또는 'bar'.
            x_label: x축 이름.
            y_label: y축 이름.
            x_json: x축 값 배열의 JSON 문자열. 예: '["2023","2024","2025"]'
            series_json: 시리즈 배열의 JSON 문자열. 각 항목 {"name":str,"y":[숫자...]}.
        """
        x = json.loads(x_json)
        series = json.loads(series_json)
        recorder.items.append(
            ChartVisual(
                title=title,
                chart_kind=chart_kind if chart_kind in ("line", "bar") else "bar",
                x_label=x_label,
                y_label=y_label,
                x=x,
                series=series,
            )
        )
        return f"차트 '{title}' 표시함"

    def show_source_page(page: int) -> str:
        """인용 근거의 원문 PDF 페이지를 이미지로 사용자에게 보여줍니다.

        Args:
            page: 표시할 물리 페이지 번호(검색 결과의 page 값).
        """
        recorder.items.append(
            ImageVisual(title=f"원문 {page}페이지", path=f"__page__:{page}")
        )
        return f"원문 {page}페이지 이미지 표시함"

    return [make_table, make_chart, show_source_page]
```
*Note:* `show_source_page`는 실제 렌더를 UI 바인딩 시점에 수행하도록 `path`에 `__page__:<n>` 마커만 기록(도구 실행 중 파일 IO 회피, 렌더는 chat.py에서). `settings`는 향후 확장 위해 확보.

- [ ] **Step 5: 테스트 통과 확인**

Run: `uv run pytest tests/agent/test_visuals.py -v`
Expected: PASS (3 passed)

- [ ] **Step 6: Commit**

```bash
git add agent/visuals.py ingest/figures.py tests/agent/test_visuals.py
git commit -m "feat(agent): add visualization tools (table/chart/source-page) with recorder

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 2: 오케스트레이터 통합 (agent/orchestrator.py)

**Files:**
- Modify: `agent/orchestrator.py`
- Test: `tests/agent/test_orchestrator.py` (append visuals-aware assertion)

**Interfaces:**
- Consumes: `agent.visuals.VisualRecorder`, `make_visual_tools`.
- Produces:
  - `AnswerResult`에 `visuals: list[Visual] = []` 추가.
  - `build_agent(recorder, visual_recorder)` — 검색 도구 + 시각화 도구를 함께 tools로.
  - `ask()`는 두 recorder(trace, visual) 생성 → agent 실행 → `AnswerResult(answer, steps, sources, visuals)`.
  - `SYSTEM_PROMPT` 보강: "수치·등급 분포는 make_table로 표를, 연도별·기금별 추세/비교는 make_chart로 차트를, 원문 표/그림 확인이 필요하면 show_source_page로 원문 페이지를 함께 제시하라. 시각물의 데이터는 반드시 검색으로 확인한 실제 값만 사용하고, 없으면 만들지 마라."

- [ ] **Step 1: orchestrator 수정**

Edit `agent/orchestrator.py`:
- import: `from agent.visuals import Visual, VisualRecorder, make_visual_tools`
- `AnswerResult`에 필드 추가: `visuals: list[Visual] = []`
- `SYSTEM_PROMPT` 끝에 시각화 지침 문단 추가(위 문구).
- `build_agent`:
```python
def build_agent(recorder: TraceRecorder, visual_recorder: VisualRecorder):
    settings = get_settings()
    client = FoundryChatClient(
        project_endpoint=settings.foundry_project_endpoint,
        model=settings.foundry_chat_deployment,
        credential=DefaultAzureCredential(),
    )
    tools = make_search_tools(recorder) + make_visual_tools(visual_recorder)
    return client.as_agent(name="mirae-fund-agent", instructions=SYSTEM_PROMPT, tools=tools)
```
- `ask`:
```python
async def ask(question: str) -> AnswerResult:
    recorder = TraceRecorder()
    visual_recorder = VisualRecorder()
    agent = build_agent(recorder, visual_recorder)
    response = await agent.run(question)
    return AnswerResult(
        answer=response.text,
        steps=recorder.steps,
        sources=recorder.sources,
        visuals=visual_recorder.items,
    )
```

- [ ] **Step 2: 실제 e2e (시각물 유도 질문)**

Run:
```bash
uv run python -c "
from agent.orchestrator import ask_sync
r = ask_sync('군인연금기금 종합등급 관련 수치를 표로 정리해서 보여줘.')
print('answer head:', r.answer[:200])
print('visuals:', [(v.kind, v.title) for v in r.visuals])
print('steps:', [s.tool for s in r.steps])
"
```
Expected: 답변 + `visuals`에 최소 1개(table 등) 기록되거나, 최소한 오류 없이 동작. (실 Foundry; 모델이 시각화 도구를 호출하면 visuals 채워짐. 도구 사용은 모델 판단이므로 없을 수도 있음 — 그 경우 프롬프트를 조정하거나 더 명시적 질문 사용.)

- [ ] **Step 3: 회귀 테스트(기존 e2e가 visuals 필드로 깨지지 않는지)**

Run: `uv run pytest tests/agent/test_orchestrator.py -v`
Expected: PASS (2 passed) — `AnswerResult`에 visuals 기본값이 있어 기존 테스트 영향 없음.

- [ ] **Step 4: Commit**

```bash
git add agent/orchestrator.py
git commit -m "feat(agent): wire visualization tools into orchestrator and AnswerResult

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 3: 순수 변환 + Chainlit 바인딩 (app/visual_bind.py, app/chat.py)

**Files:**
- Create: `app/visual_bind.py`, `tests/app/test_visual_bind.py`
- Modify: `app/chat.py`, `README.md`

**Interfaces:**
- Consumes: `agent.visuals`(TableVisual/ChartVisual/ImageVisual), pandas, plotly, `ingest.figures.render_page_png`, `settings.source_pdf_path`.
- Produces:
  - `table_to_dataframe(v: TableVisual) -> pandas.DataFrame` (순수).
  - `chart_to_figure(v: ChartVisual) -> plotly.graph_objects.Figure` (순수; line/bar).
  - `app/chat.py`: `result.visuals`를 순회해 cl.Dataframe/cl.Plotly/cl.Image 요소를 만들어 메시지에 첨부. ImageVisual path가 `__page__:<n>`이면 `render_page_png`로 PNG 렌더 후 임시 파일로 cl.Image.

- [ ] **Step 1: plotly 추가**

Run: `uv add plotly`
Expected: 설치 성공.

- [ ] **Step 2: 실패하는 테스트 작성**

Create `tests/app/test_visual_bind.py`:
```python
from agent.visuals import ChartVisual, TableVisual
from app.visual_bind import chart_to_figure, table_to_dataframe


def test_table_to_dataframe():
    v = TableVisual(title="t", columns=["등급", "개수"], rows=[["탁월", "3"], ["우수", "5"]])
    df = table_to_dataframe(v)
    assert list(df.columns) == ["등급", "개수"]
    assert df.shape == (2, 2)
    assert df.iloc[0, 0] == "탁월"


def test_chart_to_figure_line():
    v = ChartVisual(
        title="추세", chart_kind="line", x_label="연도", y_label="점수",
        x=["2023", "2024", "2025"], series=[{"name": "국민연금", "y": [80.0, 82.5, 85.0]}],
    )
    fig = chart_to_figure(v)
    assert fig.layout.title.text == "추세"
    assert len(fig.data) == 1
    assert list(fig.data[0].y) == [80.0, 82.5, 85.0]


def test_chart_to_figure_bar():
    v = ChartVisual(
        title="비교", chart_kind="bar", x_label="기금", y_label="점수",
        x=["A", "B"], series=[{"name": "점수", "y": [70.0, 90.0]}],
    )
    fig = chart_to_figure(v)
    assert len(fig.data) == 1
```

- [ ] **Step 3: 테스트 실패 확인**

Run: `uv run pytest tests/app/test_visual_bind.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.visual_bind'`

- [ ] **Step 4: visual_bind 구현**

Create `app/visual_bind.py`:
```python
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from agent.visuals import ChartVisual, TableVisual


def table_to_dataframe(v: TableVisual) -> pd.DataFrame:
    return pd.DataFrame(v.rows, columns=v.columns)


def chart_to_figure(v: ChartVisual) -> go.Figure:
    fig = go.Figure()
    for s in v.series:
        name = s.get("name", "")
        y = s.get("y", [])
        if v.chart_kind == "bar":
            fig.add_trace(go.Bar(name=name, x=v.x, y=y))
        else:
            fig.add_trace(go.Scatter(name=name, x=v.x, y=y, mode="lines+markers"))
    fig.update_layout(title=v.title, xaxis_title=v.x_label, yaxis_title=v.y_label)
    return fig
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `uv run pytest tests/app/test_visual_bind.py -v`
Expected: PASS (3 passed)

- [ ] **Step 6: chat.py 바인딩 수정**

Edit `app/chat.py` — after sending the answer message, bind visuals. Replace the citations block region with visuals + citations:
```python
import tempfile

from agent.visuals import ChartVisual, ImageVisual, TableVisual
from app.visual_bind import chart_to_figure, table_to_dataframe
from config.settings import get_settings
from ingest.figures import render_page_png
```
And in `on_message`, after `await cl.Message(content=result.answer).send()`:
```python
    # 시각물 바인딩
    elements = []
    for v in result.visuals:
        if isinstance(v, TableVisual):
            elements.append(cl.Dataframe(data=table_to_dataframe(v), name=v.title, display="inline"))
        elif isinstance(v, ChartVisual):
            elements.append(cl.Plotly(figure=chart_to_figure(v), name=v.title, display="inline"))
        elif isinstance(v, ImageVisual):
            path = v.path
            if path.startswith("__page__:"):
                page = int(path.split(":", 1)[1])
                png = render_page_png(get_settings().source_pdf_path, page)
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
                tmp.write(png)
                tmp.close()
                path = tmp.name
            elements.append(cl.Image(path=path, name=v.title, display="inline"))
    if elements:
        await cl.Message(content="📊 시각화", elements=elements).send()
```
(Keep the existing citations block after this.)

- [ ] **Step 7: 임포트/서버 부팅 스모크**

Run:
```bash
uv run python -c "import app.chat; print('import OK')"
```
Expected: `import OK`.

Run:
```bash
uv run chainlit run app/chat.py --headless --port 8770 &
CL_PID=$!; sleep 12
curl -sS -o /dev/null -w "HTTP %{http_code}\n" http://localhost:8770/
kill $CL_PID 2>/dev/null || true
```
Expected: `HTTP 200`.

- [ ] **Step 8: README 갱신 + 회귀**

Edit `README.md` — "웹 UI 데모 (P4)" 설명에 한 줄 추가:
```markdown
> 답변에 표(정형 데이터)·차트(추세/비교)·원문 페이지 이미지가 필요하면 에이전트가 자동으로 함께 표시합니다.
```

Run: `uv run pytest -q -k "not test_orchestrator and not runner_smoke and not render_and_describe and not build_figure_chunks"`
Expected: 순수 테스트(visuals/visual_bind 포함) PASS.

- [ ] **Step 9: Commit**

```bash
git add app/visual_bind.py app/chat.py tests/app/test_visual_bind.py README.md pyproject.toml uv.lock
git commit -m "feat(app): bind agent visuals to Chainlit table/chart/image elements

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Self-Review 결과

- **Spec coverage:** 표(cl.Dataframe)·차트(cl.Plotly)·이미지(cl.Image, 원문 페이지) 시각화(스펙 §5, V6.2). viz_tools 방식(에이전트가 도구로 시각물 방출 → UI 바인딩). 근거 기반 데이터 원칙 유지.
- **Placeholder scan:** 코드/명령 구체화. 이미지 렌더는 바인딩 시점 지연(도구는 마커만 기록). e2e에서 모델의 도구 사용은 비결정적이므로 Task 2 Step 2에 조정 여지 명시.
- **Type consistency:** `TableVisual/ChartVisual/ImageVisual`(Task 1) ↔ `AnswerResult.visuals`(Task 2) ↔ `table_to_dataframe/chart_to_figure`/chat.py 바인딩(Task 3) 일치. 도구는 as_agent(tools=검색+시각화). `render_page_png`(P6 파일에 추가).

## 후속
- 시각물 라이브 스트리밍/도구 호출 실시간 표시, 차트 자동 유형 추론 고도화, 이미지 폴리곤 정밀 크롭.
- 표 데이터 정확도(V1) ground-truth 대조 테스트(선택).
