import logging
import os

from api.endpoints import (
    agent_router,
    health_router,
    reco_router,
    repo_router,
    resumes_router,
)
from dotenv import load_dotenv
from fastapi import FastAPI
from middleware.otel_lgtm_metrics import install_lgtm_metrics
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from prometheus_fastapi_instrumentator import Instrumentator

# .env.ai가 있으면 먼저 로드 (배포 환경 용), 없으면 기본 .env 로드
load_dotenv(".env.ai")
load_dotenv()

# OpenTelemetry 트레이서 프로바이더 설정 (Tempo로 트레이스 전송, 4318=HTTP)
_otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://10.0.7.8:4318")
_provider = TracerProvider()
_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=_otlp_endpoint)))
trace.set_tracer_provider(_provider)

# 로깅 설정 강제 (터미널 출력 보장)
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s:%(name)s:%(message)s",
)

app = FastAPI(
    title="AI Resume & Mentoring Platform",
    description="AI-powered resume processing and mentor matching service",
    version="0.1.0",
)

# LGTM 대시보드 호환 커스텀 메트릭 추가
install_lgtm_metrics(app)

@app.middleware("http")
async def add_process_time_header(request, call_next):
    import time
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    
    # 터미널에서 즉시 확인할 수 있도록 강조 출력
    if not request.url.path.endswith(("/health", "/metrics")):
        print(f"\n>>> [PERF] {request.method} {request.url.path} | Duration: {process_time:.2f}s")
    
    response.headers["X-Process-Time"] = str(process_time)
    return response

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


@app.on_event("startup")
async def preload_embedding_model():
    """임베딩 모델을 서버 시작 시 미리 로드하여 첫 요청 지연(Cold Start) 제거"""
    if os.getenv("USE_RUNPOD_EMBEDDING", "false").lower() == "true":
        logging.info("RunPod 임베딩 모드가 활성화되어 로컬 모델 로드를 건너뜁니다.")
        return

    from services.reco.embedder import get_embedder

    get_embedder().model  # lazy loading 트리거


@app.on_event("shutdown")
async def cleanup_resources():
    """서버 종료 시 DB 커넥션 풀 및 HTTP 클라이언트 정리"""
    from adapters.backend_client import get_backend_client
    from adapters.db_client import close_pool

    await close_pool()
    await get_backend_client().aclose()


app.include_router(health_router.router, prefix="/api/ai", tags=["Health"])
app.include_router(resumes_router.router, prefix="/api/ai")
app.include_router(reco_router.router, prefix="/api/ai")
app.include_router(repo_router.router, prefix="/api/ai")
app.include_router(agent_router.router, prefix="/api/ai")

# FastAPI 자동 트레이싱 (otel-collector → Tempo)
FastAPIInstrumentor.instrument_app(app)
