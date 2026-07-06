# P4: Chainlit 챗봇 UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 고객 시연용 Chainlit 웹 UI를 구현하여, P3 에이전트에 질문하면 **추론 단계(도구 호출)를 단계별로 표시**하고, 답변(마크다운 표 포함)과 **근거 출처 카드**를 함께 렌더한다.

**Architecture:** `app/formatting.py`가 추론 단계·근거를 마크다운으로 변환하는 순수 함수(유닛 테스트 대상)를 제공한다. `app/chat.py`가 Chainlit 핸들러(`on_chat_start`, `on_message`)로 `agent.orchestrator.ask()`(async)를 호출하고, 기록된 추론 단계를 `cl.Step`으로, 답변을 `cl.Message`(마크다운 표 네이티브 렌더)로, 근거를 별도 메시지로 표시한다. 로직은 순수 함수로 분리해 테스트하고 핸들러는 얇게 유지한다.

**Tech Stack:** Python 3.12(uv), chainlit 2.11.1, P3 `agent.orchestrator.ask`, pytest.

## Global Constraints

- UI는 Chainlit(오픈소스). 에이전트 호출은 P3 `agent.orchestrator.ask`만 사용(재구현 금지). (스펙 §5)
- 관측 가능한 추론: 각 도구 호출을 `cl.Step`으로 표시. 근거 인용(section_path+page)을 출처 카드로 표시. (스펙 §1, §5)
- 답변 내 표는 마크다운으로 렌더(Chainlit 네이티브). 차트(plotly)는 본 플랜 범위 외(후속). (스펙 §5 — 표는 포함, 차트는 후속)
- 설정/시크릿은 `.env`(기존). `.chainlit/`·`.files/`는 gitignore(기존 P1). 키리스 유지.
- 실제 배포 리소스 사용, 실제 Azure 호출 스모크 허용.
- 모든 커밋 끝에 트레일러:
  `Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>`

## 확정된 Chainlit API (검증됨, 2.11.1)
- `@cl.on_chat_start`, `@cl.on_message` 데코레이터.
- `cl.Message(content=str)` → `await .send()`; `.stream_token()`, `.update()`.
- `cl.Step(name=str, type=str)` = async 컨텍스트 매니저: `async with cl.Step(...) as s: s.input=...; s.output=...`.
- `cl.Text` 엘리먼트 존재.
- 실행: `uv run chainlit run app/chat.py --headless --port <p>` (헤드리스, 브라우저 미실행). HTTP 200 서빙.

---

## File Structure

- `app/__init__.py`
- `app/formatting.py` — `format_reasoning_step(step)`, `format_citations(sources)` (순수 함수)
- `app/chat.py` — Chainlit 핸들러 (on_chat_start, on_message)
- `chainlit.md` — 한국어 환영 메시지
- `tests/app/__init__.py`
- `tests/app/test_formatting.py` — 순수 포맷 함수 유닛 테스트
- `README.md` (수정: UI 실행법)

---

## Task 1: 포맷 순수 함수 (app/formatting.py)

**Files:**
- Create: `app/__init__.py`, `app/formatting.py`, `tests/app/__init__.py`, `tests/app/test_formatting.py`

**Interfaces:**
- Consumes: `agent.tools.TraceStep`, `agent.tools.RetrievedSource`.
- Produces:
  - `format_reasoning_step(step: TraceStep) -> str` — 예: `search_narrative("탁월 등급") → 5건 검색`.
  - `format_citations(sources: list[RetrievedSource]) -> str` — 마크다운 근거 목록(`### 근거` 헤더 + `- [출처 N] (index) section_path · p.page`); 빈 목록이면 `""`.

- [ ] **Step 1: 실패하는 테스트 작성**

Create `tests/app/__init__.py` (empty), then `tests/app/test_formatting.py`:
```python
from agent.tools import RetrievedSource, TraceStep
from app.formatting import format_citations, format_reasoning_step


def test_format_reasoning_step():
    step = TraceStep(tool="search_narrative", query="탁월 등급", n_hits=5)
    out = format_reasoning_step(step)
    assert "search_narrative" in out
    assert "탁월 등급" in out
    assert "5" in out


def test_format_citations_lists_sources():
    sources = [
        RetrievedSource(
            n=1, index="narrative-index", section_path="Ⅱ > 1 > 가",
            page_physical=24, chunk_type="narrative", snippet="...",
        ),
        RetrievedSource(
            n=2, index="table-index", section_path="03. 방송통신발전기금 > 2. 기금현황",
            page_physical=89, chunk_type="table", snippet="...",
        ),
    ]
    out = format_citations(sources)
    assert "### 근거" in out
    assert "[출처 1]" in out and "[출처 2]" in out
    assert "p.24" in out
    assert "03. 방송통신발전기금" in out


def test_format_citations_empty():
    assert format_citations([]) == ""
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/app/test_formatting.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.formatting'` (또는 'app')

- [ ] **Step 3: formatting 구현**

Create `app/__init__.py` (empty). Create `app/formatting.py`:
```python
from __future__ import annotations

from agent.tools import RetrievedSource, TraceStep


def format_reasoning_step(step: TraceStep) -> str:
    return f'{step.tool}("{step.query}") → {step.n_hits}건 검색'


def format_citations(sources: list[RetrievedSource]) -> str:
    if not sources:
        return ""
    lines = ["### 근거"]
    for s in sources:
        lines.append(f"- **[출처 {s.n}]** ({s.index}) {s.section_path} · p.{s.page_physical}")
    return "\n".join(lines)
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/app/test_formatting.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add app/__init__.py app/formatting.py tests/app/__init__.py tests/app/test_formatting.py
git commit -m "feat(app): add reasoning-step and citation formatting helpers

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 2: Chainlit 앱 (app/chat.py) + 환영 + 서버 부팅 스모크

**Files:**
- Create: `app/chat.py`, `chainlit.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: `agent.orchestrator.ask` (async), `app.formatting`.
- Produces:
  - Chainlit 핸들러: `on_chat_start`(환영), `on_message`(질문 처리: 추론 단계 `cl.Step` 표시 → 답변 메시지 → 근거 메시지).

- [ ] **Step 1: chat.py 구현**

Create `app/chat.py`:
```python
from __future__ import annotations

import chainlit as cl

from agent.orchestrator import ask
from app.formatting import format_citations


@cl.on_chat_start
async def on_chat_start() -> None:
    await cl.Message(
        content="안녕하세요! 기금운용평가보고서 기반 AI 어시스턴트입니다. 질문을 입력해 주세요."
    ).send()


@cl.on_message
async def on_message(message: cl.Message) -> None:
    result = await ask(message.content)

    # 관측 가능한 추론: 각 도구 호출을 단계로 표시
    for step in result.steps:
        async with cl.Step(name=step.tool, type="tool") as s:
            s.input = step.query
            s.output = f"{step.n_hits}건 검색"

    # 답변 (마크다운 표 네이티브 렌더)
    await cl.Message(content=result.answer).send()

    # 근거 출처 카드
    citations = format_citations(result.sources)
    if citations:
        await cl.Message(content=citations).send()
```

- [ ] **Step 2: chainlit.md 환영 메시지**

Create `chainlit.md`:
```markdown
# 기금운용평가보고서 AI 어시스턴트

기금운용평가보고서(한글 PDF)를 기반으로 질문에 답하는 Agentic RAG 챗봇 데모입니다.

- 질문을 분해해 서술/표 인덱스를 조회합니다(agentic retrieval).
- 답변에는 근거 출처(섹션·페이지)를 함께 제시합니다.
- 자료에 없는 내용은 답변을 거부합니다.

예시 질문:
- 자산운용 평가의 목적은 무엇인가요?
- 탁월 등급과 우수 등급의 차이는?
```

- [ ] **Step 3: 임포트 스모크**

Run: `uv run python -c "import app.chat; print('import OK')"`
Expected: `import OK` (Chainlit 데코레이터 등록 성공, 임포트 에러 없음).

- [ ] **Step 4: 서버 부팅 스모크 (실제 기동)**

Run:
```bash
uv run chainlit run app/chat.py --headless --port 8765 &
CL_PID=$!
sleep 12
CODE=$(curl -sS -o /dev/null -w "%{http_code}" http://localhost:8765/)
echo "HTTP $CODE"
kill $CL_PID 2>/dev/null
test "$CODE" = "200" && echo "SERVER OK"
```
Expected: `HTTP 200` 그리고 `SERVER OK`. (서버가 정상 기동·서빙됨을 확인. 종료는 kill로 정리.)

- [ ] **Step 5: README 갱신**

Edit `README.md` — "에이전트 질의 (P3)" 아래에 추가:
```markdown
## 웹 UI 데모 (P4)
```bash
uv run chainlit run app/chat.py -w
```
브라우저에서 챗봇에 질문하면 추론 단계(도구 호출)·답변·근거 출처가 표시됩니다.
```

- [ ] **Step 6: 전체 테스트 회귀 확인**

Run: `uv run pytest -q`
Expected: 기존 + app 포맷 테스트 모두 PASS (에이전트 e2e 포함).

- [ ] **Step 7: Commit**

```bash
git add app/chat.py chainlit.md README.md
git commit -m "feat(app): add Chainlit UI with reasoning steps and citations

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Self-Review 결과

- **Spec coverage:** Chainlit UI(Task 2), 추론 단계 표시(cl.Step, Task 2), 근거 출처 카드(format_citations, Task 1·2), 답변 마크다운 표 네이티브 렌더(Task 2). 에이전트 호출은 P3 ask()만 사용. 차트(plotly) 자동 생성은 범위 외로 명시(후속).
- **Placeholder scan:** 코드/명령 구체화. 서버 스모크는 실제 기동+curl 200으로 검증.
- **Type consistency:** `format_reasoning_step`/`format_citations`(Task 1) ↔ `TraceStep`/`RetrievedSource`(P3 agent.tools) ↔ chat.py 사용 일치. `ask()`는 `AnswerResult(answer, steps, sources)` 반환(P3 계약).

## 후속 플랜
- **P5**: Foundry Evaluation(agent_framework.foundry.FoundryEvals / evaluate_foundry_target) + Golden Q&A(6유형 20~30문항, AI 초안).
- UI 향상(후속): 답변 토큰 스트리밍, 도구 호출 라이브 표시, plotly 차트 자동 생성, FoundryChatClient 재사용/동시성.
