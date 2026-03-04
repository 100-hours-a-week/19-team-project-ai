# AI 서비스 Dockerfile
# 멀티 스테이지 빌드로 런타임 이미지 크기 최소화

FROM python:3.11-slim AS builder

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_NO_DEV=1

# 빌드 단계에서만 필요한 패키지 설치
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        && rm -rf /var/lib/apt/lists/*

# 런타임 의존성을 프로젝트 가상환경에 설치
COPY pyproject.toml MANIFEST.in uv.lock ./
RUN mkdir -p ai_app
RUN pip install --no-cache-dir uv && uv sync --frozen --no-install-project

# 애플리케이션 코드를 복사하고 lockfile 기준으로 동기화
COPY ai_app ./ai_app
RUN uv sync --locked && \
    rm -rf /root/.cache /tmp/* && \
    find /app/.venv -type d -name "__pycache__" -prune -exec rm -rf {} +


FROM python:3.11-slim AS runtime

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# 실행에 필요한 파일만 복사
RUN useradd -m -u 1001 aiuser
COPY --from=builder --chown=aiuser:aiuser /app/.venv /app/.venv
COPY --from=builder --chown=aiuser:aiuser /app/ai_app /app/ai_app
USER aiuser

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH=/app/ai_app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=5)" || exit 1

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
