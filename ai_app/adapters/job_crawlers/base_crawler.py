"""채용공고 크롤러 기본 클래스"""

import asyncio
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx
from schemas.jobs import JobPosting, JobSource

if TYPE_CHECKING:
    from bs4 import Tag

# 한국 지역명 상수
KOREAN_REGIONS = frozenset(
    {
        "서울",
        "경기",
        "부산",
        "대구",
        "인천",
        "광주",
        "대전",
        "울산",
        "세종",
        "강원",
        "충북",
        "충남",
        "전북",
        "전남",
        "경북",
        "경남",
        "제주",
    }
)

# 섹션 키워드 매핑
SECTION_KEYWORDS = {
    "responsibilities": ["주요업무", "담당업무", "업무내용"],
    "qualifications": ["자격요건", "필수요건", "지원자격"],
    "preferred": ["우대사항", "우대조건"],
    "benefits": ["복리후생", "복지", "혜택", "복지 및 혜택"],
    "process": ["전형절차", "채용절차"],
    "etc": ["모집부문", "상세내용", "사용 기술"],
    "company_intro": ["서비스 소개", "회사 소개"],
    "deadline_location": ["마감일 및 근무지"],
}


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
                await asyncio.sleep(2**attempt)  # exponential backoff

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

    # ========== 공통 파싱 유틸리티 ==========

    def _parse_text_to_list(self, text: str, min_length: int = 2) -> list[str]:
        """텍스트를 줄 단위로 리스트로 변환

        Args:
            text: 파싱할 텍스트
            min_length: 최소 라인 길이 (기본: 2)

        Returns:
            정리된 텍스트 리스트
        """
        if not text:
            return []

        items = []
        lines = text.split("\n")

        for line in lines:
            line = line.strip()
            if not line or len(line) < min_length:
                continue

            # 불릿 포인트 제거 (-, •, ·, *)
            line = re.sub(r"^[-•·\*]\s*", "", line)
            # 숫자. 형태 제거 (1., 2. 등)
            line = re.sub(r"^\d+\.\s*", "", line)

            if line:
                items.append(line)

        return items

    def _extract_list_items_from_element(self, element: "Tag") -> list[str]:
        """HTML 요소에서 리스트 아이템 추출

        Args:
            element: BeautifulSoup Tag 요소

        Returns:
            추출된 텍스트 리스트
        """
        items = []

        # li 태그 먼저 확인
        li_items = element.select("li")
        if li_items:
            for li in li_items:
                text = li.get_text(strip=True)
                if text and len(text) > 1:
                    items.append(text)
            return items

        # br 태그로 분리된 텍스트
        text = element.get_text("\n", strip=True)
        return self._parse_text_to_list(text, min_length=2)

    def _parse_job_content_text(self, text: str) -> dict[str, list[str] | dict[str, str]]:
        """전체 텍스트에서 섹션별로 파싱

        Args:
            text: 파싱할 전체 텍스트

        Returns:
            섹션별로 파싱된 딕셔너리
        """
        result: dict[str, list[str] | dict[str, str]] = {
            "responsibilities": [],
            "qualifications": [],
            "preferred": [],
            "benefits": [],
            "process": [],
            "etc": [],
            "deadline_location": {},
        }

        current_section: str | None = None
        lines = text.split("\n")

        for line in lines:
            line = line.strip()
            if not line:
                continue

            line_lower = line.lower()

            # 섹션 헤더 감지
            section_found = False
            for section_key, keywords in SECTION_KEYWORDS.items():
                if any(kw in line_lower for kw in keywords):
                    current_section = section_key
                    section_found = True
                    break

            if section_found:
                continue

            # 현재 섹션에 내용 추가
            if current_section and len(line) > 1:
                clean_line = re.sub(r"^[-•·]\s*", "", line)
                clean_line = re.sub(r"^\d+\.\s*", "", clean_line)

                if not clean_line:
                    continue

                if current_section == "deadline_location":
                    self._parse_deadline_location_line(clean_line, result)
                elif current_section == "company_intro":
                    # 회사 소개는 스킵
                    continue
                elif current_section in result:
                    section_data = result[current_section]
                    if isinstance(section_data, list):
                        section_data.append(clean_line)

        return result

    def _parse_deadline_location_line(self, line: str, result: dict[str, list[str] | dict[str, str]]) -> None:
        """마감일/근무지 라인 파싱

        Args:
            line: 파싱할 라인
            result: 결과를 저장할 딕셔너리
        """
        deadline_location = result.get("deadline_location", {})
        if not isinstance(deadline_location, dict):
            return

        if "마감일" in line:
            match = re.search(r"마감일\s*[:：]\s*(.+)", line)
            if match:
                deadline_location["deadline"] = match.group(1).strip()
            else:
                deadline_location["deadline"] = line.replace("마감일", "").strip(" :：")
        elif "근무지" in line:
            match = re.search(r"근무지\s*[:：]?\s*[-]?\s*(.+)", line)
            if match and match.group(1).strip():
                deadline_location["location"] = match.group(1).strip()
        elif not deadline_location.get("location"):
            # 지역명 패턴 확인
            if any(loc in line for loc in KOREAN_REGIONS):
                deadline_location["location"] = line

        result["deadline_location"] = deadline_location
