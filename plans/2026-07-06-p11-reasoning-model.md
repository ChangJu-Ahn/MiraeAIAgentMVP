# P11: 추론 모델 전환 + 인용 근거만 표시 + 에이전트 설명 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development 또는 executing-plans. Steps use checkbox syntax.

**Goal:** (1) 챗봇·평가 judge를 **gpt-5.4-mini(추론, effort=medium, summary)** 로 전환해 계획/사고 과정이 실제로 나오게 하고, 그림 설명은 gpt-4o 유지. (2) 근거 카드를 **답변이 실제 인용한 `[출처 N]` 만** 표시. (3) Chainlit 시작 화면(chainlit.md)에 **에이전트·도구 설명**을 추가.

**Architecture:** Foundry에 gpt-5.4-mini 배포(`reasoning`)를 추가(gpt-4o `chat` 배포는 그림설명용으로 유지). `settings`에 `foundry_chat_deployment=reasoning`(챗+judge), `foundry_vision_deployment=chat`(그림)로 분리. 오케스트레이터가 `default_options={"reasoning":{"effort":"medium","summary":"auto"}}`로 에이전트를 만들고, 추론 요약을 계획 이벤트로 캡처(경험적 확인). `app/formatting.py`에 인용 파서를 추가해 답변의 `[출처 N]`에 해당하는 sources만 필터. chainlit.md 갱신.

**Tech Stack:** Bicep, Python 3.12(uv), agent-framework(reasoning options, streaming), azure-ai-evaluation, chainlit, pytest.

## Global Constraints
- 챗봇 오케스트레이션·평가 judge = **gpt-5.4-mini**; 그림 멀티모달 설명 = **gpt-4o**(유지). 임베딩 = text-embedding-3-large(유지). 키리스.
- reasoning: effort="medium", summary="auto".
- 근거 카드는 답변이 인용한 [출처 N]만(cited-only). 인용 없으면 카드 생략.
- 배포/설정 변경은 재배포로 반영. ask/ask_sync 시그니처 호환.
- 커밋 트레일러 필수.

## 확정된 사실
- koreacentral gpt-5.4-mini(2026-03-17, GlobalStandard) 가용.
- FoundryChatOptions.reasoning = ReasoningOptions{effort: none|low|medium|high|xhigh, summary: auto|concise|detailed}.
- 추론 요약이 스트림에서 어떻게 표면화되는지는 **경험적 확인 필요**(update.text 인라인 vs 별도) — Task 2 Step에 명시.

---

## File Structure
- `infra/modules/foundry.bicep` (수정) — reasoning 배포 추가
- `infra/main.bicep` (수정) — reasoning 파라미터/출력
- `scripts/deploy.sh` (수정) — FOUNDRY_CHAT_DEPLOYMENT=reasoning, FOUNDRY_VISION_DEPLOYMENT=chat
- `config/settings.py` (수정) — foundry_vision_deployment 추가
- `ingest/figures.py` (수정) — 그림 설명은 vision 배포 사용
- `agent/orchestrator.py` (수정) — reasoning default_options + 계획 이벤트 캡처
- `app/formatting.py` (수정) — `cited_sources(answer, sources)`
- `app/chat.py` (수정) — 인용된 근거만 표시
- `chainlit.md` (수정) — 에이전트/도구 설명
- tests: `test_formatting.py`(cited_sources), 회귀

---

## Task 1: gpt-5.4-mini 배포 + 배포 분리 + 재배포

**Files:** Modify `infra/modules/foundry.bicep`, `infra/main.bicep`, `scripts/deploy.sh`, `config/settings.py`, `ingest/figures.py`, `.env.example`

- [ ] **Step 1: foundry.bicep에 reasoning 배포 추가**

Edit `infra/modules/foundry.bicep` — add params + a third deployment (sequential dependsOn to avoid concurrent-deploy conflict):
```bicep
param reasoningModelName string = 'gpt-5.4-mini'
param reasoningModelVersion string = '2026-03-17'
param reasoningDeploymentName string = 'reasoning'
param reasoningCapacity int = 20
```
Add resource after embedding (dependsOn embedding):
```bicep
resource reasoning 'Microsoft.CognitiveServices/accounts/deployments@2025-04-01-preview' = {
  parent: account
  name: reasoningDeploymentName
  dependsOn: [embedding]
  sku: { name: 'GlobalStandard', capacity: reasoningCapacity }
  properties: {
    model: { format: 'OpenAI', name: reasoningModelName, version: reasoningModelVersion }
  }
}
```
Add output: `output reasoningDeploymentName string = reasoning.name`

Run: `az bicep build --file infra/modules/foundry.bicep --stdout > /dev/null && echo OK` → `OK`

- [ ] **Step 2: main.bicep 통합**

Edit `infra/main.bicep` — pass through (defaults ok) + add output:
```bicep
output reasoningDeploymentName string = foundry.outputs.reasoningDeploymentName
```
Run: `az bicep build --file infra/main.bicep --stdout > /dev/null && echo OK` → `OK`

- [ ] **Step 3: settings + figures 분리**

Edit `config/settings.py` — add:
```python
    foundry_vision_deployment: str = "chat"
```
(foundry_chat_deployment는 재배포 후 .env에서 reasoning으로 채워짐; 기본값은 호환 위해 "chat" 유지)

Edit `ingest/figures.py` `describe_figure` — 모델을 vision 배포로:
```python
        model=s.foundry_vision_deployment,
```

Edit `.env.example` — add `FOUNDRY_VISION_DEPLOYMENT=chat`.

- [ ] **Step 4: deploy.sh — .env 매핑**

Edit `scripts/deploy.sh` — parse reasoning output, set chat=reasoning + vision=chat:
```bash
reasoning=$(echo "$OUT" | python3 -c "import sys,json;print(json.load(sys.stdin)['reasoningDeploymentName']['value'])")
```
In the `.env` heredoc change:
```
FOUNDRY_CHAT_DEPLOYMENT=$reasoning
FOUNDRY_VISION_DEPLOYMENT=$chat
```
(기존 `chat` 변수는 gpt-4o 배포명 'chat')

- [ ] **Step 5: 재배포**

Run: `bash scripts/deploy.sh`
Expected: reasoning 배포 생성, `.env`에 `FOUNDRY_CHAT_DEPLOYMENT=reasoning`, `FOUNDRY_VISION_DEPLOYMENT=chat`. (실 Azure, 수 분)

- [ ] **Step 6: 확인 + Commit**

Run: `grep -E "FOUNDRY_(CHAT|VISION)_DEPLOYMENT" .env`
Expected: chat=reasoning, vision=chat.

```bash
git add infra/modules/foundry.bicep infra/main.bicep scripts/deploy.sh config/settings.py ingest/figures.py .env.example
git commit -m "feat(infra): add gpt-5.4-mini reasoning deployment; split vision(gpt-4o) deployment

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 2: 오케스트레이터 reasoning + 계획 캡처

**Files:** Modify `agent/orchestrator.py`, `agent/middleware.py`(필요시)

- [ ] **Step 1: reasoning default_options 주입**

Edit `agent/orchestrator.py` `build_agent` — add default_options:
```python
    return client.as_agent(
        name="mirae-fund-agent",
        instructions=SYSTEM_PROMPT,
        tools=tools,
        middleware=middleware,
        default_options={"reasoning": {"effort": "medium", "summary": "auto"}},
    )
```

- [ ] **Step 2: 경험적 확인 — 계획/추론 요약이 어떻게 나오나**

Run:
```bash
uv run python -c "
import asyncio
from agent.orchestrator import start_stream
async def run():
    stream, tr, vr, pr = start_stream('탁월 등급과 우수 등급의 차이는?')
    texts=[]
    async for u in stream:
        if u.text: texts.append(u.text)
    return tr, pr, ''.join(texts)
tr, pr, ans = asyncio.run(run())
print('plan events:', sum(1 for e in pr.events if e.kind==\"plan\"))
print('tool events:', sum(1 for e in pr.events if e.kind==\"tool\"))
print('answer head:', ans[:200])
print('sources:', len(tr.sources))
"
```
관찰: 계획 이벤트/추론 요약이 (a) process events의 plan으로 잡히는지, (b) update에 reasoning 요약이 별도로 오는지, (c) 답변 앞 텍스트로 오는지.
- 만약 reasoning summary가 `update`에 별도 필드(예: reasoning/summary)로 온다면, chat.py의 스트리밍 루프에서 이를 분리해 "🧠 추론" step/영역으로 표시하도록 Task 3에서 처리.
- plan 이벤트가 여전히 0이고 요약이 답변 텍스트에 섞이면, 요약을 답변과 분리하는 방법(update 속성)을 SDK introspect로 찾고, 없으면 "추론 요약은 답변 상단에 표시"로 수용·문서화.
- reasoning 모델이 tool calling과 함께 정상 동작하는지도 확인(도구 이벤트 ≥1 유지).

- [ ] **Step 3: 회귀 (ask/streaming/eval judge)**

Run: `uv run pytest tests/agent/test_orchestrator.py tests/agent/test_streaming.py -v`
Expected: PASS. (reasoning 모델로 바뀌어도 근거 인용·거부 동작 유지 확인. 만약 gpt-5.4-mini가 거부 문구를 다르게 내면 guard 테스트의 부정표지 세트로 흡수됨.)

- [ ] **Step 4: Commit**
```bash
git add agent/orchestrator.py
git commit -m "feat(agent): enable reasoning (effort=medium, summary) on orchestrator

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 3: 인용 근거만 표시 + UI 계획 표시 + chainlit.md

**Files:** Modify `app/formatting.py`, `app/chat.py`, `chainlit.md`; Test `tests/app/test_formatting.py`

- [ ] **Step 1: cited_sources 순수 함수 (TDD)**

Add to `tests/app/test_formatting.py`:
```python
def test_cited_sources_filters_to_referenced():
    from agent.tools import RetrievedSource
    from app.formatting import cited_sources

    srcs = [
        RetrievedSource(n=1, index="narrative-index", section_path="A", page_physical=1, chunk_type="narrative", snippet="s"),
        RetrievedSource(n=2, index="table-index", section_path="B", page_physical=2, chunk_type="table", snippet="s"),
        RetrievedSource(n=3, index="narrative-index", section_path="C", page_physical=3, chunk_type="narrative", snippet="s"),
    ]
    answer = "핵심은 [출처 1] 이고 표는 [출처 3] 참조."
    out = cited_sources(answer, srcs)
    assert {s.n for s in out} == {1, 3}


def test_cited_sources_empty_when_no_refs():
    from agent.tools import RetrievedSource
    from app.formatting import cited_sources
    srcs = [RetrievedSource(n=1, index="x", section_path="A", page_physical=1, chunk_type="narrative", snippet="s")]
    assert cited_sources("인용 없음", srcs) == []
```

Add to `app/formatting.py`:
```python
import re

def cited_sources(answer: str, sources: list) -> list:
    nums = {int(m) for m in re.findall(r"\[출처\s*(\d+)\]", answer)}
    return [s for s in sources if s.n in nums]
```

Run: `uv run pytest tests/app/test_formatting.py -v` → PASS.

- [ ] **Step 2: chat.py — 인용된 근거만 표시**

Edit `app/chat.py` — replace citations block:
```python
    from app.formatting import cited_sources
    used = cited_sources(answer_text, trace.sources)
    citations = format_citations(used)
    if citations:
        await cl.Message(content=citations).send()
```
where `answer_text` accumulates streamed tokens (add `answer_text = ""` and `answer_text += update.text` in the loop). If Task 2 shows a separate reasoning-summary field on updates, render it as a `🧠 추론` step here.

- [ ] **Step 3: chainlit.md — 에이전트/도구 설명 추가**

Overwrite `chainlit.md`:
```markdown
# 기금운용평가보고서 AI 어시스턴트

기금운용평가보고서(한글 PDF)를 기반으로 답하는 **Agentic RAG 챗봇** 데모입니다. Microsoft Foundry(gpt-5.4-mini, 추론) + Azure AI Search + Document Intelligence + Microsoft Agent Framework.

## 에이전트가 하는 일
질문을 분해해 여러 인덱스를 조회하고(agentic retrieval), 근거를 인용해 답변합니다. 자료에 없으면 답변을 거부합니다(할루시네이션 방어). 추론(계획) 과정과 도구 호출이 단계로 표시되고, 답변은 토큰 단위로 스트리밍됩니다.

## 사용 가능한 도구
| 도구 | 동작 |
|------|------|
| 🔎 search_narrative | 서술형 본문(평가 개요·총평·정성 설명) 하이브리드 검색 |
| 📊 search_tables | 표(등급·점수·수익률 등 수치/정형 데이터) 하이브리드 검색 |
| 📋 make_table | 정형 데이터를 표(정렬 가능)로 표시 |
| 📈 make_chart | 추세/비교를 차트(line/bar)로 표시 |
| 🖼️ show_source_page | 근거가 된 원문 PDF 페이지를 이미지로 표시 |

## 화면 구성
- 🧠 계획 / 🔧 도구: 에이전트의 추론·도구 실행 과정(입력=근거 질의, 결과)
- 답변: 근거 [출처 N] 인용, 필요 시 표·차트·원문 이미지
- 근거: 답변이 실제 인용한 출처(섹션·페이지)

## 예시 질문
- 자산운용 평가의 목적은 무엇인가요?
- 탁월 등급과 우수 등급의 차이는?
- 국민연금기금의 상대수익률을 표로 보여줘
- (원문 확인) 국민연금 상대수익률 표의 원문 페이지를 보여줘
```

- [ ] **Step 4: 임포트/서버 스모크 + 실제 인용필터 확인**

Run: `uv run python -c "import app.chat; print('import OK')"`
Run: `uv run chainlit run app/chat.py --headless --port 8774 & CL=$!; sleep 12; curl -sS -o /dev/null -w "HTTP %{http_code}\n" http://localhost:8774/; kill $CL 2>/dev/null || true` → `HTTP 200`

- [ ] **Step 5: 회귀 + Commit**

Run: `uv run pytest -q -k "not test_orchestrator and not runner_smoke and not render_and_describe and not build_figure_chunks and not test_streaming"` → PASS.

```bash
git add app/formatting.py app/chat.py chainlit.md tests/app/test_formatting.py
git commit -m "feat(app): show only cited sources; add agent/tools guide to welcome screen

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Self-Review 결과
- **Spec coverage:** 추론 모델(gpt-5.4-mini, effort=medium, summary)로 계획/사고 노출(Task 1,2), 인용 근거만 표시(Task 3), 그림설명 gpt-4o 유지(vision 배포 분리), 에이전트/도구 설명(chainlit.md).
- **경험적 리스크:** 추론 요약의 스트림 표면화 방식은 Task 2 Step 2에서 확인 후 UI 반영 결정. reasoning 모델의 tool calling·평가 judge 호환도 회귀로 확인.
- **Type consistency:** foundry_vision_deployment(settings) ↔ figures/deploy.sh/.env 일치. cited_sources(answer, sources) ↔ chat.py 사용 일치. reasoning 배포 output 이름(reasoningDeploymentName) ↔ deploy.sh 파서 일치.

## 후속
- 추론 요약을 전용 "🧠 추론" 패널로 정제, effort 조정(비용/지연 트레이드오프), judge를 reasoning으로 둔 평가 재실행·리포트 갱신.
