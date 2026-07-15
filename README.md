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

# 전체 코퍼스 인제스트 (report 3건 + guideline 2건)
uv run python -m ingest.run --all

# 검증만 수행 (임베딩·Azure Search 쓰기 없이 추출·카탈로그·팩트 완전성 확인)
uv run python -m ingest.run --all --validate-only
```
추가 자료는 전달받는 대로 동일 명령을 새 --doc-id로 재실행하면 upsert 됩니다.

> `--validate-only`는 PDF 파싱·청킹·기금 카탈로그 추출·청크 주석·평가 팩트 추출과 완전성 검증만 수행합니다. 임베딩, Vision 그림 설명(figure descriptions), Azure Search 인덱스 생성/쓰기는 일절 하지 않으므로 Azure 연결 없이 로컬에서 실행 가능합니다. 그림은 실제 인제스트에서만 생성됩니다.

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
> 에이전트의 도구 실행(🔧, 입력=근거 질의·결과)이 MAF 미들웨어로 캡처되어 단계로 표시되고 App Insights 트레이스에도 남습니다.
> 답변 후 스스로 충분성을 점검(🔍)하고, 부족하면 부족한 부분을 보완 질의로 다시 조회해 답변을 개선합니다(최대 2라운드).

> 답변에 표(정형 데이터)·차트(추세/비교)·원문 페이지 이미지가 필요하면 에이전트가 자동으로 함께 표시합니다.

## 평가 (P5)
```bash
# Azure 호출 없이 Excel 구조와 문항 수 확인
uv run python -m eval.run_eval "Chatbot_질문지리스트_20260713" --validate-only

# 전체 질문·정답 평가
uv run python -m eval.run_eval "Chatbot_질문지리스트_20260713"

# 처음 3문항만 평가
uv run python -m eval.run_eval "Chatbot_질문지리스트_20260713" --limit 3
```
제목은 `Docs/<제목>.xlsx`의 확장자를 제외한 파일명입니다. 활성 시트의 첫 번째 비어 있지 않은 행에서 `질문`과 `정답` 열을 찾으며 두 값은 필수입니다. `순번`과 `유형`은 선택값이고, 없으면 각각 Excel 행 기반 ID와 `미분류`를 사용합니다. 영문 헤더 `question`/`query`, `ground_truth`/`reference_answer`, `id`, `qtype`/`category`도 지원합니다.

Foundry judge(`azure-ai-evaluation==1.17.0`)로 Groundedness·Relevance·Similarity·Coherence·Fluency를 각각 1~5점, 통과 기준 3점으로 평가합니다. Similarity는 Excel의 검토 정답을 사용하고, Fluency는 답변을 번역하지 않고 답변이 작성된 언어의 문법·자연스러움·가독성을 평가합니다. 결과는 기본적으로 `reports/eval-<제목>.md`와 같은 이름의 `.json`에 저장되며, 점수·판정 이유·실제 judge context·검색 trace·출처·실패 군집·개선 제안을 포함합니다.

전체 실행은 문항마다 에이전트 호출 1회와 judge 호출 5회를 수행하므로 Azure 사용 비용과 실행 시간이 발생합니다. 먼저 `--validate-only` 또는 작은 `--limit`으로 입력과 연결을 확인하세요.

## 관측성 (P8)
`.env`에 `APPINSIGHTS_CONNECTION_STRING`이 있으면 에이전트 실행·툴 콜(입력=근거, 출력=답변)이 OpenTelemetry로 Azure Application Insights에 자동 기록됩니다(민감 데이터 포함). 각 진입점(챗봇/CLI)이 시작 시 `setup_observability()`를 호출합니다. 미설정 시 안전하게 no-op.

**트레이스 확인**: Azure Portal → Application Insights → Transaction search 또는 Logs(KQL): `dependencies | where timestamp > ago(30m)` (에이전트 실행·툴 콜 gen_ai 스팬).

설계: `specs/2026-07-06-agentic-rag-chatbot-design.md`
