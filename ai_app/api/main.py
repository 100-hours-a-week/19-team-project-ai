from api.endpoints import health_router, reco_router, repo_router, resumes_router
from dotenv import load_dotenv
from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

load_dotenv()

app = FastAPI(
    title="AI Resume & Mentoring Platform",
    description="AI-powered resume processing and mentor matching service",
    version="0.1.0",
)

# Prometheus 메트릭 계측 (/metrics 엔드포인트 자동 생성)
Instrumentator(
    should_group_status_codes=False,  # 200, 201 등 개별 status code 유지
    should_ignore_untemplated=True,  # 등록되지 않은 경로 무시
    excluded_handlers=["/health", "/api/ai/health", "/api/ai/metrics"],  # health/metrics는 집계 제외
    inprogress_name="ai_inprogress_requests",
    inprogress_labels=True,
).instrument(app).expose(app, endpoint="/api/ai/metrics", include_in_schema=False)


# Root health check for CD/monitoring
@app.get("/health")
async def root_health():
    """Simple health check at root level for deployment monitoring"""
    return {"status": "ok"}


app.include_router(health_router.router, prefix="/api/ai", tags=["Health"])
app.include_router(resumes_router.router, prefix="/api/ai")
app.include_router(reco_router.router, prefix="/api/ai")
app.include_router(repo_router.router, prefix="/api/ai")
