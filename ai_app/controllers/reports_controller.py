"""Reports 컨트롤러 - 리포트 생성 핸들러"""

from functools import lru_cache

from schemas.reports import (
    ReportData,
    ReportRequest,
)
from services.report import ReportGenerator, get_report_generator


class ReportsController:
    """리포트 생성 컨트롤러"""

    def __init__(self, report_generator: ReportGenerator | None = None):
        self.report_generator = report_generator or get_report_generator()

    async def generate_report(
        self,
        report_id: int,
        request: ReportRequest,
    ) -> ReportData:
        """
        리포트 생성

        Args:
            report_id: 리포트 ID
            request: 리포트 생성 요청

        Returns:
            ReportData: 생성된 리포트
        """
        result = await self.report_generator.generate_report(
            job_posting_title=request.job_posting_title,
            job_posting_content=request.job_posting_content,
            resume_content=request.resume_content,
            expert_feedback=request.expert_feedback,
        )

        return ReportData(
            report_id=report_id,
            result=result,
        )


@lru_cache(maxsize=1)
def get_reports_controller() -> ReportsController:
    """컨트롤러 싱글톤"""
    return ReportsController()
