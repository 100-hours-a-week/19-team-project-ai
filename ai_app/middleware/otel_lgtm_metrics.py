"""LGTM 대시보드 호환 커스텀 메트릭."""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Iterator

from fastapi import FastAPI, Request
from prometheus_client import Gauge, Histogram
from sqlalchemy.engine import Connection, Engine

ASYNCIO_PROCESS_DURATION_SECONDS = Histogram(
    "asyncio_process_duration_seconds",
    "Async HTTP request processing duration in seconds.",
    labelnames=("route", "method", "status_code"),
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30),
)

DB_CLIENT_CONNECTIONS_USAGE = Gauge(
    "db_client_connections_usage",
    "Current DB client connections checked out from SQLAlchemy pool.",
)

_EXCLUDED_PATHS = {
    "/health",
    "/api/ai/health",
    "/api/ai/metrics",
}


def _checked_out_connections(engine: Engine) -> float:
    """SQLAlchemy pool에서 현재 checkout된 커넥션 수를 가져온다."""
    pool = engine.pool
    checkedout = getattr(pool, "checkedout", None)
    if callable(checkedout):
        return float(checkedout())
    return 0.0


@contextmanager
def tracked_db_connection(engine: Engine) -> Iterator[Connection]:
    """DB 커넥션 사용량 게이지를 갱신하며 커넥션을 연다."""
    DB_CLIENT_CONNECTIONS_USAGE.set(_checked_out_connections(engine))
    conn = engine.connect()
    DB_CLIENT_CONNECTIONS_USAGE.set(_checked_out_connections(engine))
    try:
        yield conn
    finally:
        conn.close()
        DB_CLIENT_CONNECTIONS_USAGE.set(_checked_out_connections(engine))


def install_lgtm_metrics(app: FastAPI) -> None:
    """FastAPI 요청 처리 시간을 asyncio_process_duration_seconds로 기록."""

    # 프로세스 시작 시 0으로 초기화 (No data 대신 0 시계열 유지)
    DB_CLIENT_CONNECTIONS_USAGE.set(0.0)

    @app.middleware("http")
    async def _observe_asyncio_processing(request: Request, call_next):
        path = request.url.path
        if path in _EXCLUDED_PATHS:
            return await call_next(request)

        start = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            duration = time.perf_counter() - start
            route = request.scope.get("route")
            route_path = getattr(route, "path", path)
            ASYNCIO_PROCESS_DURATION_SECONDS.labels(
                route=route_path,
                method=request.method,
                status_code=str(status_code),
            ).observe(duration)
