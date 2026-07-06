# P10: 미들웨어 기반 사고/계획 가시화 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development 또는 executing-plans. Steps use checkbox syntax.

**Goal:** Microsoft Agent Framework 미들웨어로 에이전트의 처리 과정을 캡처한다 — `FunctionMiddleware`로 **모든 툴 호출(입력=근거 질의, 출력=결과)**을, `ChatMiddleware`로 **모델 턴의 계획/의도 텍스트**를 잡아 UI에 "🧠 계획"·"🔧 도구" 단계로 실시간 표시한다. 프롬프트로 계획 서술을 유도한다.

**Architecture:** `agent/middleware.py`에 `ProcessRecorder`(순서 있는 이벤트 목록)와 두 미들웨어(`ToolProcessMiddleware(FunctionMiddleware)`, `PlanningChatMiddleware(ChatMiddleware)`)를 둔다. `build_agent(..., process_recorder=None)`가 recorder가 있으면 `as_agent(middleware=[...])`로 주입한다. `start_stream()`(UI 경로)이 process_recorder를 생성·반환한다. `ask`/`ask_sync`는 미들웨어 없이 그대로(불변). UI는 스트림 진행 중 ProcessRecorder 이벤트를 순서대로 step으로 방출한다. 기존 TraceRecorder는 근거(sources)용으로 유지.

**Tech Stack:** Python 3.12(uv), agent-framework(FunctionMiddleware/ChatMiddleware, as_agent(middleware=...)), chainlit, pytest.

## Global Constraints
- `ask`/`ask_sync`/`AnswerResult`/`build_agent` 기존 시그니처 호환(옵션 인자로 확장) — P3 테스트·P5 평가 보호.
- FunctionMiddleware: `context.function.name`, `context.arguments`, (call_next 후) `context.result`.
- ChatMiddleware: 스트리밍 모드에선 `context.result`가 스트림일 수 있으므로 **스트림을 소비하지 않도록** 안전 가드(읽을 수 있는 텍스트일 때만 계획 이벤트 기록).
- 프롬프트 유도: "도구 호출 전 한 문장으로 무엇을 왜 찾을지 밝혀라".
- 근거(sources)는 기존 TraceRecorder 유지. 커밋 트레일러 필수.

## 확정된 API (검증됨)
- `class X(FunctionMiddleware): async def process(self, context, call_next): ...; await call_next()` — `context.function.name`/`arguments`/`result`.
- `class Y(ChatMiddleware): async def process(self, context, call_next): ...` — `context.messages`/`result`.
- `client.as_agent(..., middleware=[...])`.

---

## File Structure
- `agent/middleware.py` (신규) — ProcessRecorder, ProcessEvent, ToolProcessMiddleware, PlanningChatMiddleware
- `agent/orchestrator.py` (수정) — build_agent(process_recorder=None), start_stream 반환에 process 추가, 프롬프트 유도
- `app/chat.py` (수정) — process 이벤트를 step으로 라이브 표시
- `tests/agent/test_middleware.py` (신규) — 미들웨어 recorder 단위 테스트 + 실 스트리밍에서 tool 이벤트 캡처
- `README.md` (수정)

---

## Task 1: 미들웨어 + recorder (agent/middleware.py)

**Files:** Create `agent/middleware.py`, `tests/agent/test_middleware.py`

**Interfaces:**
- `ProcessEvent(BaseModel)`: `kind: str`("plan"|"tool"), `title: str`, `detail: str`.
- `ProcessRecorder(BaseModel)`: `events: list[ProcessEvent]`; `.reset()`.
- `ToolProcessMiddleware(FunctionMiddleware)`: process에서 call_next 후 `ProcessEvent(kind="tool", title=function.name, detail=f"{arguments} → {result 요약}")` 기록.
- `PlanningChatMiddleware(ChatMiddleware)`: call_next 후 `context.result`가 안전히 읽을 수 있는 텍스트(예: ChatResponse.text, 스트림 아님)일 때만 `ProcessEvent(kind="plan", ...)` 기록(스트림이면 skip).

- [ ] **Step 1: 실패 테스트 작성**

Create `tests/agent/test_middleware.py`:
```python
import asyncio


def test_process_recorder_basic():
    from agent.middleware import ProcessEvent, ProcessRecorder

    rec = ProcessRecorder()
    rec.events.append(ProcessEvent(kind="plan", title="계획", detail="x"))
    assert rec.events[0].kind == "plan"
    rec.reset()
    assert rec.events == []


def test_tool_middleware_records_tool_event():
    from agent.middleware import ProcessRecorder, ToolProcessMiddleware

    rec = ProcessRecorder()
    mw = ToolProcessMiddleware(rec)

    class _Fn:
        name = "search_narrative"

    class _Ctx:
        function = _Fn()
        arguments = {"query": "탁월"}
        result = "결과 텍스트"

    async def call_next():
        return None

    asyncio.run(mw.process(_Ctx(), call_next))
    assert rec.events and rec.events[-1].kind == "tool"
    assert rec.events[-1].title == "search_narrative"
    assert "탁월" in rec.events[-1].detail
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/agent/test_middleware.py -v`
Expected: FAIL (ModuleNotFoundError agent.middleware)

- [ ] **Step 3: 구현**

Create `agent/middleware.py`:
```python
from __future__ import annotations

from agent_framework import ChatMiddleware, FunctionMiddleware
from pydantic import BaseModel


class ProcessEvent(BaseModel):
    kind: str  # "plan" | "tool"
    title: str
    detail: str


class ProcessRecorder(BaseModel):
    events: list[ProcessEvent] = []

    def reset(self) -> None:
        self.events.clear()


class ToolProcessMiddleware(FunctionMiddleware):
    def __init__(self, recorder: ProcessRecorder) -> None:
        self._recorder = recorder

    async def process(self, context, call_next) -> None:  # noqa: ANN001
        name = getattr(getattr(context, "function", None), "name", "tool")
        args = getattr(context, "arguments", None)
        await call_next()
        result = getattr(context, "result", "")
        result_str = str(result)
        if len(result_str) > 200:
            result_str = result_str[:200] + "…"
        self._recorder.events.append(
            ProcessEvent(kind="tool", title=str(name), detail=f"{args} → {result_str}")
        )


class PlanningChatMiddleware(ChatMiddleware):
    def __init__(self, recorder: ProcessRecorder) -> None:
        self._recorder = recorder

    async def process(self, context, call_next) -> None:  # noqa: ANN001
        await call_next()
        result = getattr(context, "result", None)
        # 스트림은 건드리지 않는다(소비 방지). 텍스트를 안전히 읽을 수 있을 때만 기록.
        text = getattr(result, "text", None) if result is not None else None
        if isinstance(text, str) and text.strip():
            snippet = text.strip()
            if len(snippet) > 200:
                snippet = snippet[:200] + "…"
            self._recorder.events.append(
                ProcessEvent(kind="plan", title="계획/사고", detail=snippet)
            )
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/agent/test_middleware.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**
```bash
git add agent/middleware.py tests/agent/test_middleware.py
git commit -m "feat(agent): add process middleware (tool + planning) recorder

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 2: 오케스트레이터 통합 + 프롬프트 유도 + 경험적 검증

**Files:** Modify `agent/orchestrator.py`

**Interfaces:**
- `build_agent(recorder, visual_recorder, process_recorder=None)` — process_recorder가 있으면 `middleware=[ToolProcessMiddleware(pr), PlanningChatMiddleware(pr)]` 주입.
- `start_stream(question) -> (stream, trace, visual, process)` — process_recorder 추가 생성·반환.
- SYSTEM_PROMPT에 계획 유도 문장 추가.

- [ ] **Step 1: 수정**

Edit `agent/orchestrator.py`:
- import: `from agent.middleware import ProcessRecorder, PlanningChatMiddleware, ToolProcessMiddleware`
- SYSTEM_PROMPT 원칙에 추가: "0. 도구를 호출하기 전에 한 문장으로 무엇을 왜 조회할지 계획을 밝히세요."
- `build_agent`:
```python
def build_agent(recorder, visual_recorder, process_recorder=None):
    settings = get_settings()
    client = FoundryChatClient(
        project_endpoint=settings.foundry_project_endpoint,
        model=settings.foundry_chat_deployment,
        credential=DefaultAzureCredential(),
    )
    tools = make_search_tools(recorder) + make_visual_tools(visual_recorder)
    middleware = None
    if process_recorder is not None:
        middleware = [ToolProcessMiddleware(process_recorder), PlanningChatMiddleware(process_recorder)]
    return client.as_agent(
        name="mirae-fund-agent", instructions=SYSTEM_PROMPT, tools=tools, middleware=middleware
    )
```
- `start_stream`:
```python
def start_stream(question: str):
    recorder = TraceRecorder()
    visual_recorder = VisualRecorder()
    process_recorder = ProcessRecorder()
    agent = build_agent(recorder, visual_recorder, process_recorder)
    stream = agent.run(question, stream=True)
    return stream, recorder, visual_recorder, process_recorder
```
(`ask`는 build_agent(recorder, visual_recorder) 호출 그대로 — process 미주입.)

- [ ] **Step 2: 경험적 검증 (실 스트리밍에서 무엇이 캡처되나)**

Run:
```bash
uv run python -c "
import asyncio
from agent.orchestrator import start_stream
async def run():
    stream, tr, vr, pr = start_stream('국민연금기금 상대수익률을 표로 보여줘')
    async for u in stream:
        pass
    return pr
pr = asyncio.run(run())
for e in pr.events: print(e.kind, '|', e.title, '|', e.detail[:80])
print('tool events:', sum(1 for e in pr.events if e.kind=='tool'))
print('plan events:', sum(1 for e in pr.events if e.kind=='plan'))
"
```
Expected: tool 이벤트 ≥1 (툴 입력·결과). plan 이벤트는 0 이상(모델/스트리밍에 따라). **tool 캡처가 핵심 성공 기준.** plan이 0이면 그대로 수용(프롬프트 유도로 답변 앞 계획이 인라인 스트리밍됨) — 문서화.

- [ ] **Step 3: 회귀 (ask/평가 불변 확인)**

Run: `uv run pytest tests/agent/test_orchestrator.py tests/agent/test_streaming.py -v`
Expected: PASS (start_stream 4-튜플 변경 반영은 Task 3 UI에서; 스트리밍 테스트는 3-튜플 언팩이므로 **테스트도 갱신 필요** → 아래).

수정: `tests/agent/test_streaming.py`의 언팩을 4-튜플로:
```python
stream, trace, _visual, _process = start_stream("자산운용 평가의 목적은?")
```

Run again: `uv run pytest tests/agent/test_streaming.py -v` → PASS.

- [ ] **Step 4: Commit**
```bash
git add agent/orchestrator.py tests/agent/test_streaming.py
git commit -m "feat(agent): wire process middleware into streaming path + planning prompt

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 3: UI에 계획/도구 과정 라이브 표시

**Files:** Modify `app/chat.py`, `README.md`

**Interfaces:** on_message가 `start_stream`의 4번째 반환(process_recorder)을 받아, 스트림 진행 중 `process.events`를 순서대로 step으로 방출. (기존 trace.steps 표시는 process 이벤트로 대체하거나 병행 — 중복 방지 위해 process 이벤트를 단일 소스로 사용, 근거는 trace.sources 유지.)

- [ ] **Step 1: on_message 수정**

Edit `app/chat.py`:
- `stream, trace, visual, process = start_stream(message.content)`
- 단계 방출을 `process.events` 기반으로:
```python
    answer_msg = cl.Message(content="")
    shown = 0

    async def flush_process() -> None:
        nonlocal shown
        while shown < len(process.events):
            e = process.events[shown]
            icon = "🧠" if e.kind == "plan" else "🔧"
            async with cl.Step(name=f"{icon} {e.title}", type=e.kind) as s:
                s.output = e.detail
            shown += 1

    async for update in stream:
        await flush_process()
        if update.text:
            await answer_msg.stream_token(update.text)
    await flush_process()
    await answer_msg.update()
```
- 시각물/근거 블록은 그대로(visual.items, trace.sources). `format_reasoning_step` import는 미사용 시 제거.

- [ ] **Step 2: 임포트 + 서버 부팅 스모크**

Run: `uv run python -c "import app.chat; print('import OK')"`
Run: `uv run chainlit run app/chat.py --headless --port 8772 & CL=$!; sleep 12; curl -sS -o /dev/null -w "HTTP %{http_code}\n" http://localhost:8772/; kill $CL 2>/dev/null || true`
Expected: `import OK`, `HTTP 200`.

- [ ] **Step 3: README + 회귀**

Edit `README.md` — UI 설명에 추가:
```markdown
> 에이전트의 계획(🧠)과 도구 실행(🔧, 입력·결과)이 처리되는 대로 단계로 표시됩니다(MAF 미들웨어).
```
Run: `uv run pytest -q -k "not test_orchestrator and not runner_smoke and not render_and_describe and not build_figure_chunks and not test_streaming"`
Expected: PASS.

- [ ] **Step 4: Commit**
```bash
git add app/chat.py README.md
git commit -m "feat(app): display agent planning and tool process steps live via middleware

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Self-Review 결과
- **Spec coverage:** MAF 미들웨어로 툴 과정(FunctionMiddleware)·계획(ChatMiddleware) 캡처 + 프롬프트 유도 + UI 라이브 표시. ask/평가/관측성 불변. sources는 TraceRecorder 유지.
- **Placeholder scan:** ChatMiddleware의 스트리밍 계획 캡처는 경험적 검증(Task 2 Step 2)으로 확정; plan 0이어도 수용·문서화.
- **Type consistency:** ProcessEvent/ProcessRecorder(Task1) ↔ build_agent/start_stream(Task2, 4-튜플) ↔ chat.py(Task3) 일치. start_stream 4-튜플 변경에 맞춰 test_streaming 언팩 갱신.

## 후속
- plan 이벤트가 부족하면 전용 `plan` 도구(강제 계획) 추가 옵션.
