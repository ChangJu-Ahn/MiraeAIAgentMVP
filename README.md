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

설계: `specs/2026-07-06-agentic-rag-chatbot-design.md`
