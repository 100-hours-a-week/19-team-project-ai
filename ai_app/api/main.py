"""FastAPI Application Configuration with Router includes and Middleware."""

from fastapi import FastAPI

from api.endpoints import health_router

app = FastAPI(
    title="AI Resume & Mentoring Platform",
    description="AI-powered resume processing and mentor matching service",
    version="0.1.0",
)

# Include routers
app.include_router(health_router.router, tags=["Health"])
