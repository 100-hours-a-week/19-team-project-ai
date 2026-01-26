"""채용공고 API 컨트롤러"""

from fastapi import HTTPException

from schemas.common import ResponseCode
from schemas.jobs import JobPosting
from services.job_crawler.crawler_service import CrawlerService, get_crawler_service


class JobsController:
    """채용공고 API 컨트롤러"""

    def __init__(self, crawler_service: CrawlerService | None = None):
        self.crawler_service = crawler_service or get_crawler_service()

    async def parse_job_url(self, url: str) -> JobPosting:
        """채용공고 URL 파싱"""
        result = await self.crawler_service.parse_url(url)

        if not result:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": ResponseCode.BAD_REQUEST.value,
                    "data": {"message": "지원하지 않는 URL이거나 파싱에 실패했습니다.", "url": url},
                },
            )

        return result


# 싱글톤
_controller: JobsController | None = None


def get_jobs_controller() -> JobsController:
    """컨트롤러 싱글톤"""
    global _controller
    if _controller is None:
        _controller = JobsController()
    return _controller
