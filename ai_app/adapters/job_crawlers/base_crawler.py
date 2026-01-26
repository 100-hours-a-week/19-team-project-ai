"""채용공고 크롤러 기본 클래스"""

import asyncio
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx
from schemas.jobs import JobPosting, JobSource


@dataclass
class CrawlerConfig:
    """크롤러 설정"""

    base_url: str = ""
    timeout: float = 30.0
    max_retries: int = 3
    rate_limit_delay: float = 1.0  # 요청 간 대기 시간 (초)


class BaseJobCrawler(ABC):
    """채용공고 크롤러 추상 기본 클래스"""

    source: JobSource

    def __init__(self, config: CrawlerConfig | None = None):
        self.config = config or CrawlerConfig()
        self._client: httpx.AsyncClient | None = None
        self._last_request_time: float = 0

    async def _get_client(self) -> httpx.AsyncClient:
        """HTTP 클라이언트 (lazy init)"""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.config.timeout,
                headers=self._get_default_headers(),
                follow_redirects=True,
            )
        return self._client

    def _get_default_headers(self) -> dict[str, str]:
        """기본 HTTP 헤더"""
        return {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        }

    async def _rate_limit(self) -> None:
        """Rate limiting 적용"""
        elapsed = time.time() - self._last_request_time
        wait_time = self.config.rate_limit_delay - elapsed
        if wait_time > 0:
            await asyncio.sleep(wait_time)
        self._last_request_time = time.time()

    async def _fetch(self, url: str, params: dict | None = None) -> str | None:
        """URL에서 HTML 가져오기 (retry 포함)"""
        client = await self._get_client()

        for attempt in range(self.config.max_retries):
            try:
                await self._rate_limit()
                response = await client.get(url, params=params)
                response.raise_for_status()
                return response.text
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 403:
                    return None  # 접근 거부
                if attempt == self.config.max_retries - 1:
                    raise
            except (httpx.TimeoutException, httpx.NetworkError):
                if attempt == self.config.max_retries - 1:
                    raise
                await asyncio.sleep(2 ** attempt)  # exponential backoff

        return None

    @abstractmethod
    async def get_detail(self, source_id: str) -> JobPosting | None:
        """채용공고 상세 조회"""
        pass

    async def parse_from_url(self, url: str) -> JobPosting | None:
        """URL에서 직접 파싱 (기본 구현: get_detail 호출)"""
        # 서브클래스에서 필요시 오버라이드
        return None

    async def close(self) -> None:
        """클라이언트 정리"""
        if self._client:
            await self._client.aclose()
            self._client = None
