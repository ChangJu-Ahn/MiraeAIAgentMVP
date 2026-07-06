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

## 평가 (P5)
```bash
uv run python -m eval.run_eval            # 전체 Golden Q&A 평가 → reports/eval-report.md
uv run python -m eval.run_eval --limit 3  # 소규모 실행
```
Foundry judge(azure-ai-evaluation)로 Groundedness·Relevance·Retrieval·Coherence·Fluency를 측정하고, 인용율·할루시네이션 방어를 목표선(정확도 80%·인용 90%·방어 90%)과 비교합니다.

설계: `specs/2026-07-06-agentic-rag-chatbot-design.md`
