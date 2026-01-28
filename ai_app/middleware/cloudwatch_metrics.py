"""
CloudWatch 메트릭 전송 Middleware
SLI/SLO 문서 기준에 맞춰 AI API 성능 지표를 CloudWatch로 전송
"""
import logging
import os
import time
from typing import Callable

import boto3
from botocore.exceptions import ClientError
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)

# CloudWatch 클라이언트 초기화
try:
    cloudwatch = boto3.client(
        "cloudwatch",
        region_name=os.getenv("AWS_REGION", "ap-northeast-2"),
    )
    CLOUDWATCH_ENABLED = os.getenv("CLOUDWATCH_METRICS_ENABLED", "false").lower() == "true"
except Exception as e:
    logger.warning(f"CloudWatch 클라이언트 초기화 실패: {e}")
    CLOUDWATCH_ENABLED = False

NAMESPACE = "ReFit/AI"
ENVIRONMENT = os.getenv("ENVIRONMENT", "production")


class CloudWatchMetricsMiddleware(BaseHTTPMiddleware):
    """
    AI API 요청의 성능 지표를 CloudWatch로 전송하는 Middleware
    
    수집 메트릭:
    - ResponseTime: API 응답 시간 (밀리초)
    - RequestCount: 요청 수 (StatusCode별)
    - ErrorCount: 에러 요청 수 (5xx)
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # AI API 경로만 측정 (/api/ai/*)
        if not request.url.path.startswith("/api/ai/"):
            return await call_next(request)
        
        # Health check는 제외
        if request.url.path == "/api/ai/health":
            return await call_next(request)

        start_time = time.time()
        
        try:
            response = await call_next(request)
            duration_ms = (time.time() - start_time) * 1000  # 밀리초
            
            # CloudWatch로 메트릭 전송 (비동기, 실패해도 요청은 계속)
            if CLOUDWATCH_ENABLED:
                self._send_metrics(
                    endpoint=request.url.path,
                    method=request.method,
                    status_code=response.status_code,
                    duration_ms=duration_ms,
                )
            
            return response
        
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            
            # 에러 발생 시 500으로 메트릭 전송
            if CLOUDWATCH_ENABLED:
                self._send_metrics(
                    endpoint=request.url.path,
                    method=request.method,
                    status_code=500,
                    duration_ms=duration_ms,
                )
            
            raise  # 원래 에러는 그대로 전파

    def _normalize_endpoint(self, endpoint: str) -> str:
        """동적 경로를 정규화하여 집계 가능하도록 변환"""
        import re
        
        # 동적 경로 패턴 정규화
        # /api/ai/mentors/recommend/123 → /api/ai/mentors/recommend
        # /api/ai/resumes/456/parse → /api/ai/resumes
        patterns = [
            (r'/api/ai/mentors/recommend/\d+', '/api/ai/mentors/recommend'),
            (r'/api/ai/resumes/\d+/parse', '/api/ai/resumes'),
            (r'/api/ai/resumes/\d+', '/api/ai/resumes'),
        ]
        
        normalized = endpoint
        for pattern, replacement in patterns:
            normalized = re.sub(pattern, replacement, normalized)
        
        return normalized

    def _send_metrics(
        self,
        endpoint: str,
        method: str,
        status_code: int,
        duration_ms: float,
    ):
        """CloudWatch로 메트릭 전송"""
        try:
            # 동적 경로 정규화
            normalized_endpoint = self._normalize_endpoint(endpoint)
            
            # StatusCode를 2xx, 4xx, 5xx 형식으로 변환
            status_class = f"{status_code // 100}xx"
            
            metric_data = [
                # 1. 응답 시간 (P95 계산용)
                {
                    "MetricName": "ResponseTime",
                    "Value": duration_ms,
                    "Unit": "Milliseconds",
                    "Dimensions": [
                        {"Name": "Endpoint", "Value": normalized_endpoint},
                        {"Name": "Environment", "Value": ENVIRONMENT},
                    ],
                    "StorageResolution": 60,  # 1분 단위 고해상도
                },
                # 2. 요청 수 (가용성 계산용)
                {
                    "MetricName": "RequestCount",
                    "Value": 1,
                    "Unit": "Count",
                    "Dimensions": [
                        {"Name": "Endpoint", "Value": normalized_endpoint},
                        {"Name": "StatusCode", "Value": status_class},
                        {"Name": "Environment", "Value": ENVIRONMENT},
                    ],
                    "StorageResolution": 60,
                },
                # 3. 전체 요청 수 (Rate Limit 포함)
                {
                    "MetricName": "RequestCount",
                    "Value": 1,
                    "Unit": "Count",
                    "Dimensions": [
                        {"Name": "Endpoint", "Value": normalized_endpoint},
                        {"Name": "Environment", "Value": ENVIRONMENT},
                    ],
                    "StorageResolution": 60,
                },
            ]
            
            # 4. 에러 카운트 (5xx만)
            if status_code >= 500:
                metric_data.append({
                    "MetricName": "ErrorCount",
                    "Value": 1,
                    "Unit": "Count",
                    "Dimensions": [
                        {"Name": "Endpoint", "Value": normalized_endpoint},
                        {"Name": "Environment", "Value": ENVIRONMENT},
                    ],
                    "StorageResolution": 60,
                })
            
            # CloudWatch로 전송 (비동기)
            cloudwatch.put_metric_data(
                Namespace=NAMESPACE,
                MetricData=metric_data,
            )
            
            logger.debug(
                f"CloudWatch 메트릭 전송: {normalized_endpoint} {status_code} {duration_ms:.2f}ms"
            )
        
        except ClientError as e:
            # CloudWatch 전송 실패는 로그만 남기고 계속
            logger.error(f"CloudWatch 메트릭 전송 실패: {e}")
        except Exception as e:
            logger.error(f"메트릭 처리 중 예외 발생: {e}")
