# AI Service Dockerfile
# Multi-stage build for Python FastAPI application

FROM --platform=linux/arm64 python:3.11-slim AS base

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl \
        build-essential \
        && rm -rf /var/lib/apt/lists/*

# 의존성 먼저 설치 (레이어 캐시 활용 — 코드 변경 시 재설치 방지)
COPY pyproject.toml MANIFEST.in ./
RUN mkdir -p ai_app && \
    pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -e .

# 애플리케이션 코드는 마지막에 복사 (코드 변경 시 이 레이어만 갱신)
COPY ai_app ./ai_app

# Create non-root user
RUN useradd -m -u 1001 aiuser && \
    chown -R aiuser:aiuser /app

# Switch to non-root user
USER aiuser

# Set PYTHONPATH so 'from api.endpoints' works
ENV PYTHONPATH=/app/ai_app:$PYTHONPATH

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run application
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
