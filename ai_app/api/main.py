import logging
import sys

from dotenv import load_dotenv
from fastapi import FastAPI

from api.endpoints import health_router, jobs_router, reco_router, resumes_router

load_dotenv()

# logging 설정: INFO 레벨 로그를 stdout으로 출력
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stdout,
)

app = FastAPI(
    title="AI Resume & Mentoring Platform",
    description="AI-powered resume processing and mentor matching service",
    version="0.1.0",
)


# Root health check for CD/monitoring
@app.get("/health")
async def root_health():
    """Simple health check at root level for deployment monitoring"""
    return {"status": "ok"}


app.include_router(health_router.router, prefix="/api/ai", tags=["Health"])
app.include_router(resumes_router.router, prefix="/api/ai")
app.include_router(jobs_router.router, prefix="/api/ai")
app.include_router(reco_router.router, prefix="/api/ai")
