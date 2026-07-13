# Microsoft Agent Framework(MAF) — 통제·오케스트레이션·툴콜링 상세 분석 리포트

> 대상: 수익자 홈페이지 AI 챗봇 PoC (MiraeAIAgentMVP)<br>
> 작성 목적: 오픈소스 **Microsoft Agent Framework(MAF)** 로 에이전트를 **어떻게 구성·통제**하고, **어떻게 오케스트레이션**하며, **어떻게 툴콜링**하는지를 코드 근거와 함께 상세히 기록.<br>
> 코드 기준: `agent/orchestrator.py`, `agent/tools.py`, `agent/visuals.py`, `agent/translate.py`, `agent/reflection.py`, `agent/observability.py`, `app/chat.py` (main 브랜치, P1~P12 + 추론 요약 스트리밍/2단계 접이식 UI 반영)<br>
> 라이브러리: `agent_framework`(코어), `agent_framework_foundry`(Foundry 채팅 클라이언트), `agent_framework_openai`(OpenAI/Responses 어댑터) — `.venv` 실측 기준.

---

## 0. 한눈에 — MAF가 이 프로젝트에서 맡는 역할

```
                       ┌──────────────────────────── MAF 오케스트레이션 ────────────────────────────┐
 사용자 질문 ──────────▶│  Agent(=as_agent 산출)                                                    │
                       │   ├─ instructions(system prompt) ── 행동 규칙·언어·거부 가드·인용 강제        │
                       │   ├─ tools[5] ── search_narrative/search_tables + make_table/chart/source    │
                       │   ├─ default_options.reasoning ── effort=medium, summary=auto (사고 노출)     │
                       │   └─ FoundryChatClient (키리스, DefaultAzureCredential)                       │
                       │                                                                              │
                       │   [자동 함수 호출 루프] LLM ↔ 도구  (max_iterations=40, 병렬, 오류 3회 가드)   │
                       │        └ 에이전트가 스스로 질의 분해→다중 검색→교차참조→인용→시각화            │
                       └───────────────────────────────────────────────────────────────────────────┘
                                       │ (스트림: text_reasoning / function_call / function_result / text)
                                       ▼
       app 레벨 오케스트레이션: 토큰 스트리밍 · 2단계 접이식 진행표시 · 자가점검 루프(최대 2R) · 출처 카드
```

- MAF는 **단일 에이전트(single-agent) + 자동 함수 호출(agentic tool-use)** 패턴으로 사용된다. 멀티 에이전트 그래프/워크플로는 쓰지 않는다.
- "오케스트레이션"은 **두 층**으로 나뉜다:
  1. **MAF 내부 오케스트레이션** — LLM과 도구 사이의 자동 함수 호출 루프(질의 분해·다중 조회·교차 참조를 *모델이 스스로* 수행).
  2. **애플리케이션 오케스트레이션** — MAF 위에서 감싼 스트리밍 표시·자가 점검(reflection) 재질의 루프·번역·출처 카드(`app/chat.py`).

---

## 1. 에이전트 생성 & 클라이언트 계층 — `build_agent()`

`agent/orchestrator.py` — `build_agent(recorder, visual_recorder)`

```python
client = FoundryChatClient(
    project_endpoint=settings.foundry_project_endpoint,
    model=settings.foundry_chat_deployment,      # 배포명 "reasoning" = gpt-5.4-mini
    credential=DefaultAzureCredential(),          # 키리스(Entra RBAC)
)
tools = make_search_tools(recorder) + make_visual_tools(visual_recorder)
return client.as_agent(
    name="mirae-fund-agent",
    instructions=SYSTEM_PROMPT,
    tools=tools,
    default_options={"reasoning": {"effort": "medium", "summary": "auto"}},
)
```

### 1.1 `FoundryChatClient`의 계층 구조 (MRO) — "통제 지점"의 정체
실측 MRO:
```
FoundryChatClient
 └ FunctionInvocationLayer   ← 자동 함수 호출 루프(툴콜링의 심장, §2.3)
   └ ChatMiddlewareLayer     ← 미들웨어 삽입 지점(요청/함수 가로채기)
     └ ChatTelemetryLayer    ← OpenTelemetry gen_ai 스팬(§5.2)
       └ RawFoundryChatClient → RawOpenAIChatClient → BaseChatClient
```
즉 **툴콜링·미들웨어·텔레메트리가 클라이언트에 데코레이터처럼 겹겹이 감긴 계층**이며, 우리는 이 스택을 그대로 활용한다. 이 프로젝트는 커스텀 미들웨어를 두지 않고(과거 계획/툴 트레이스 미들웨어는 제거됨), 진행 상황은 스트림 콘텐츠를 직접 파싱해 표시한다(§4, `app/chat.py`).

### 1.2 `as_agent()`가 만드는 `Agent`
`BaseChatClient.as_agent(...)`는 클라이언트를 감싼 `Agent` 인스턴스를 반환한다. 주요 파라미터(이 프로젝트가 사용하는 것):

| 파라미터 | 값 | 통제 의미 |
|---|---|---|
| `instructions` | `SYSTEM_PROMPT` | 매 호출 **system 메시지**로 주입 → 행동·언어·거부 가드·인용 규칙(§3.2) |
| `tools` | 함수 5개 | LLM에 노출되는 도구 스키마(§2) |
| `default_options` | `{"reasoning": {...}}` | 모델 추론 강도·요약 노출(§3.3) |
| `name` | `"mirae-fund-agent"` | 관측/식별 |
| (미사용) `middleware`, `context_providers`, `compaction_strategy`, `tokenizer` | — | 확장 여지(§7) |

> 인증은 전 구간 **키리스**: `DefaultAzureCredential`(Managed Identity/Entra RBAC). 키/시크릿을 코드·환경에 두지 않는다.

---

## 2. 툴콜링(Function Calling) 메커니즘

### 2.1 Python 함수 → 도구 스키마 **자동 변환**
도구는 데코레이터 없이 **평범한 파이썬 함수**로 정의하고, `as_agent(tools=[...])`에 그대로 넘긴다. MAF(`ai_function`/`FunctionTool`)가 **함수명·타입힌트·docstring**을 읽어 LLM용 JSON 스키마를 자동 생성한다.

실측(예: `search_narrative`):
- `name` = 함수명 `search_narrative`
- `description` = docstring 전문(용도 설명 + `Args:`)
- `parameters` = `{"properties": {"query": {"type": "string", "title": "Query"}}, "required": ["query"], ...}`

→ **한 곳(함수)만 정의하면** 실행 코드와 LLM 노출 스키마가 동시에 확정된다. 스키마 표류(drift)가 원천 차단됨. 그래서 docstring/타입힌트가 곧 "프롬프트"이며, 이 프로젝트는 docstring에 **사용 지침(정성=narrative, 수치=tables 등)** 을 한국어로 상세히 적어 도구 선택 정확도를 높인다.

### 2.2 도구 카탈로그 (5개, 두 묶음)

**검색 도구** — `agent/tools.py` `make_search_tools(recorder)`
| 도구 | 역할 | 인덱스 |
|---|---|---|
| `search_narrative(query)` | 서술형 본문(총평·정성) 하이브리드 검색 | `narrative-index` |
| `search_tables(query)` | 표(등급·수익률 등 수치) 하이브리드 검색 | `table-index` |

- 내부 `_run_tool()`이 `search/hybrid.py`의 **BM25+벡터+시맨틱** 하이브리드 검색을 수행하고, 각 히트를 `[출처 N]` 형식 텍스트로 만들어 반환. 동시에 `RetrievedSource`로 **사이드 기록**(§2.4).

**시각화 도구** — `agent/visuals.py` `make_visual_tools(visual_recorder)`
| 도구 | 역할 | UI 바인딩 |
|---|---|---|
| `make_table(title, columns_json, rows_json)` | 정형 표 표시 | `cl.Dataframe` |
| `make_chart(title, chart_kind, x_label, y_label, x_json, series_json)` | line/bar 차트 | `cl.Plotly` |
| `show_source_page(page)` | 원문 PDF 페이지 이미지 | `cl.Image`(지연 렌더) |

- 시각화 도구는 화면 표시를 위한 **부수효과 기록**만 하고, 실제 렌더링 데이터(`Visual`)를 `VisualRecorder`에 쌓는다. 실 렌더는 앱 계층에서 수행(`app/visual_bind.py`, `app/chat.py`).
- 인자를 `*_json` 문자열로 받는 이유: 도구 스키마를 단순 스칼라로 유지해 모델이 채우기 쉽게 하고, 앱에서 `json.loads`로 구조화.

### 2.3 자동 함수 호출 루프 — `FunctionInvocationLayer` (툴콜링의 심장)
MAF가 **LLM ↔ 도구 왕복을 자동으로 반복**한다(우리 코드는 루프를 직접 돌리지 않음). 실측 기본 통제값(`agent_framework/_tools.py`):

| 통제 파라미터 | 기본값 | 의미 |
|---|---|---|
| `max_iterations` | **40** | LLM ↔ 도구 **왕복(라운드트립) 상한**. 각 라운드는 여러 도구를 병렬 호출 가능 |
| `max_consecutive_errors_per_request` | **3** | 연속 도구 오류 허용 횟수(초과 시 중단) — 무한 실패 방어 |
| `max_function_calls` | (옵션) | 요청 전체에서 총 도구 호출 수 상한 |
| `max_invocations`(도구별) | (옵션) | 특정 도구의 호출 횟수 제한 |

- **병렬 호출**: 한 라운드에서 모델이 `search_narrative`를 4번 등 동시에 호출 → MAF가 병렬 실행 후 결과를 모아 다음 라운드에 투입. (실측: 한 질문에 도구 8~12회 호출 관측.)
- 이 프로젝트는 이 값들을 **명시 오버라이드하지 않고 기본값을 사용** → 필요 시 `client.function_invocation_configuration["max_iterations"] = N`으로 조정 가능(§7).

### 2.4 부수효과 기록 — 클로저 + Recorder (관측·근거의 토대)
도구 팩토리는 `recorder`를 **클로저로 캡처**한다. 도구가 실행될 때마다:
- `TraceRecorder.steps` ← `TraceStep(tool, query, n_hits)` (추론 단계)
- `TraceRecorder.sources` ← `RetrievedSource(n, section_path, page, ...)` (인용 근거)
- `VisualRecorder.items` ← 표/차트/이미지

→ **에이전트 실행과 무관한 사이드 채널**로 근거·시각물을 수집. 답변의 `[출처 N]` 인용을 UI 카드로 연결(`app/formatting.py`)하고, 인용 누락 시 검색된 자료를 "참고한 자료"로 대체 표시하는 근거가 된다.

---

## 3. 오케스트레이션 & 통제

### 3.1 패턴 — 단일 에이전트 + **Agentic Retrieval**
관리형 "AI Search Knowledge Base" 대신, **에이전트가 스스로 검색을 계획**하도록 오케스트레이션한다:
1. 질문을 하위 질의로 분해(모델 추론)
2. 목적별로 `search_narrative`/`search_tables`를 **여러 번·병렬** 호출
3. 여러 인덱스·질의 결과를 **교차 참조**해 답변 합성
4. 필요 시 `make_*`/`show_source_page`로 시각화

이 "다중 조회·교차참조"가 스펙의 **Agentic Retrieval / 다중 문서 교차참조(V5)** 검증축이며, MAF의 자동 함수 호출 루프(§2.3)가 이를 실행 엔진으로 뒷받침한다.

### 3.2 행동 통제 — 시스템 프롬프트(`SYSTEM_PROMPT`)
`instructions`로 주입되는 규칙이 에이전트 행동의 1차 통제선이다:
- **언어 규칙(최우선)**: 최종 답변·사고 과정·추론 요약까지 **사용자 질문 언어**로.
- **도구 라우팅**: 정성=`search_narrative`, 수치/등급/표=`search_tables`, 교차 확인 위해 다중 호출.
- **인용 강제**: 근거를 `[출처 N]`(+section_path·page)으로.
- **거부 가드(할루시네이션 방어)**: 근거 없으면 "제공된 자료에서 확인할 수 없습니다".
- **시각화 데이터 진실성**: 검색으로 확인한 실제 값만 사용, 지어내지 않음.

### 3.3 추론(reasoning) 제어 — `default_options`
```python
default_options={"reasoning": {"effort": "medium", "summary": "auto"}}
```
- `effort="medium"`: 추론 토큰 강도(품질/지연 균형).
- `summary="auto"`: **추론 요약(reasoning summary)** 생성 활성화 → 스트림에 `text_reasoning` 콘텐츠로 흘러나와 "생각 중" 스텝에 노출(§4). 이 옵션이 없으면 사고 과정이 UI에 보이지 않는다.
- 모델은 Foundry `gpt-5.4-mini`(배포명 `reasoning`, GlobalStandard, 용량 200K TPM로 상향).

### 3.4 애플리케이션 오케스트레이션 — 자가 점검(Reflection) 루프
`app/chat.py` `on_message` + `agent/reflection.py` — **MAF 밖에서** 에이전트를 한 번 더 감싼 통제:
1. 1라운드 답변 생성(스트리밍).
2. `critique(question, answer, sources)` — **별도 Foundry judge**(eval 배포)가 "충분한가?"를 JSON으로 판정.
3. 부족하면 `augmented_question()`으로 보완 지시를 붙여 **2라운드 재질의**(최대 2R).
4. 점검 자체가 실패하면 안전하게 "충분"으로 통과(가용성 우선).

→ 단일 에이전트를 **자기 반영(self-reflection)** 으로 강화하는 경량 오케스트레이션. 멀티 에이전트 없이 품질을 끌어올린다.

---

## 4. 실행 모드 & 스트림 콘텐츠

| 모드 | 진입점 | 용도 |
|---|---|---|
| 동기 | `ask()` / `ask_sync()` → `agent.run(question)` | CLI(`agent/ask.py`), 배치/평가 |
| 스트리밍 | `start_stream()` → `agent.run(question, stream=True)` | 챗 UI(`app/chat.py`) |

스트리밍 시 `update.contents`에 도착하는 유형과 소비 방식:

| 콘텐츠 타입 | 내용 | UI 처리(`app/chat.py`) |
|---|---|---|
| `text_reasoning` | 추론 요약 델타 | 부모 "생각 중" 스텝에 누적(질문 언어와 다르면 세그먼트 단위 번역, `agent/translate.py`) |
| `function_call` | 도구 호출(name+arguments, 델타 누적) | `call_id`별 **접이식 자식 스텝** 생성(입력=검색어) |
| `function_result` | 도구 결과 | 해당 자식 스텝의 출력(결과 전문) 채움 |
| `text` | 최종 답변 델타 | 답변 메시지로 토큰 스트리밍 |
| `usage` | 토큰 사용량 | (미표시) |

→ **자동 함수 호출 루프의 내부 상태가 스트림으로 그대로 관측**되므로, 별도 미들웨어 없이 진행 과정을 2단계 접이식(생각 중 → 각 도구)으로 재구성할 수 있다.

---

## 5. 거버넌스 계층 요약

### 5.1 인증 — 키리스 전 구간
`FoundryChatClient`, `SearchClient`, 임베딩·그림 설명·평가·번역 모두 `DefaultAzureCredential`. 키/시크릿 미보관, Entra RBAC로 최소권한.

### 5.2 관측성 — OpenTelemetry gen_ai
`agent/observability.py` `setup_observability()`:
- `configure_otel_providers(...)` + `enable_instrumentation(enable_sensitive_data=True)`
- `ChatTelemetryLayer`(§1.1)가 에이전트 실행·툴 콜(입력=근거 질의, 출력=답변)을 **gen_ai 스팬**으로 Azure Application Insights에 기록.
- 프로세스당 1회 설정(idempotent), 연결 문자열 없으면 no-op.

### 5.3 결정성·안전 가드
- 도구 오류 3연속 시 중단(§2.3), 루프 40회 상한 → 폭주 방지.
- 시스템 프롬프트의 거부 가드 → 근거 없는 답변 억제.
- `critique` 실패 시 fail-safe 통과 → 점검 오류가 서비스 중단으로 번지지 않음.

---

## 6. 통제 파라미터 한눈에

| 항목 | 위치 | 현재값 | 조정 방법 |
|---|---|---|---|
| system 규칙 | `orchestrator.SYSTEM_PROMPT` | 언어/라우팅/인용/거부 | 프롬프트 편집 |
| 추론 강도 | `default_options.reasoning.effort` | `medium` | `low`/`high` 등 |
| 추론 요약 노출 | `default_options.reasoning.summary` | `auto` | `off`로 숨김 가능 |
| 자동 함수 루프 왕복 | `function_invocation_configuration.max_iterations` | 기본 **40** | 클라이언트에 오버라이드 |
| 연속 오류 허용 | `max_consecutive_errors_per_request` | 기본 **3** | 동상 |
| 총 도구 호출/도구별 호출 | `max_function_calls`/`max_invocations` | 미설정 | 필요 시 지정 |
| 자가 점검 라운드 | `app/chat.py` `max_rounds` | **2** | 상수 변경 |
| 모델/배포 | `settings.foundry_chat_deployment` | `reasoning`(gpt-5.4-mini) | `.env` |
| 도구 검색 top-k | `tools._run_tool(top=5)` | 5 | 인자 변경 |

---

## 7. 한계 & 확장 여지

- **단일 에이전트**만 사용. MAF의 멀티 에이전트 워크플로/그래프(핸드오프·병렬 팬아웃)는 미사용 — 필요 시 분해 가능.
- **미들웨어 미사용**: `ChatMiddlewareLayer`가 있으나 커스텀 미들웨어를 두지 않음(진행 표시는 스트림 파싱으로 대체). 정책 가드·PII 마스킹·레이트리밋 등을 미들웨어로 삽입할 여지.
- **컨텍스트/히스토리 관리 미사용**: `context_providers`, `compaction_strategy`, `tokenizer` 미설정 → 장기 대화·컨텍스트 압축이 필요하면 활성화.
- **루프 상한 기본값 의존**: `max_iterations=40`은 넉넉하나, 비용/지연 통제가 필요하면 낮춰 지정 권장.
- **추론 요약 언어**: 모델이 영어로 생성 → 앱에서 세그먼트 번역으로 우회(추가 LLM 호출·지연). 모델측 언어 제어가 개선되면 번역 제거 가능.

---

## 8. 요약

이 프로젝트는 MAF를 **"단일 에이전트 + 자동 함수 호출"** 로 사용한다. 핵심은 (1) **평범한 파이썬 함수(도구 5개)를 도구로 자동 스키마화**해 LLM에 노출하고, (2) `FunctionInvocationLayer`의 **자동 함수 호출 루프**(왕복 40·병렬·오류 3회 가드)가 *에이전트 주도 다중 검색·교차참조*를 실행하며, (3) **시스템 프롬프트·reasoning 옵션·키리스 인증·OTel 관측**으로 행동과 운영을 통제하고, (4) 그 위에 **앱 레벨 자가 점검 루프·스트리밍 2단계 진행표시·출처 카드**를 오케스트레이션으로 얹어 품질과 설명가능성을 확보한다는 점이다. 도구 정의(함수+docstring)가 곧 통제면이므로, 스키마 표류 없이 실행·노출·근거 기록이 한 지점에서 일관되게 관리된다.
