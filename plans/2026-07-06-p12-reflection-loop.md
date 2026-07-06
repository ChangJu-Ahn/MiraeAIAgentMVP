# P12: 명시적 Reflection 루프 (자가 점검 → 부족 시 재조회) Implementation Plan

> REQUIRED SUB-SKILL: subagent-driven-development / executing-plans. Steps use checkbox syntax.

**Goal:** 에이전트가 답변한 뒤, **답변이 질문을 충분히·근거 기반으로 커버했는지 자가 점검**하고, 부족하면 부족한 부분을 명시해 **보완 질의로 재조회·재답변**하는 명시적 reflection 루프를 추가한다(최대 2라운드). 스트리밍 UX 유지.

**Architecture:** `agent/reflection.py`에 `ReflectionVerdict(sufficient, missing)`, `critique(question, answer, sources)`(gpt-4o judge로 JSON 판정), `augmented_question(question, missing)`(순수)를 둔다. `app/chat.py`가 라운드 루프: 답변 스트리밍→critique→부족&라운드 남으면 `🔍 보완` step 표시 후 보완 질의로 재스트리밍. 점검은 안정적 gpt-4o(eval 배포) 사용(reasoning judge 비호환 회피). ask/ask_sync·start_stream 불변.

**Tech Stack:** Python 3.12(uv), agent-framework(FoundryChatClient), chainlit, pytest.

## Global Constraints
- Reflection 점검 LLM = gpt-4o(`foundry_eval_deployment`) — JSON 응답, reasoning 아님.
- 최대 2라운드(무한 루프 방지). 충분하면 즉시 종료.
- 스트리밍 유지: 각 라운드 답변은 토큰 스트리밍. 재조회는 부족할 때만(비용 최소).
- 순수 로직(`augmented_question`, JSON 파싱)은 유닛 테스트. critique는 실 통합 스모크.
- ask/ask_sync/start_stream/AnswerResult 시그니처 불변.
- 커밋 트레일러 필수.

## File Structure
- `agent/reflection.py` (신규)
- `app/chat.py` (수정) — 라운드 루프
- `tests/agent/test_reflection.py` (신규)
- `README.md`, `chainlit.md` (수정)

---

## Task 1: reflection 모듈 (critique + augmented_question)

**Files:** Create `agent/reflection.py`, `tests/agent/test_reflection.py`

**Interfaces:**
- `ReflectionVerdict(BaseModel)`: `sufficient: bool`, `missing: str`.
- `augmented_question(question: str, missing: str) -> str` (순수): 원 질문 + "다음 부족한 부분을 반드시 보완해 답하라: {missing}".
- `async def critique(question: str, answer: str, sources: list) -> ReflectionVerdict` — gpt-4o(eval 배포)로 JSON 판정. 파싱 실패 시 `sufficient=True`(안전: 불필요한 재조회 방지).
- `parse_verdict(text: str) -> ReflectionVerdict` (순수): JSON 추출·파싱.

- [ ] **Step 1: 실패 테스트**

Create `tests/agent/test_reflection.py`:
```python
from agent.reflection import ReflectionVerdict, augmented_question, parse_verdict


def test_augmented_question_includes_missing():
    q = augmented_question("탁월 등급이란?", "우수 등급과의 점수 구간 차이")
    assert "탁월 등급이란?" in q
    assert "우수 등급과의 점수 구간 차이" in q


def test_parse_verdict_json():
    v = parse_verdict('{"sufficient": false, "missing": "연도별 수치"}')
    assert v.sufficient is False and "연도별" in v.missing


def test_parse_verdict_embedded_and_fallback():
    v = parse_verdict('점검 결과: {"sufficient": true, "missing": ""} 입니다')
    assert v.sufficient is True
    # 파싱 불가 → 안전하게 sufficient True
    bad = parse_verdict("not json at all")
    assert bad.sufficient is True
```

- [ ] **Step 2: 실패 확인** — `uv run pytest tests/agent/test_reflection.py -v` → FAIL (module 없음)

- [ ] **Step 3: 구현**

Create `agent/reflection.py`:
```python
from __future__ import annotations

import json
import re

from azure.identity import DefaultAzureCredential
from agent_framework.foundry import FoundryChatClient
from pydantic import BaseModel

from config.settings import get_settings


class ReflectionVerdict(BaseModel):
    sufficient: bool
    missing: str = ""


_CRITIQUE_PROMPT = """당신은 답변 품질 점검자입니다. 아래 질문과 답변, 검색 근거를 보고
답변이 질문을 충분히·근거 기반으로 커버했는지 판정하세요.
누락된 하위 질문·수치·근거가 있으면 부족으로 판정하고 무엇이 부족한지 한국어로 구체적으로 쓰세요.
반드시 JSON만 출력: {{"sufficient": true/false, "missing": "부족한 점(없으면 빈 문자열)"}}

[질문]
{question}

[답변]
{answer}

[검색 근거 요약]
{sources}
"""


def augmented_question(question: str, missing: str) -> str:
    return (
        f"{question}\n\n"
        f"[보완 지시] 이전 답변에서 다음이 부족했습니다. 추가로 검색·조회하여 반드시 보완해 답하세요: {missing}"
    )


def parse_verdict(text: str) -> ReflectionVerdict:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return ReflectionVerdict(sufficient=True)
    try:
        data = json.loads(m.group(0))
        return ReflectionVerdict(
            sufficient=bool(data.get("sufficient", True)),
            missing=str(data.get("missing", "")),
        )
    except (ValueError, TypeError):
        return ReflectionVerdict(sufficient=True)


async def critique(question: str, answer: str, sources: list) -> ReflectionVerdict:
    s = get_settings()
    client = FoundryChatClient(
        project_endpoint=s.foundry_project_endpoint,
        model=s.foundry_eval_deployment,
        credential=DefaultAzureCredential(),
    )
    agent = client.as_agent(name="reflection-critic", instructions="You output only JSON.")
    src_summary = "\n".join(f"[출처 {getattr(x,'n','?')}] {getattr(x,'section_path','')}" for x in sources[:10]) or "(없음)"
    prompt = _CRITIQUE_PROMPT.format(question=question, answer=answer, sources=src_summary)
    resp = await agent.run(prompt)
    return parse_verdict(resp.text)
```

- [ ] **Step 4: 통과 확인** — `uv run pytest tests/agent/test_reflection.py -v` → PASS(3)

- [ ] **Step 5: critique 실 스모크**

Run:
```bash
uv run python -c "
import asyncio
from agent.reflection import critique
v = asyncio.run(critique('탁월과 우수 등급의 점수 구간 차이는?', '탁월은 높은 등급입니다.', []))
print('sufficient:', v.sufficient, '| missing:', v.missing[:80])
"
```
Expected: 근거 없고 답이 빈약 → `sufficient=False` + missing에 구체 내용(대개). 오류 없이 판정 반환. (실 gpt-4o)

- [ ] **Step 6: Commit**
```bash
git add agent/reflection.py tests/agent/test_reflection.py
git commit -m "feat(agent): add reflection critique + question augmentation

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 2: UI reflection 루프 (스트리밍 + 재조회)

**Files:** Modify `app/chat.py`, `README.md`, `chainlit.md`

**Interfaces:** on_message이 최대 2라운드: 스트리밍 답변 → critique → 부족&라운드 남으면 `🔍 자가 점검` step + 보완 질의로 재스트리밍. 근거/시각물은 최종 라운드 기준.

- [ ] **Step 1: on_message 리팩터**

Edit `app/chat.py` — reflection import + 루프:
```python
from agent.reflection import augmented_question, critique
```
Replace on_message body with a rounds loop:
```python
@cl.on_message
async def on_message(message: cl.Message) -> None:
    question = message.content
    max_rounds = 2
    final_trace = None
    final_visual = None

    for rnd in range(1, max_rounds + 1):
        stream, trace, visual, process = start_stream(question)
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

        answer_text = ""
        async for update in stream:
            await flush_process()
            if update.text:
                answer_text += update.text
                await answer_msg.stream_token(update.text)
        await flush_process()
        await answer_msg.update()

        final_trace, final_visual = trace, answer_text_holder = trace, visual
        final_answer = answer_text

        # 마지막 라운드거나 점검 통과면 종료
        if rnd == max_rounds:
            break
        verdict = await critique(question, answer_text, trace.sources)
        if verdict.sufficient:
            break
        async with cl.Step(name="🔍 자가 점검: 보완 필요", type="reflection") as s:
            s.output = f"부족한 부분: {verdict.missing}\n→ 보완 질의로 다시 조회합니다."
        question = augmented_question(message.content, verdict.missing)

    # 시각물 (최종 라운드)
    elements = _visual_elements(final_visual.items)
    if elements:
        await cl.Message(content="📊 시각화", elements=elements).send()
    # 근거 — 최종 답변이 인용한 것만
    used = cited_sources(final_answer, final_trace.sources)
    citations = format_citations(used)
    if citations:
        await cl.Message(content=citations).send()
```
(주의: 위 스니펫의 `answer_text_holder` 표기는 오타 방지를 위해 실제 구현 시 `final_visual = visual`, `final_answer = answer_text`로 단순화할 것. nonlocal/클로저는 라운드별 재정의되므로 루프 내 정의 유지.)

*구현 정리 지침:* 라운드 루프에서 `flush_process`를 매 라운드 새로 정의(각 라운드 recorder가 다름). 최종 `final_visual`,`final_answer`,`final_trace`만 루프 밖에서 사용.

- [ ] **Step 2: 임포트/서버 스모크**

Run: `uv run python -c "import app.chat; print('import OK')"`
Run: `uv run chainlit run app/chat.py --headless --port 8775 & CL=$!; sleep 12; curl -sS -o /dev/null -w "HTTP %{http_code}\n" http://localhost:8775/; kill $CL 2>/dev/null || true`
Expected: `import OK`, `HTTP 200`.

- [ ] **Step 3: README/chainlit.md 갱신**

README UI 설명에 추가:
```markdown
> 답변 후 스스로 충분성을 점검(🔍)하고, 부족하면 부족한 부분을 보완 질의로 다시 조회해 답변을 개선합니다(최대 2라운드).
```
chainlit.md "에이전트가 하는 일"에 한 줄 추가(자가 점검·보완 재조회).

- [ ] **Step 4: 회귀 + Commit**

Run: `uv run pytest -q -k "not test_orchestrator and not runner_smoke and not render_and_describe and not build_figure_chunks and not test_streaming"` → PASS.
```bash
git add app/chat.py README.md chainlit.md
git commit -m "feat(app): add explicit reflection loop (self-check → re-query when insufficient)

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Self-Review 결과
- **Spec coverage:** 명시적 reflection(자가 점검→부족 시 보완 재조회, 최대 2R), 스트리밍 유지, 안정적 gpt-4o 점검. 암묵적 재조회(추론 모델) 위에 명시적 게이트 추가.
- **Placeholder scan:** Task 2 스니펫의 클로저/변수 정리 지침 명시(구현 시 단순화).
- **Type consistency:** ReflectionVerdict/critique/augmented_question(Task1) ↔ chat.py(Task2). critique는 eval 배포(gpt-4o) 사용.

## 후속
- reflection 판정 근거를 App Insights 커스텀 이벤트로; 라운드 수/effort 튜닝.
