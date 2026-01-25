"""FastAPI Application Configuration with Router includes and Middleware."""

from dotenv import load_dotenv

# .env 파일에서 환경변수 로드 (다른 임포트보다 먼저 실행)
load_dotenv()

import logging

from fastapi import FastAPI

from api.endpoints import health_router, resumes_router

# 로그 레벨 설정 (INFO 이상 출력)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

app = FastAPI(
    title="AI Resume & Mentoring Platform",
    description="AI-powered resume processing and mentor matching service",
    version="0.1.0",
)

# Include routers
app.include_router(health_router.router, tags=["Health"])
app.include_router(resumes_router.router)
