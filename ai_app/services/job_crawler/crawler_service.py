"""채용공고 크롤링 서비스 - 여러 소스 오케스트레이션"""

import re
from urllib.parse import urlparse

from adapters.job_crawlers.base_crawler import BaseJobCrawler
from adapters.job_crawlers.saramin_crawler import SaraminCrawler
from adapters.job_crawlers.jobkorea_crawler import JobKoreaCrawler
from adapters.job_crawlers.wanted_crawler import WantedCrawler
from schemas.jobs import (
    JobSource,
    JobPosting,
)


class CrawlerService:
    """채용공고 크롤링 서비스 - 여러 소스 오케스트레이션"""

    def __init__(self):
        self._crawlers: dict[JobSource, BaseJobCrawler] = {}
        self._initialized = False

    def _init_crawlers(self) -> None:
        """크롤러 초기화 (lazy)"""
        if self._initialized:
            return

        self._crawlers = {
            JobSource.SARAMIN: SaraminCrawler(),
            JobSource.JOBKOREA: JobKoreaCrawler(),
            JobSource.WANTED: WantedCrawler(),
        }
        self._initialized = True

    async def get_detail(self, source: JobSource, source_id: str) -> JobPosting | None:
        """특정 소스에서 상세 조회"""
        self._init_crawlers()

        crawler = self._crawlers.get(source)
        if not crawler:
            return None

        return await crawler.get_detail(source_id)

    def _detect_source_from_url(self, url: str) -> tuple[JobSource | None, str | None]:
        """URL에서 소스와 ID 자동 감지"""
        parsed = urlparse(url)
        domain = parsed.netloc.lower()

        # 사람인
        if "saramin.co.kr" in domain:
            # rec_idx 파라미터 또는 URL 경로에서 ID 추출
            match = re.search(r"rec_idx=(\d+)", url)
            if match:
                return JobSource.SARAMIN, match.group(1)
            # /zf_user/jobs/relay/view/숫자 형태
            match = re.search(r"/view/(\d+)", parsed.path)
            if match:
                return JobSource.SARAMIN, match.group(1)
            return JobSource.SARAMIN, None

        # 잡코리아
        if "jobkorea.co.kr" in domain:
            # /Recruit/GI_Read/숫자 형태
            match = re.search(r"/GI_Read/(\d+)", parsed.path)
            if match:
                return JobSource.JOBKOREA, match.group(1)
            return JobSource.JOBKOREA, None

        # 원티드
        if "wanted.co.kr" in domain:
            # /wd/숫자 형태
            match = re.search(r"/wd/(\d+)", parsed.path)
            if match:
                return JobSource.WANTED, match.group(1)
            return JobSource.WANTED, None

        return None, None

    async def parse_url(self, url: str) -> JobPosting | None:
        """URL에서 채용공고 상세 정보 파싱"""
        self._init_crawlers()

        source, source_id = self._detect_source_from_url(url)

        if not source:
            return None

        crawler = self._crawlers.get(source)
        if not crawler:
            return None

        # source_id가 있으면 상세 조회, 없으면 URL 직접 파싱
        if source_id:
            return await crawler.get_detail(source_id)
        else:
            return await crawler.parse_from_url(url)

    async def close(self) -> None:
        """모든 크롤러 정리"""
        for crawler in self._crawlers.values():
            await crawler.close()


# 싱글톤
_crawler_service: CrawlerService | None = None


def get_crawler_service() -> CrawlerService:
    """크롤러 서비스 싱글톤"""
    global _crawler_service
    if _crawler_service is None:
        _crawler_service = CrawlerService()
    return _crawler_service
