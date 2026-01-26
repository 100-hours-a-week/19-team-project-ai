"""원티드 채용공고 크롤러"""

import re

from schemas.jobs import CompanyInfo, JobPosting, JobSource

from adapters.job_crawlers.base_crawler import BaseJobCrawler, CrawlerConfig


class WantedCrawler(BaseJobCrawler):
    """원티드 HTML 파싱 크롤러"""

    source = JobSource.WANTED

    def __init__(self, config: CrawlerConfig | None = None):
        if config is None:
            config = CrawlerConfig(
                base_url="https://www.wanted.co.kr",
                rate_limit_delay=2.0,
            )
        super().__init__(config)

    def _get_default_headers(self) -> dict[str, str]:
        """원티드 전용 헤더"""
        headers = super()._get_default_headers()
        headers["Accept"] = "application/json, text/plain, */*"
        return headers

    async def get_detail(self, source_id: str) -> JobPosting | None:
        """채용공고 상세 조회"""
        url = f"{self.config.base_url}/api/v4/jobs/{source_id}"
        response = await self._fetch(url)

        if not response:
            return None

        import json
        try:
            data = json.loads(response)
            job = data.get("job", {})
            return self._parse_job_detail(job, source_id) if job else None
        except Exception:
            return None

    def _parse_job_detail(self, job: dict, source_id: str) -> JobPosting | None:
        """상세 API 응답 파싱"""
        if not job:
            return None

        # 회사 정보
        company = job.get("company", {})
        company_name = company.get("name", "")
        industry = company.get("industry_name", "")

        # 위치 정보
        address = job.get("address", {})
        location = address.get("full_location", "") or address.get("location", "")

        # 제목
        title = job.get("position", "")

        # 마감일
        due_time = job.get("due_time")
        deadline = due_time if due_time else "상시채용"

        # 직무 카테고리
        category = job.get("category", {})
        job_categories = []
        if category.get("name"):
            job_categories.append(category.get("name"))

        # 상세 정보 파싱
        detail = job.get("detail", {})

        # 고용 형태 (정규직, 인턴, 계약직 등)
        job_type = job.get("job_type", {}).get("name", "") or job.get("position_type", "") or "정규직"

        # 주요업무 (main_tasks)
        main_tasks = detail.get("main_tasks", "")
        responsibilities = self._parse_text_to_list(main_tasks) if main_tasks else []

        # 자격요건 (requirements)
        requirements = detail.get("requirements", "")
        qualifications = self._parse_text_to_list(requirements) if requirements else []

        # 우대사항 (preferred)
        preferred = detail.get("preferred", "")
        preferred_qualifications = self._parse_text_to_list(preferred) if preferred else []

        # 혜택 및 복지
        benefits_text = detail.get("benefits", "")
        benefits = self._parse_text_to_list(benefits_text) if benefits_text else []

        # 채용절차
        hiring_process = []
        hire_round = job.get("hire_round", [])
        if hire_round:
            hiring_process = [r.get("name", "") for r in hire_round if r.get("name")]

        # 기타 정보 (회사/서비스 소개)
        intro = detail.get("intro", "")
        etc = self._parse_text_to_list(intro) if intro else []

        return JobPosting(
            source=self.source,
            source_id=source_id,
            title=title,
            company=CompanyInfo(
                name=company_name,
                industry=industry,
                location=location,
            ),
            job_type=job_type,
            job_category=job_categories,
            location=location,
            responsibilities=responsibilities,
            qualifications=qualifications,
            preferred_qualifications=preferred_qualifications,
            benefits=benefits,
            hiring_process=hiring_process,
            etc=etc,
            deadline=deadline,
            url=f"{self.config.base_url}/wd/{source_id}",
        )

    def _parse_text_to_list(self, text: str) -> list[str]:
        """텍스트를 리스트로 파싱"""
        if not text:
            return []

        items = []
        lines = text.split("\n")

        for line in lines:
            line = line.strip()
            if not line or len(line) < 2:
                continue

            # - 또는 • 등 제거
            line = re.sub(r"^[-•·\*]\s*", "", line)
            if line:
                items.append(line)

        return items
