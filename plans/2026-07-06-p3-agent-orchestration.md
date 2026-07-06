# P3: 에이전트 오케스트레이션 (Microsoft Agent Framework) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Microsoft Agent Framework(GA)로 Microsoft Foundry LLM 기반 오케스트레이터 에이전트를 구성하여, 질문을 분해하고 P2의 하이브리드 검색을 도구로 **여러 인덱스(narrative/table)에 다중 조회**하며, 근거를 인용해 답변하고 근거가 없으면 거부(할루시네이션 방어)하는 agentic retrieval을 구현한다. 각 도구 호출(생각 절차)과 근거를 추적해 반환한다.

**Architecture:** `agent/tools.py`가 `TraceRecorder`에 바인딩된 검색 도구 클로저(`search_narrative`, `search_tables`)를 만든다 — 도구는 `search.hybrid.hybrid_search`를 호출하고, 호출 단계와 검색된 출처를 recorder에 기록하며, 인용 가능한 문자열을 반환한다. `agent/orchestrator.py`가 `FoundryChatClient.as_agent(instructions=SYSTEM_PROMPT, tools=[...])`로 에이전트를 만들고 `ask()`(async)/`ask_sync()`로 (답변, 단계, 출처)를 반환한다. `agent/ask.py` CLI가 답변·추론 단계·인용을 출력한다. 관리형 미들웨어 대신 recorder 클로저로 단계를 완전 제어(P4 UI에서 재사용).

**Tech Stack:** Python 3.12(uv), agent-framework 1.10.0 (agent_framework.foundry.FoundryChatClient), azure-identity, P2 모듈(search.hybrid), pydantic, pytest, asyncio.

## Global Constraints

- LLM/오케스트레이션은 반드시 **Microsoft Foundry**(FoundryChatClient) + **Microsoft Agent Framework**. (스펙 §1, 메모리)
- 키리스: `DefaultAzureCredential`. FoundryChatClient는 `project_endpoint=settings.foundry_project_endpoint`, `model=settings.foundry_chat_deployment`, `credential=DefaultAzureCredential()`. (스펙 §1)
- 검색은 P2 `search.hybrid.hybrid_search`만 사용(재구현 금지). 설정은 `config.settings`에서만. (스펙 §2)
- Agentic retrieval = 에이전트가 질문을 분해해 narrative/table 인덱스를 **여러 번** 조회하고 교차참조. (스펙 §3, §4)
- 답변은 **근거 인용**(section_path + page) 포함. 근거 없으면 "제공된 자료에서 확인할 수 없습니다"로 **거부**(할루시네이션 방어). (스펙 §4, V6)
- 각 도구 호출 단계와 출처를 추적해 반환(관측 가능한 추론 → P4 UI). (스펙 §1 목표)
- 실제 배포 리소스 사용, 실제 Azure 호출 테스트 허용. (사용자 방침)
- 모든 커밋 끝에 트레일러:
  `Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>`

## 확정된 Agent Framework API (검증됨, 1.10.0)
- `from agent_framework.foundry import FoundryChatClient`
- `client = FoundryChatClient(project_endpoint=..., model=..., credential=...)` (임포트·생성 검증됨)
- `agent = client.as_agent(instructions=str, tools=[callable, ...], name=str, description=str)` — **도구는 타입힌트+docstring 있는 일반 파이썬 함수**(동기 함수 허용).
- `resp = await agent.run(messages, stream=False)` → `AgentResponse`, 답변은 `resp.text`.
- **검증 지점(실행 중 확인)**: (a) `agent.run`에 질문 문자열을 직접 넘길 수 있는지(`messages="..."`), 아니면 리스트/Message 필요한지; (b) 비동기 실행에서 `DefaultAzureCredential`(동기)로 충분한지, 아니면 `azure.identity.aio.DefaultAzureCredential` 필요한지. 실제 e2e 실행으로 확인하고 필요 시 조정.

---

## File Structure

- `agent/__init__.py`
- `agent/tools.py` — `RetrievedSource`, `TraceStep`, `TraceRecorder`, `make_search_tools(recorder) -> list[callable]`
- `agent/orchestrator.py` — `SYSTEM_PROMPT`, `AnswerResult`, `build_agent(recorder)`, `async ask(question)`, `ask_sync(question)`
- `agent/ask.py` — CLI
- `tests/agent/__init__.py`
- `tests/agent/test_tools.py` — 도구 포맷/기록 (실 Search 통합)
- `tests/agent/test_orchestrator.py` — e2e (실 Foundry+Search): 근거 인용 답변 + 할루시네이션 거부
- `README.md` (수정: 에이전트 사용법)

---

## Task 1: 검색 도구 + 트레이스 (agent/tools.py)

**Files:**
- Create: `agent/__init__.py`, `agent/tools.py`, `tests/agent/__init__.py`, `tests/agent/test_tools.py`

**Interfaces:**
- Consumes: `search.hybrid.hybrid_search`, `config.settings.get_settings`.
- Produces:
  - `RetrievedSource(BaseModel)`: `n: int`, `index: str`, `section_path: str`, `page_physical: int`, `chunk_type: str`, `snippet: str`
  - `TraceStep(BaseModel)`: `tool: str`, `query: str`, `n_hits: int`
  - `TraceRecorder`: `.steps: list[TraceStep]`, `.sources: list[RetrievedSource]`; `.reset()`; 내부적으로 출처 번호(n) 1부터 증가.
  - `make_search_tools(recorder: TraceRecorder) -> list[Callable]` — 두 함수 `search_narrative(query)`, `search_tables(query)`(각각 docstring/타입힌트 포함) 반환. 각 호출은 hybrid_search(top=5) → recorder에 TraceStep과 RetrievedSource 기록 → "[출처 N] (section_path, p.페이지) 내용…" 형식 문자열 반환. 결과 없으면 "검색 결과 없음" 반환.

- [ ] **Step 1: 실패하는 통합 테스트 작성**

Create `tests/agent/__init__.py` (empty), then `tests/agent/test_tools.py`:
```python
from agent.tools import TraceRecorder, make_search_tools


def test_search_narrative_returns_citations_and_records():
    rec = TraceRecorder()
    search_narrative, _search_tables = make_search_tools(rec)
    out = search_narrative("탁월 등급의 의미")
    assert "[출처 1]" in out
    assert rec.steps and rec.steps[0].tool == "search_narrative"
    assert rec.sources and rec.sources[0].section_path is not None


def test_search_tables_records_table_tool():
    rec = TraceRecorder()
    _n, search_tables = make_search_tools(rec)
    out = search_tables("등급 내용 표")
    assert "[출처" in out
    assert rec.steps[-1].tool == "search_tables"
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/agent/test_tools.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent'`

- [ ] **Step 3: tools 구현**

Create `agent/__init__.py` (empty). Create `agent/tools.py`:
```python
from __future__ import annotations

from typing import Callable

from pydantic import BaseModel, Field

from config.settings import get_settings
from search.hybrid import hybrid_search


class RetrievedSource(BaseModel):
    n: int
    index: str
    section_path: str
    page_physical: int
    chunk_type: str
    snippet: str


class TraceStep(BaseModel):
    tool: str
    query: str
    n_hits: int


class TraceRecorder(BaseModel):
    steps: list[TraceStep] = Field(default_factory=list)
    sources: list[RetrievedSource] = Field(default_factory=list)

    def reset(self) -> None:
        self.steps.clear()
        self.sources.clear()


def _run_tool(recorder: TraceRecorder, tool_name: str, index_name: str, query: str, top: int = 5) -> str:
    hits = hybrid_search(index_name, query, top=top)
    recorder.steps.append(TraceStep(tool=tool_name, query=query, n_hits=len(hits)))
    if not hits:
        return "검색 결과 없음"
    lines: list[str] = []
    for h in hits:
        n = len(recorder.sources) + 1
        recorder.sources.append(
            RetrievedSource(
                n=n,
                index=index_name,
                section_path=h.section_path,
                page_physical=h.page_physical,
                chunk_type=h.chunk_type,
                snippet=h.content[:300],
            )
        )
        lines.append(f"[출처 {n}] ({h.section_path}, p.{h.page_physical})\n{h.content[:500]}")
    return "\n\n".join(lines)


def make_search_tools(recorder: TraceRecorder) -> list[Callable[..., str]]:
    settings = get_settings()

    def search_narrative(query: str) -> str:
        """기금운용평가보고서의 서술형 본문(평가 개요·총평·정성 설명 등)에서 검색합니다.

        Args:
            query: 한국어 검색 질의.
        """
        return _run_tool(recorder, "search_narrative", settings.search_index_narrative, query)

    def search_tables(query: str) -> str:
        """기금운용평가보고서의 표(등급·점수·수익률 등 수치/정형 데이터)에서 검색합니다.

        Args:
            query: 한국어 검색 질의.
        """
        return _run_tool(recorder, "search_tables", settings.search_index_table, query)

    return [search_narrative, search_tables]
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/agent/test_tools.py -v`
Expected: PASS (2 passed). 실 Search 대상(P2 적재 데이터 사용).

- [ ] **Step 5: Commit**

```bash
git add agent/__init__.py agent/tools.py tests/agent/__init__.py tests/agent/test_tools.py
git commit -m "feat(agent): add search tools with trace recorder and citations

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 2: 오케스트레이터 에이전트 (agent/orchestrator.py)

**Files:**
- Create: `agent/orchestrator.py`, `tests/agent/test_orchestrator.py`

**Interfaces:**
- Consumes: `agent.tools` (TraceRecorder, make_search_tools), `FoundryChatClient`, `config.settings`.
- Produces:
  - `SYSTEM_PROMPT: str` (한국어: 역할·질문분해·도구선택·다중조회·인용·거부정책).
  - `AnswerResult(BaseModel)`: `answer: str`, `steps: list[TraceStep]`, `sources: list[RetrievedSource]`.
  - `build_agent(recorder: TraceRecorder)` — FoundryChatClient.as_agent(instructions=SYSTEM_PROMPT, tools=make_search_tools(recorder), name="mirae-fund-agent").
  - `async def ask(question: str) -> AnswerResult` — recorder 생성 → agent 실행 → AnswerResult(resp.text, recorder.steps, recorder.sources).
  - `def ask_sync(question: str) -> AnswerResult` — `asyncio.run(ask(question))`.

- [ ] **Step 1: orchestrator 구현**

Create `agent/orchestrator.py`:
```python
from __future__ import annotations

import asyncio

from azure.identity import DefaultAzureCredential
from agent_framework.foundry import FoundryChatClient
from pydantic import BaseModel

from agent.tools import RetrievedSource, TraceRecorder, TraceStep, make_search_tools
from config.settings import get_settings

SYSTEM_PROMPT = """당신은 기금운용평가보고서 전문 분석 어시스턴트입니다.

원칙:
1. 질문을 필요한 하위 질의로 분해하세요.
2. 정성·서술형 정보는 search_narrative, 수치·등급·표 데이터는 search_tables 도구를 사용하세요. 필요하면 두 도구를 여러 번 호출해 교차 확인하세요.
3. 답변에는 반드시 근거를 [출처 N] 형식으로 인용하고, 가능하면 섹션 경로와 페이지를 함께 제시하세요.
4. 검색 결과에 답의 근거가 없으면 지어내지 말고 "제공된 자료에서 확인할 수 없습니다"라고 답하세요.
5. 한국어로 간결하고 정확하게 답변하세요."""


class AnswerResult(BaseModel):
    answer: str
    steps: list[TraceStep]
    sources: list[RetrievedSource]


def build_agent(recorder: TraceRecorder):
    settings = get_settings()
    client = FoundryChatClient(
        project_endpoint=settings.foundry_project_endpoint,
        model=settings.foundry_chat_deployment,
        credential=DefaultAzureCredential(),
    )
    return client.as_agent(
        name="mirae-fund-agent",
        instructions=SYSTEM_PROMPT,
        tools=make_search_tools(recorder),
    )


async def ask(question: str) -> AnswerResult:
    recorder = TraceRecorder()
    agent = build_agent(recorder)
    response = await agent.run(question)
    return AnswerResult(answer=response.text, steps=recorder.steps, sources=recorder.sources)


def ask_sync(question: str) -> AnswerResult:
    return asyncio.run(ask(question))
```

- [ ] **Step 2: 실제 e2e 동작 확인 + (검증 지점 해결)**

Run:
```bash
uv run python -c "
from agent.orchestrator import ask_sync
r = ask_sync('탁월 등급은 어떤 의미인가요?')
print('ANSWER:', r.answer[:400])
print('STEPS:', [(s.tool, s.query) for s in r.steps])
print('SOURCES:', len(r.sources))
assert r.answer and r.steps and r.sources
print('OK')
"
```
Expected: 근거 기반 답변 + 최소 1개 도구 호출(step) + 출처. `OK`.
- 만약 `agent.run(question)`이 문자열 입력을 거부하면, 올바른 입력 형태(예: 메시지 리스트/Message 객체)로 조정. `agent_framework`의 `Message`/`AgentRunInputs` 사용법을 introspect(`help(agent.run)`, `dir(Message)`)하여 최소 변경으로 해결.
- 만약 비동기 실행이 동기 `DefaultAzureCredential`로 인증 오류가 나면 `from azure.identity.aio import DefaultAzureCredential`(aio)로 교체하고 `ask()` 내에서 async 컨텍스트로 사용(필요 시 `async with`), `ask_sync`는 그대로 asyncio.run 유지.
- `response.text`가 답변이 아니면 AgentResponse 구조를 확인(`dir(response)`, `response.to_dict()`)해 올바른 접근자로 조정. 계약(AnswerResult)은 유지.

- [ ] **Step 3: 실패하는 e2e 테스트 작성**

Create `tests/agent/test_orchestrator.py`:
```python
from agent.orchestrator import ask_sync


def test_grounded_answer_cites_and_uses_tools():
    r = ask_sync("자산운용 평가의 목적은 무엇인가요?")
    assert r.answer.strip()
    assert r.steps, "expected at least one tool call (agentic retrieval)"
    assert r.sources, "expected retrieved sources"


def test_hallucination_guard_refuses_unknown():
    r = ask_sync("2025년 애플 아이폰 판매량은 이 보고서에 얼마로 나오나요?")
    assert "확인할 수 없습니다" in r.answer or "없습니다" in r.answer
```

- [ ] **Step 4: e2e 테스트 통과 확인**

Run: `uv run pytest tests/agent/test_orchestrator.py -v`
Expected: PASS (2 passed). 실 Foundry+Search 호출(각 수 초~십수 초). 할루시네이션 방어 테스트는 보고서에 없는 사실을 물어 거부 응답을 확인.

- [ ] **Step 5: Commit**

```bash
git add agent/orchestrator.py tests/agent/test_orchestrator.py
git commit -m "feat(agent): add Foundry Agent Framework orchestrator with grounded citations and guardrail

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 3: 에이전트 CLI (agent/ask.py) + 실제 질의 시연

**Files:**
- Create: `agent/ask.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: `agent.orchestrator.ask_sync`.
- Produces:
  - CLI: `python -m agent.ask "<질문>"` — 답변, **추론 단계(도구 호출 목록)**, 인용 출처를 사람이 읽기 좋게 출력.

- [ ] **Step 1: ask.py 구현**

Create `agent/ask.py`:
```python
from __future__ import annotations

import argparse

from agent.orchestrator import ask_sync


def main() -> None:
    ap = argparse.ArgumentParser(description="Ask the fund-evaluation agent")
    ap.add_argument("question", help="질문 (한국어)")
    args = ap.parse_args()

    result = ask_sync(args.question)

    print("=" * 60)
    print("[추론 단계]")
    for i, s in enumerate(result.steps, 1):
        print(f"  {i}. {s.tool}(\"{s.query}\") -> {s.n_hits} hits")
    print("=" * 60)
    print("[답변]")
    print(result.answer)
    print("=" * 60)
    print("[근거]")
    for s in result.sources:
        print(f"  [출처 {s.n}] ({s.index}) {s.section_path} p.{s.page_physical}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 실제 시연 (여러 질의 유형)**

Run:
```bash
uv run python -m agent.ask "자산운용 평가의 목적과 평가단 구성은?"
uv run python -m agent.ask "탁월 등급과 우수 등급의 차이는?"
```
Expected: 각 질문에 대해 추론 단계(도구 호출)·근거 인용이 포함된 답변 출력. 도구가 1회 이상 호출되고 출처가 표시됨.

- [ ] **Step 3: README 갱신**

Edit `README.md` — "문서 인제스트 (P2)" 아래에 추가:
```markdown
## 에이전트 질의 (P3)
```bash
uv run python -m agent.ask "자산운용 평가의 목적은?"
```
에이전트가 질문을 분해해 narrative/table 인덱스를 조회하고(agentic retrieval), 근거를 인용해 답변합니다. 근거가 없으면 답변을 거부합니다.
```

- [ ] **Step 4: 전체 테스트 회귀 확인**

Run: `uv run pytest -q`
Expected: 기존 + agent 테스트 모두 PASS.

- [ ] **Step 5: Commit**

```bash
git add agent/ask.py README.md
git commit -m "feat(agent): add agent CLI showing reasoning steps and citations

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Self-Review 결과

- **Spec coverage:** Microsoft Agent Framework + Foundry LLM 오케스트레이터(Task 2), 질문분해·다중 인덱스 조회 도구(Task 1) = agentic retrieval(V5/V6), 근거 인용 + 할루시네이션 거부(Task 2 프롬프트·테스트, V6), 관측 가능한 추론 단계(TraceRecorder → CLI, Task 1·3). 키리스·설정 주입 준수. 관리형 AI Search Knowledge Base 대안은 후속(선택).
- **Placeholder scan:** 코드/명령 구체화. Task 2 Step 2에 실행 중 검증·조정 지점 3가지(입력 형태/aio 자격증명/응답 접근자)를 명시 — 신규 프레임워크의 실제 동작으로 최소 조정.
- **Type consistency:** `TraceRecorder`/`TraceStep`/`RetrievedSource`(Task 1) ↔ `AnswerResult`·`ask`/`ask_sync`(Task 2) ↔ CLI(Task 3) 일치. 도구는 as_agent(tools=...)에 일반 함수로 전달. 검색은 `hybrid_search`(P2)만 사용, 인덱스명은 settings에서.

## 후속 플랜
- **P4**: Chainlit UI — ask()의 steps/sources를 실시간 step·근거 카드로 렌더, 답변 내 표/차트.
- **P5**: Foundry Evaluation(agent_framework.foundry.FoundryEvals / evaluate_foundry_target) + Golden Q&A.
- (선택) 관리형 Knowledge Base 기반 agentic retrieval 대안 평가; P2 후속(year/fund_name 채우기, doc_id 삭제 후 재적재).
