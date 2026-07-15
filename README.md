# Mirae AI Agent MVP

기금운용평가 보고서와 지침을 근거로 답하는 Microsoft Foundry 기반 Agentic RAG PoC입니다.

## 흐름

1. Azure Document Intelligence가 PDF의 본문, 표, 그림, 페이지 구조를 추출합니다.
2. 인제스트 파이프라인이 추출 결과를 검증하고 Azure AI Search의 4개 인덱스에 적재합니다.
3. Microsoft Agent Framework가 질문에 필요한 검색 도구를 선택해 한 번의 agent run으로 답변합니다.
4. Chainlit이 답변을 스트리밍하고 인용 출처와 요청된 표, 차트, 원문 페이지를 표시합니다.
5. 평가 파이프라인이 답변과 실제 검색 근거를 5개 Foundry judge로 검증합니다.

| 인덱스 | 역할 |
|---|---|
| `narrative-index` | 서술형 본문 하이브리드 검색 |
| `table-index` | 표와 수치 문맥 하이브리드 검색 |
| `fund-catalog-index` | 연도별 평가 대상 기금 확인과 이름 해석 |
| `evaluation-facts-index` | 점수, 등급, 조정 항목, 결정적 집계 |

에이전트는 서술/표 검색과 `list_funds`, `resolve_fund`, `get_fund_evaluations`, `aggregate_evaluations`, `fund_analytics`를 사용합니다. 순위, 분포, 연도 비교, 등급 변화, 교집합은 LLM이 계산하지 않고 Python이 전체 모집단을 대상으로 계산합니다.

## 준비

- Python 3.12
- [uv](https://docs.astral.sh/uv/)
- Azure CLI 2.83 이상과 Bicep
- `az login`으로 인증된 Azure 구독

```bash
uv sync
```

## Azure 인프라

```bash
bash scripts/verify_availability.sh
bash scripts/deploy.sh
uv run python scripts/smoke_test.py
```

Bicep은 AI Search, Document Intelligence, Foundry, Application Insights, managed identity, ACR, Container Apps를 배포합니다. 애플리케이션은 `DefaultAzureCredential`과 managed identity를 사용합니다.

## 인제스트

```bash
# 전체 등록 코퍼스 검증: Azure Search 쓰기와 모델 호출 없음
uv run python -m ingest.run --all --validate-only

# 전체 등록 코퍼스 적재
uv run python -m ingest.run --all

# 등록된 문서 하나만 적재
uv run python -m ingest.run --doc-id <doc-id>
```

`--validate-only`는 파싱, 청킹, 카탈로그, 평가 팩트, 완전성 계약만 검사합니다. 실제 적재에서 그림 설명이 필요 없으면 `--no-figures`를 사용합니다. 문서 목록과 메타데이터는 `ingest/corpus.py`에서 관리합니다.

## 질의

```bash
# CLI
uv run python -m agent.ask "2022년 종합등급 분포를 알려줘"

# 웹 UI
uv run chainlit run app/chat.py -w
```

채팅마다 하나의 Agent Framework 세션을 재사용하므로 후속 질문의 대화 문맥은 유지됩니다. 각 메시지는 한 번 실행되며, 자료에 근거가 없으면 없다고 답합니다.

## 평가

```bash
# Excel 계약만 확인
uv run python -m eval.run_eval "Chatbot_질문지리스트_20260713" --validate-only

# 일부 문항 실행
uv run python -m eval.run_eval "Chatbot_질문지리스트_20260713" --limit 3

# 전체 실행 또는 checkpoint 재개
uv run python -m eval.run_eval "Chatbot_질문지리스트_20260713"
uv run python -m eval.run_eval "Chatbot_질문지리스트_20260713" --resume
```

Excel의 `질문`과 `정답` 열은 필수입니다. Groundedness, Relevance, Similarity, Coherence, Fluency를 1~5점으로 평가하며 3점 이상을 통과로 기록합니다. 결과는 `reports/`의 Markdown과 JSON에 저장됩니다.

## 관측성과 검증

`APPINSIGHTS_CONNECTION_STRING`이 설정되면 Agent Framework trace를 Application Insights로 전송합니다. 미설정이면 계측을 구성하지 않습니다.

```bash
uv run pytest -q
uv lock --check
```

현재 단순화 설계는 `docs/superpowers/specs/2026-07-15-core-demo-simplification.md`에 있습니다.
