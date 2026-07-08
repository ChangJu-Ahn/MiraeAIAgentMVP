FROM python:3.12-slim

# poppler-utils: show_source_page(원문 페이지 이미지) 렌더용 pdftoppm
RUN apt-get update && apt-get install -y --no-install-recommends poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# uv (astral)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# 의존성 먼저 설치 (레이어 캐시). 프로젝트 자체는 소스 경로로 실행하므로 미설치.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# 앱 소스 + 원문 PDF(렌더용) + chainlit 설정
COPY agent/ agent/
COPY app/ app/
COPY search/ search/
COPY ingest/ ingest/
COPY config/ config/
COPY Docs/ Docs/
COPY .chainlit/ .chainlit/
COPY chainlit.md ./

ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
CMD ["chainlit", "run", "app/chat.py", "--host", "0.0.0.0", "--port", "8000"]
