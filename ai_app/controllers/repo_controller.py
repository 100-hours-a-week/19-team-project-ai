"""레포트 컨트롤러 - HTTP 레이어 조율"""

from functools import lru_cache
from typing import Any

from schemas.repo import (
    JobParseRequest,
    MentorFeedback,
    ReportGenerateRequest,
)
from services.repo import parse_job_from_text, parse_job_from_url
from services.repo.report_pipeline import get_report_pipeline


class RepoController:
    """채용공고 파싱 및 리포트 생성 조율"""

    def __init__(self):
        self.report_pipeline = get_report_pipeline()
        # 임시 저장소 (실제로는 DB)
        self._job_store: dict[str, dict] = {}
        self._report_store: dict[str, dict] = {}

    async def parse_job(self, request: JobParseRequest) -> dict[str, Any]:
        """채용공고 파싱"""
        if request.job_url:
            result = await parse_job_from_url(request.job_url)
        elif request.job_text:
            result = await parse_job_from_text(request.job_text)
        else:
            return {
                "success": False,
                "error": "job_url 또는 job_text 중 하나는 필수입니다.",
            }

        if result.get("success"):
            job_data = result.get("data", {})
            job_id = f"job_{len(self._job_store) + 1}"
            self._job_store[job_id] = job_data

            return {
                "success": True,
                "job_id": job_id,
                "data": job_data,
            }

        return result

    async def generate_report(
        self,
        request: ReportGenerateRequest,
        resume_data: dict,
    ) -> dict[str, Any]:
        """리포트 생성 - 현직자 피드백 + AI 분석 통합"""

        # 채팅 메시지 변환
        chat_messages = None
        if request.chat_messages:
            chat_messages = [msg.model_dump() for msg in request.chat_messages]

        # 리포트 파이프라인 실행
        result = await self.report_pipeline.generate(
            resume_data=resume_data,
            job_url=request.job_url,
            job_text=request.job_text,
            resume_id=request.resume_id,
            mentor_feedback=request.mentor_feedback,
            chat_messages=chat_messages,
        )

        if result.success:
            report = {
                "success": True,
                "report_id": result.report_id,
                "resume_id": result.resume_id,
                "report_data": result.report_data,
                "processing_time_ms": result.processing_time_ms,
            }
            self._report_store[result.report_id] = report
            return report

        return {
            "success": False,
            "error": result.error_message,
        }

    async def get_report(self, report_id: str) -> dict[str, Any] | None:
        """리포트 조회"""
        return self._report_store.get(report_id)


@lru_cache(maxsize=1)
def get_repo_controller() -> RepoController:
    """컨트롤러 싱글톤"""
    return RepoController()
