import logging

from api.endpoints import health_router, jobs_router, reco_router, resumes_router
from dotenv import load_dotenv
from fastapi import FastAPI
from middleware.cloudwatch_metrics import CloudWatchMetricsMiddleware

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

app = FastAPI(
    title="AI Resume & Mentoring Platform",
    description="AI-powered resume processing and mentor matching service",
    version="0.1.0",
)

# CloudWatch 메트릭 수집 Middleware 등록
app.add_middleware(CloudWatchMetricsMiddleware)


# Root health check for CD/monitoring
@app.get("/health")
async def root_health():
    """Simple health check at root level for deployment monitoring"""
    return {"status": "ok"}


app.include_router(health_router.router, prefix="/api/ai", tags=["Health"])
app.include_router(resumes_router.router, prefix="/api/ai")
app.include_router(jobs_router.router, prefix="/api/ai")
app.include_router(reco_router.router, prefix="/api/ai")
