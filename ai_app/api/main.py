import os

from api.endpoints import agent_router, health_router, reco_router, repo_router, resumes_router
from dotenv import load_dotenv
from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from prometheus_fastapi_instrumentator import Instrumentator

# .env.ai가 있으면 먼저 로드 (배포 환경 용), 없으면 기본 .env 로드
load_dotenv(".env.ai")
load_dotenv()

# OpenTelemetry 트레이서 프로바이더 설정 (Tempo로 트레이스 전송)
_otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "10.0.7.8:4317")
_provider = TracerProvider()
_provider.add_span_processor(
    BatchSpanProcessor(OTLPSpanExporter(endpoint=_otlp_endpoint, insecure=True))  # noqa: S501
)
trace.set_tracer_provider(_provider)

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
app.include_router(agent_router.router, prefix="/api/ai")

# FastAPI 자동 트레이싱 (otel-collector → Tempo)
FastAPIInstrumentor.instrument_app(app)
