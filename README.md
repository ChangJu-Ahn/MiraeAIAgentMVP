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

설계: `specs/2026-07-06-agentic-rag-chatbot-design.md`
