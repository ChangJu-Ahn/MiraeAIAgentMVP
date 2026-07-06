# Mirae AI Agent MVP (Agentic RAG 챗봇 PoC)

문서 기반 Agentic RAG 챗봇 데모. Azure Document Intelligence + AI Search(agentic retrieval) + Microsoft Foundry + Microsoft Agent Framework + Chainlit.

## 요구사항
- Python 3.12 (uv), Azure CLI 2.83+, Bicep
- Azure 구독 로그인: `az login`

## 셋업
```bash
uv sync
```

## 인프라 배포 (P1)
```bash
bash scripts/verify_availability.sh   # 리전/모델 가용성 확인
bash scripts/deploy.sh                # 배포 + .env 생성
uv run python scripts/smoke_test.py   # 연결 스모크 테스트
```

## 문서 인제스트 (P2)
```bash
# PDF를 파싱·청킹·임베딩하여 AI Search 2개 인덱스에 적재
uv run python -m ingest.run --pdf "Docs/<파일>.pdf" --doc-id "<고유ID>"
```
추가 자료는 전달받는 대로 동일 명령을 새 --doc-id로 재실행하면 upsert 됩니다.

> 그림(figures)은 Foundry gpt-4o 멀티모달로 설명을 생성해 함께 인덱싱합니다(`--no-figures`로 비활성).

## 에이전트 질의 (P3)
```bash
uv run python -m agent.ask "자산운용 평가의 목적은?"
```
에이전트가 질문을 분해해 narrative/table 인덱스를 조회하고(agentic retrieval), 근거를 인용해 답변합니다. 근거가 없으면 답변을 거부합니다.

## 웹 UI 데모 (P4)
```bash
uv run chainlit run app/chat.py -w
```
브라우저에서 챗봇에 질문하면 추론 단계(도구 호출)·답변·근거 출처가 표시됩니다.

> 답변은 토큰 단위로 스트리밍되며, 도구 호출(추론 단계)이 진행되는 대로 실시간 표시됩니다.
> 에이전트의 계획(🧠)과 도구 실행(🔧, 입력=근거 질의·결과)이 MAF 미들웨어로 캡처되어 단계로 표시됩니다(스트리밍 모드에서는 계획이 답변 첫 문장에 인라인으로 표현될 수 있습니다). App Insights 트레이스에도 남습니다.

> 답변에 표(정형 데이터)·차트(추세/비교)·원문 페이지 이미지가 필요하면 에이전트가 자동으로 함께 표시합니다.

## 평가 (P5)
```bash
uv run python -m eval.run_eval            # 전체 Golden Q&A 평가 → reports/eval-report.md
uv run python -m eval.run_eval --limit 3  # 소규모 실행
```
Foundry judge(azure-ai-evaluation)로 Groundedness·Relevance·Retrieval·Coherence·Fluency를 측정하고, 인용율·할루시네이션 방어를 목표선(정확도 80%·인용 90%·방어 90%)과 비교합니다.

## 관측성 (P8)
`.env`에 `APPINSIGHTS_CONNECTION_STRING`이 있으면 에이전트 실행·툴 콜(입력=근거, 출력=답변)이 OpenTelemetry로 Azure Application Insights에 자동 기록됩니다(민감 데이터 포함). 각 진입점(챗봇/CLI)이 시작 시 `setup_observability()`를 호출합니다. 미설정 시 안전하게 no-op.

**트레이스 확인**: Azure Portal → Application Insights → Transaction search 또는 Logs(KQL): `dependencies | where timestamp > ago(30m)` (에이전트 실행·툴 콜 gen_ai 스팬).

설계: `specs/2026-07-06-agentic-rag-chatbot-design.md`
