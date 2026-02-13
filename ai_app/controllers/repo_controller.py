"""레포트 컨트롤러 - HTTP 레이어 조율"""

from functools import lru_cache
from typing import Any

from schemas.repo import (
    JobParseRequest,
    MentorFeedback,
    ReportGenerateRequest,
)
from services.repo import parse_job_from_url
from services.repo.report_pipeline import get_report_pipeline


class RepoController:
    """채용공고 파싱 및 리포트 생성 조율"""

    def __init__(self):
        self.report_pipeline = get_report_pipeline()
        self._job_store: dict[str, dict] = {}
        self._report_store: dict[str, dict] = {}

    async def parse_job(self, request: JobParseRequest) -> dict[str, Any]:
        """채용공고 파싱 - CrawlerService 우선, LLM fallback"""
        import logging

        logger = logging.getLogger(__name__)

        # 1. CrawlerService 우선 시도 (사람인/잡코리아/원티드)
        try:
            from services.job_crawler.crawler_service import get_crawler_service

            crawler_service = get_crawler_service()
            job_posting = await crawler_service.parse_url(request.job_url)

            if job_posting:
                job_data = job_posting.model_dump()
                job_id = f"job_{len(self._job_store) + 1}"
                self._job_store[job_id] = job_data
                logger.info(f"CrawlerService 파싱 성공 - {job_data.get('title')}")
                return {
                    "success": True,
                    "job_id": job_id,
                    "data": job_data,
                }

            logger.info("CrawlerService가 이 URL을 지원하지 않음, LLM fallback 시도")
        except Exception as e:
            logger.warning(f"CrawlerService 파싱 실패, LLM fallback: {e}")

        # 2. LLM fallback
        result = await parse_job_from_url(request.job_url)

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
        job_data: dict,
    ) -> dict[str, Any]:
        """리포트 생성 - 현직자 피드백 + AI 분석 통합"""

        # 채팅 메시지 변환
        chat_messages = None
        if request.chat_messages:
            chat_messages = [msg.model_dump() for msg in request.chat_messages]

        # 리포트 파이프라인 실행
        result = await self.report_pipeline.generate(
            resume_data=resume_data,
            job_data=job_data,
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
