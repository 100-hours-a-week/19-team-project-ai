"""
CloudWatch 메트릭 전송 미들웨어

현재 프로젝트 구조:
- ai_app/api/middleware/cloudwatch_metrics.py (이 파일)
- ai_app/api/endpoints/*.py (라우터들)
"""

import logging
import os
from datetime import datetime
from typing import Literal

import boto3

logger = logging.getLogger(__name__)

# Feature 타입 정의 (현재 프로젝트 기준)
FeatureType = Literal["DocumentAnalysis", "Recommendation", "ReportGeneration"]


class CloudWatchMetrics:
    """CloudWatch 메트릭 전송 서비스"""

    def __init__(self):
        self.cloudwatch = boto3.client("cloudwatch", region_name=os.getenv("AWS_REGION", "ap-northeast-2"))
        self.namespace = "ReFit/AI"
        self.environment = os.getenv("ENVIRONMENT", "production")
        self.enabled = os.getenv("METRICS_ENABLED", "true").lower() == "true"

    def track_request(self, feature: FeatureType, success: bool, duration: float):
        """
        AI 요청 메트릭 전송

        Args:
            feature: AI 기능 타입
                - 'DocumentAnalysis': 이력서/자소서 분석 (resumes_router.py)
                - 'Recommendation': 현직자 추천 (reco_router.py)
                - 'ReportGeneration': 리포트 생성 (해당 라우터)
            success: 성공 여부
            duration: 처리 시간 (초)
        """
        if not self.enabled:
            logger.debug(f"Metrics disabled, skipping: {feature}")
            return

        try:
            self.cloudwatch.put_metric_data(
                Namespace=self.namespace,
                MetricData=[
                    # 성공률 메트릭
                    {
                        "MetricName": f"{feature}SuccessRate",
                        "Value": 100.0 if success else 0.0,
                        "Unit": "Percent",
                        "Timestamp": datetime.utcnow(),
                        "Dimensions": [{"Name": "Environment", "Value": self.environment}],
                    },
                    # 지연시간 메트릭
                    {
                        "MetricName": f"{feature}Latency",
                        "Value": duration,
                        "Unit": "Seconds",
                        "Timestamp": datetime.utcnow(),
                        "Dimensions": [{"Name": "Environment", "Value": self.environment}],
                        "StorageResolution": 1,  # 1분 해상도
                    },
                    # 요청 카운트
                    {
                        "MetricName": f"{feature}RequestCount",
                        "Value": 1,
                        "Unit": "Count",
                        "Timestamp": datetime.utcnow(),
                        "Dimensions": [
                            {"Name": "Environment", "Value": self.environment},
                            {"Name": "Status", "Value": "Success" if success else "Failure"},
                        ],
                    },
                ],
            )
            logger.info(f"✅ Metrics sent: {feature}, success={success}, duration={duration:.2f}s")

        except Exception as e:
            # 메트릭 전송 실패해도 API는 계속 동작
            logger.error(f"❌ Failed to send CloudWatch metrics: {e}")


# 싱글톤 인스턴스 (전역에서 재사용)
metrics_service = CloudWatchMetrics()
