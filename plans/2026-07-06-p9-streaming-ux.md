# P9: 실시간 스트리밍 UX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Chainlit 챗봇이 응답을 완료까지 기다렸다 한 번에 렌더하지 않고, **도구 호출(추론 단계)을 진행되는 대로 라이브 표시**하고 **답변을 토큰 단위로 스트리밍**하도록 개선한다. 시각물·근거는 스트리밍 완료 후 이어서 렌더한다.

**Architecture:** `agent/orchestrator.py`에 스트리밍 진입점 `start_stream(question) -> (ResponseStream, TraceRecorder, VisualRecorder)`를 추가한다(기존 `ask`/`ask_sync`는 CLI·평가·테스트용으로 유지). `app/chat.py`의 `on_message`가 스트림을 async 반복하며, `TraceRecorder.steps`가 늘어나는 대로 `cl.Step`을 방출하고 `update.text`를 `cl.Message.stream_token`으로 흘린다. 스트림 종료 후 `VisualRecorder.items`·`TraceRecorder.sources`로 시각물·근거를 렌더한다.

**Tech Stack:** Python 3.12(uv), agent-framework(run(stream=True) → ResponseStream, update.text 델타), chainlit(Message.stream_token, Step), pytest.

## Global Constraints

- 스트리밍은 UI 경로에만 도입. `ask`/`ask_sync`(P3)와 그 반환 `AnswerResult`는 **변경하지 않음**(P5 평가·P3 테스트 보호).
- 도구 콜(근거 검색·시각화)은 스트림 중 recorder에 기록됨 → 단계는 recorder 증가를 감지해 방출.
- 시각물/근거 렌더 로직은 P7/P4 재사용(`_visual_elements`, `format_citations`).
- 관측성(P8)은 그대로 유지(진입점 setup 유지).
- 커밋 트레일러: `Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>`

## 확정된 API (검증됨)
- `stream = agent.run(question, stream=True)` → `ResponseStream`(async-iterable). `async for update in stream: update.text`(토큰 델타, 실측 91개 점진 도착).
- 도구 호출 시 `TraceRecorder.steps`/`VisualRecorder.items`가 스트림 진행 중 채워짐(실측: search_narrative 기록됨).
- `cl.Message(content="")` + `await msg.stream_token(tok)` + `await msg.update()`; `cl.Step` async 컨텍스트.

---

## File Structure
- `agent/orchestrator.py` (수정) — `start_stream()` 추가
- `app/chat.py` (수정) — 스트리밍 `on_message`
- `tests/agent/test_streaming.py` (신규) — 실 스트리밍 통합(텍스트 누적 + 단계 기록)
- `README.md` (수정)

---

## Task 1: 오케스트레이터 스트리밍 진입점

**Files:**
- Modify: `agent/orchestrator.py`
- Test: `tests/agent/test_streaming.py`

**Interfaces:**
- Produces: `start_stream(question: str) -> tuple[ResponseStream, TraceRecorder, VisualRecorder]` — 새 recorder들로 에이전트를 만들고 `agent.run(question, stream=True)` 스트림과 recorder를 반환(반복은 호출자가 수행).

- [ ] **Step 1: start_stream 구현**

Edit `agent/orchestrator.py` — add (keep `ask`/`ask_sync` unchanged):
```python
def start_stream(question: str):
    """Return (response_stream, trace_recorder, visual_recorder) for live UIs.

    Caller iterates the stream (async) for text deltas; recorders fill with
    tool-call steps, retrieved sources, and visuals during iteration.
    """
    recorder = TraceRecorder()
    visual_recorder = VisualRecorder()
    agent = build_agent(recorder, visual_recorder)
    stream = agent.run(question, stream=True)
    return stream, recorder, visual_recorder
```

- [ ] **Step 2: 실 스트리밍 통합 테스트 작성**

Create `tests/agent/test_streaming.py`:
```python
import asyncio


def test_start_stream_streams_text_and_records_steps():
    from agent.orchestrator import start_stream

    async def run():
        stream, trace, _visual = start_stream("자산운용 평가의 목적은?")
        chunks = 0
        text = ""
        async for update in stream:
            if update.text:
                chunks += 1
                text += update.text
        return chunks, text, trace

    chunks, text, trace = asyncio.run(run())
    assert chunks >= 2, "expected incremental token deltas (streaming)"
    assert text.strip()
    assert trace.steps, "expected at least one tool-call step recorded during stream"


if __name__ == "__main__":
    pass
```

- [ ] **Step 3: 통합 테스트 통과 확인**

Run: `uv run pytest tests/agent/test_streaming.py -v`
Expected: PASS (실 Foundry; 토큰 델타 2개↑ 누적, 단계 기록). ~15~25초.

- [ ] **Step 4: Commit**

```bash
git add agent/orchestrator.py tests/agent/test_streaming.py
git commit -m "feat(agent): add streaming entrypoint start_stream for live UI

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 2: Chainlit 스트리밍 on_message

**Files:**
- Modify: `app/chat.py`, `README.md`

**Interfaces:**
- Consumes: `start_stream`, `format_reasoning_step`, `format_citations`, `_visual_elements`.
- Produces: 라이브 단계 + 토큰 스트리밍 + 후속 시각물/근거.

- [ ] **Step 1: on_message 스트리밍으로 교체**

Edit `app/chat.py` — replace `on_message` body (keep imports; add `start_stream`):
```python
from agent.orchestrator import start_stream
```
```python
@cl.on_message
async def on_message(message: cl.Message) -> None:
    stream, trace, visual = start_stream(message.content)

    answer_msg = cl.Message(content="")
    shown_steps = 0

    async def flush_steps() -> None:
        nonlocal shown_steps
        while shown_steps < len(trace.steps):
            st = trace.steps[shown_steps]
            async with cl.Step(name=st.tool, type="tool") as s:
                s.input = st.query
                s.output = format_reasoning_step(st)
            shown_steps += 1

    async for update in stream:
        await flush_steps()  # 도구 호출을 진행되는 대로 표시
        if update.text:
            await answer_msg.stream_token(update.text)
    await flush_steps()
    await answer_msg.update()

    # 시각물 (표/차트/원문 이미지)
    elements = _visual_elements(visual.items)
    if elements:
        await cl.Message(content="📊 시각화", elements=elements).send()

    # 근거 출처
    citations = format_citations(trace.sources)
    if citations:
        await cl.Message(content=citations).send()
```
(기존 non-streaming 블록 제거. `ask` import는 더 이상 필요 없으면 제거하되, 다른 곳에서 안 쓰면 정리.)

- [ ] **Step 2: 임포트 스모크**

Run: `uv run python -c "import app.chat; print('import OK')"`
Expected: `import OK`

- [ ] **Step 3: 서버 부팅 스모크**

Run:
```bash
uv run chainlit run app/chat.py --headless --port 8771 &
CL=$!; sleep 12; curl -sS -o /dev/null -w "HTTP %{http_code}\n" http://localhost:8771/; kill $CL 2>/dev/null || true
```
Expected: `HTTP 200`.

- [ ] **Step 4: README 갱신 + 회귀**

Edit `README.md` — "웹 UI 데모 (P4)" 설명에 추가:
```markdown
> 답변은 토큰 단위로 스트리밍되며, 도구 호출(추론 단계)이 진행되는 대로 실시간 표시됩니다.
```

Run: `uv run pytest -q -k "not test_orchestrator and not runner_smoke and not render_and_describe and not build_figure_chunks and not test_streaming"`
Expected: 순수/기타 테스트 PASS(느린 실 e2e 제외).

- [ ] **Step 5: Commit**

```bash
git add app/chat.py README.md
git commit -m "feat(app): stream answer tokens and show tool steps live in Chainlit

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Self-Review 결과
- **Spec coverage:** 실시간 스트리밍(토큰) + 라이브 추론 단계(도구 호출) — 사용자 요청. 시각물/근거는 스트림 후 렌더. `ask`/`ask_sync`·평가·관측성 불변.
- **Placeholder scan:** 코드/명령 구체화. 스트리밍은 실 Foundry 통합 테스트로 검증.
- **Type consistency:** `start_stream` 반환(ResponseStream, TraceRecorder, VisualRecorder) ↔ chat.py 사용 일치. 단계/시각물/근거는 recorder 필드 사용(P3/P7과 동일).

## 후속
- 스트리밍 중 도구 단계를 "진행 중" 상태로 표시(현재는 완료 단계로 방출), 답변 스트리밍과 병행한 부분 시각물 프리뷰.
