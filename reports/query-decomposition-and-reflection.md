# 쿼리 분해 · 반복 검색 · 근거 부족 시 재질문 — 동작 원리 리포트

> 대상: 수익자 홈페이지 AI 챗봇 PoC (MiraeAIAgentMVP)
> 작성 목적: 하나의 질문이 **여러 개의 검색 쿼리로 쪼개져** 조회되는 원리와, **답변 근거가 부족할 때 다시 질문(재검색)** 하는 로직을 코드 근거와 함께 정확히 이해하기 위함.
> 코드 기준: `agent/orchestrator.py`, `agent/tools.py`, `search/hybrid.py`, `app/chat.py`, `agent/reflection.py` (main 브랜치)
> 핵심 조합: **Microsoft Agent Framework(오픈소스, `agent-framework 1.10.0`)** + **Foundry 추론 모델(reasoning)**

---

## 0. 한눈에

```
사용자 질문 1개
   │
   ▼  ┌───────────────────── 한 라운드 = agent.run() 1회 ─────────────────────┐
   │  │  [추론 모델의 tool-calling 루프]  (Agent Framework가 오케스트레이션)     │
   │  │                                                                        │
   │  │   LLM 추론(계획) ─▶ query 작문 ─▶ search_narrative(query) 실행 ─┐        │
   │  │        ▲                                                       │        │
   │  │        └──────── 결과(5건)를 보고 다음 query 결정 ◀────────────┘        │
   │  │   … 모델이 "충분"하다고 판단할 때까지 반복 (쿼리 N개 생성) …             │
   │  │   → tool_call 없이 최종 답변 생성 시 루프 종료                          │
   │  └────────────────────────────────────────────────────────────────────┘
   │                       │  답변 + 근거(sources)
   ▼                       ▼
[reflection] 답변이 근거를 충분히 커버했나?  ──(부족)──▶ 보완 질의로 라운드 2 재실행
   │                                                     (원 질문 + "[보완 지시] …")
   └──(충분/최대 라운드)──▶ 종료
```

- **쿼리를 쪼개는 주체 = 추론 모델**. 코드에 쿼리 분해·재작성 로직은 없다.
- **반복시키는 주체 = Agent Framework의 tool-calling 루프**.
- **근거 부족 시 다시 묻는 주체 = 우리 app 코드의 reflection 루프** (별도 판정 LLM).

---

## 1. 핵심 결론 — "누가 쿼리를 쪼갰나?"

**추론 모델(LLM)이 추론(계획) 과정에서 직접 쪼갠다.** 우리 코드에는 질문을 하위 쿼리로 나누거나 다시 쓰는 함수가 **한 줄도 없다.**

근거:
- 도구 함수 시그니처가 `search_narrative(query: str)` — 이 `query` 문자열을 **모델이 채운다** (`agent/tools.py:60`).
- 시스템 프롬프트가 분해를 **지시**만 한다: `"1. 질문을 필요한 하위 질의로 분해하세요."` (`agent/orchestrator.py:19`).
- 모델은 `reasoning: {effort: medium, summary: auto}` 로 계획을 세운다 (`agent/orchestrator.py:46`).
- 채워진 `query`는 **가공 없이** AI Search로 전달된다 (`agent/tools.py:35` → `search/hybrid.py`).

즉 "query generation"이라는 별도 단계/모듈이 아니라, **추론 모델의 tool_call 생성 = 쿼리 생성**이다.

---

## 2. 실제 예시 — "비계량지표 3개 대분류는 각각 뭘 평가해?" → 6 쿼리

관측된 실제 호출(모두 `search_narrative`, 즉 정성 질문으로 판단해 `search_tables`는 0회):

```
[1] search_narrative("비계량지표 3개 대분류 각각 무엇을 평가하는지")            → 5건
[2] search_narrative("비계량지표 대분류 3개 평가 항목")                          → 5건
[3] search_narrative("비계량지표 3개 대분류 운용 기본체계 운용성과 관리체계")     → 5건
[4] search_narrative("자산운용 체계 비계량지표 … 가버넌스 전담조직")             → 5건
[5] search_narrative("자산운용 정책 비계량지표 … 목표 자산배분 투자 실행과정")   → 5건
[6] search_narrative("자산운용 위험 및 성과관리 비계량지표 … 위험관리 성과관리") → 5건
```

이 6개는 **탐색 → 정제**의 2단계로, 모델이 앞 결과를 보고 다음 쿼리를 스스로 만든 결과다:

| 단계 | 쿼리 | 모델의 의도 |
|---|---|---|
| 탐색 | 1~3 | 아직 3개 대분류명을 모름 → 원 질문 재표현 + 대분류명 추측 |
| 정제 | 4~6 | 1~3 결과에서 실제 3개 대분류(**자산운용 체계 / 정책 / 위험 및 성과관리**)를 알아낸 뒤, **대분류마다 1개씩** 집중 조회 |

> 참고: 1~3은 서로 겹쳐 같은 문서를 중복 조회하는 면이 있다(커버리지↑, 속도↓의 트레이드오프). 이는 성능 문제라기보다 반복 검색의 자연스러운 특성이다.

---

## 3. 동작 단계별 상세 (코드 근거)

### ① 도구 등록 + 추론 설정 — `agent/orchestrator.py`
```python
# L19 (SYSTEM_PROMPT 규칙 1): "질문을 필요한 하위 질의로 분해하세요."
# L42~46
return client.as_agent(
    name="mirae-fund-agent",
    instructions=SYSTEM_PROMPT,
    tools=tools,                       # search_narrative, search_tables (+ 시각화 도구)
    default_options={"reasoning": {"effort": "medium", "summary": "auto"}},
)
# L67 start_stream: agent.run(question, stream=True) 로 루프 시작
```
- 파이썬 함수 2개가 LLM이 호출 가능한 **tool**로 등록된다.
- `reasoning.effort=medium` 이 계획/분해 강도를 결정한다.

### ② 에이전트 tool-calling 루프 (여기서 쿼리 N개가 생성) — Agent Framework
개념적 제어 흐름(프레임워크 내부):
```
반복:
  LLM이 [추론 요약] + [tool_call(들)] 생성       # tool_call.arguments = {"query": "..."} ← 모델 작문
    → 프레임워크가 파이썬 함수 실제 실행           # search_narrative(query=...)
    → 결과(검색 5건)를 LLM 컨텍스트에 재주입
  LLM이 판단:
    - 더 필요 → 또 tool_call  (쿼리 4·5·6이 여기서 생성됨)
    - 충분함 → tool_call 없이 최종 답변 → 루프 종료
```
이 루프가 눈에 보이는 지점 — `app/chat.py` `_run_round` (L86~):
```python
# L144
async for update in stream:
    for content in update.contents:
        # L148 ctype == "text_reasoning"  → 모델의 추론 요약
        # L163 ctype == "function_call"   → 도구 호출(=쿼리). call_id별 arguments 누적
        # L172 ctype == "function_result" → 도구 실행 결과
        # (그 외) ctype == "text"         → 최종 답변 토큰
```
`function_call`이 6번 도착 = 위 루프가 6번 반복 = `search_narrative` 6회.

### ③ 도구 실행 = AI Search 하이브리드 검색 1회 — `agent/tools.py` + `search/hybrid.py`
```python
# agent/tools.py L32~35
def _run_tool(recorder, tool_name, index_name, query, top=5):
    hits = hybrid_search(index_name, query, top=top)   # ← 모델이 만든 query 그대로 전달
    recorder.steps.append(TraceStep(tool=tool_name, query=query, n_hits=len(hits)))
    ...
# agent/tools.py L60
def search_narrative(query: str) -> str:   # ← 모델이 query 인자를 직접 채움
    return _run_tool(recorder, "search_narrative", settings.search_index_narrative, query)
```
- 도구 1콜 = 쿼리 1개 = AI Search 1회 (벡터 + BM25 + 시맨틱 리랭킹, `top=5` → 5건).
- 쿼리 문자열에 대한 **재작성·분해·정규화는 없다** — 모델 출력을 그대로 사용.

### ④ 근거 부족 시 "다시 질문" (reflection 루프) — `app/chat.py` + `agent/reflection.py`
```python
# app/chat.py answer_and_render (L212~)
max_rounds = 2                                    # L217
for rnd in range(1, max_rounds + 1):              # L224
    answer_text, trace, visual = await _run_round(question)   # ①~③ 한 라운드 실행 (L225)
    if rnd == max_rounds:
        break                                     # L227: 마지막 라운드면 종료
    verdict = await critique(original_question, answer_text, trace.sources)  # L231: 충분한가?
    if verdict.sufficient:
        break                                     # L238: 충분 → 종료
    question = augmented_question(original_question, verdict.missing)        # L239: 보완 질의로 재실행
```
```python
# agent/reflection.py
# L55 critique(): 별도 판정 LLM이 {"sufficient": bool, "missing": "..."} 반환
#     (프롬프트 L18~31: 누락된 하위 질문·수치·근거가 있으면 부족 판정)
# L41 parse_verdict(): 판정 JSON 파싱. 실패 시 안전하게 sufficient=True (통과)
# L34 augmented_question(): 원 질문 + "[보완 지시] 이전 답변에서 …부족했으니 보완해 답하라"
```
→ 라운드 1이 부족 판정되면, **보완 지시가 붙은 질문으로 ②③ 루프를 한 번 더** 돈다.
그래서 관측된 6개 쿼리는 **한 라운드에 몰려 있을 수도**, **라운드1 + 라운드2로 나뉘어** 있을 수도 있다(디버그 사이드바가 라운드 경계를 보여줌).

> 안전장치: `critique` 호출이 예외로 실패하면 경고 로그 후 **충분으로 간주하고 종료**한다(무한 재질의 방지). `app/chat.py:232~234`.

---

## 4. 제어 흐름 의사코드 (전체)

```text
answer_and_render(question):
    reset_trace()                          # OTel 스팬 버퍼 초기화
    for round in 1..2:
        # --- 한 라운드 = Agent Framework tool-calling 루프 (내부 반복) ---
        stream = agent.run(question)       # 추론 모델 ↔ 도구
        while 모델이 tool_call을 내면:
            query = 모델이_작문한_문자열     # ← 쿼리 "분해/생성"의 실체
            result = hybrid_search(query)  # AI Search 1회
            결과를_모델에_재주입()
        answer, sources = 최종답변
        # --- 라운드 종료 후 자가 점검 ---
        if round == 2: break
        verdict = critique(question, answer, sources)   # 별도 LLM 판정
        if verdict.sufficient: break
        question = question + "[보완 지시] " + verdict.missing   # 재질문
    render(answer, 근거카드, 디버그사이드바, 후속질문버튼)
```

---

## 5. 어디서 확인하나 (읽기 가이드)

| 순서 | 파일·라인 | 확인 내용 |
|---|---|---|
| 1 | `agent/orchestrator.py:19`, `:42-46` | 분해 지시(규칙1) + 추론 모델·도구 등록 |
| 2 | `agent/tools.py:60`, `:32-35` | 모델이 `query`를 채우는 도구 + AI Search 실행(가공 없음) |
| 3 | `app/chat.py:144-176` (`_run_round`) | tool-calling 루프의 실제 이벤트(`function_call` = 쿼리들) |
| 4 | `app/chat.py:217-239` + `agent/reflection.py:34,41,55` | 근거 부족 시 보완 질의로 재검색 |

**실행 중 확인**: 우측 상단 ⚙️에서 **디버그 모드 ON** → 우측 사이드바에 **라운드별 도구 호출·쿼리·관련도 점수**와 맨 아래 **Raw OpenTelemetry 트레이스**가 그대로 표시된다. ③의 각 `function_call`과 ④의 라운드 경계를 실제 데이터로 매칭해 볼 수 있다.

---

## 6. 조절 포인트 (참고)

동작을 바꾸고 싶을 때 만지는 위치(현재는 기본값 유지):

| 목표 | 위치 | 방법 |
|---|---|---|
| 쿼리 수 줄이기(중복 억제) | `agent/orchestrator.py` 규칙 1 | "먼저 1회 검색해 대분류 파악 후 꼭 필요한 하위 질의만; 중복 재표현 금지" 추가 |
| 분해 강도 낮추기 | `agent/orchestrator.py:46` | `reasoning.effort` = `low` |
| 재질의(2R) 끄기 | `app/chat.py:217` | `max_rounds = 1` |
| 호출당 검색량 조정 | `agent/tools.py` `_run_tool` | `top` 값 변경(현재 5) |

---

## 7. 한 줄 요약

**쪼개는 지능은 추론 모델**(계획→`query` 작문)이, **그 판단을 도구 실행으로 반복시키는 런타임 루프는 Microsoft Agent Framework**가, **근거가 부족하면 다시 묻는 자가 점검은 우리 app 코드(reflection)** 가 담당한다. 세 요소의 조합이 "질문 1개 → 다중 쿼리 → (부족 시) 재검색 → 답변"을 만들어낸다.
