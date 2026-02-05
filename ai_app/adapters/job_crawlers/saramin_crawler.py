"""사람인 채용공고 크롤러"""

import re

from bs4 import BeautifulSoup
from schemas.jobs import CompanyInfo, JobPosting, JobSource, SalaryInfo

from adapters.job_crawlers.base_crawler import BaseJobCrawler, CrawlerConfig


class SaraminCrawler(BaseJobCrawler):
    """사람인 HTML 파싱 크롤러"""

    source = JobSource.SARAMIN

    def __init__(self, config: CrawlerConfig | None = None):
        if config is None:
            config = CrawlerConfig(
                base_url="https://www.saramin.co.kr",
                rate_limit_delay=1.5,
            )
        super().__init__(config)

    async def get_detail(self, source_id: str) -> JobPosting | None:
        """채용공고 상세 조회"""
        # 메인 페이지에서 기본 정보 추출
        main_url = f"{self.config.base_url}/zf_user/jobs/relay/view?rec_idx={source_id}"
        main_html = await self._fetch(main_url)

        # 상세 페이지에서 직무 내용 추출
        detail_url = f"{self.config.base_url}/zf_user/jobs/relay/view-detail?rec_idx={source_id}"
        detail_html = await self._fetch(detail_url)

        if not main_html and not detail_html:
            return None

        return self._parse_detail_page(main_html, detail_html, source_id, main_url)

    def _parse_detail_page(
        self, main_html: str | None, detail_html: str | None, source_id: str, url: str
    ) -> JobPosting | None:
        """상세 페이지 HTML 파싱"""
        title = ""
        company_name = ""
        location = ""
        experience = ""
        education = ""
        job_type = ""
        deadline = ""
        salary_text = ""
        job_categories = []

        # 메인 페이지에서 기본 정보 추출
        if main_html:
            main_soup = BeautifulSoup(main_html, "lxml")

            # title 태그에서 제목과 회사명 추출
            title_tag = main_soup.select_one("title")
            if title_tag:
                title_text = title_tag.get_text(strip=True)
                # [(주)인졀미] [신입] Flutter 앱 & Node.js 개발자(D-5) - 사람인
                match = re.match(r"\[([^\]]+)\]\s*(.+?)\s*-\s*사람인", title_text)
                if match:
                    company_name = match.group(1)
                    title = match.group(2).strip()
                    # (D-5) 같은 마감일 표시 제거
                    title = re.sub(r"\(D-\d+\)$", "", title).strip()

            # meta description에서 추가 정보 추출
            meta_desc = main_soup.select_one('meta[name="description"]')
            if meta_desc:
                desc_content = meta_desc.get("content", "")
                # 경력:신입, 학력:학력무관, 면접 후 결정, 마감일:2026-01-31
                if "경력:" in desc_content:
                    match = re.search(r"경력:([^,]+)", desc_content)
                    if match:
                        experience = match.group(1).strip()
                if "학력:" in desc_content:
                    match = re.search(r"학력:([^,]+)", desc_content)
                    if match:
                        education = match.group(1).strip()
                if "마감일:" in desc_content:
                    match = re.search(r"마감일:([^,]+)", desc_content)
                    if match:
                        deadline = match.group(1).strip()

            # JavaScript 변수에서 추가 정보 추출
            script_match = re.search(r"companyNm\s*=\s*'([^']+)'", main_html)
            if script_match and not company_name:
                company_name = script_match.group(1)

            category_match = re.search(r"jobCategoryNm\s*=\s*'([^']+)'", main_html)
            if category_match:
                categories = category_match.group(1).split(",")
                job_categories = [c.strip() for c in categories[:5] if c.strip()]

        # 상세 정보 섹션 파싱
        responsibilities = []
        qualifications = []
        preferred_qualifications = []
        benefits = []
        hiring_process = []
        etc = []

        # 상세 페이지에서 직무 내용 추출
        if detail_html:
            detail_soup = BeautifulSoup(detail_html, "lxml")
            user_content = detail_soup.select_one(".user_content")

            if user_content:
                full_text = user_content.get_text("\n", strip=True)
                # BaseJobCrawler의 공통 메서드 사용
                parsed = self._parse_job_content_text(full_text)
                resp = parsed.get("responsibilities")
                responsibilities = resp if isinstance(resp, list) else []
                qual = parsed.get("qualifications")
                qualifications = qual if isinstance(qual, list) else []
                pref = parsed.get("preferred")
                preferred_qualifications = pref if isinstance(pref, list) else []
                ben = parsed.get("benefits")
                benefits = ben if isinstance(ben, list) else []
                proc = parsed.get("process")
                hiring_process = proc if isinstance(proc, list) else []
                et = parsed.get("etc")
                etc = et if isinstance(et, list) else []

                # 마감일/근무지 추출
                if not deadline or not location:
                    dl_loc = parsed.get("deadline_location", {})
                    deadline_location = dl_loc if isinstance(dl_loc, dict) else {}
                    if not deadline:
                        deadline = deadline_location.get("deadline", "")
                    if not location:
                        location = deadline_location.get("location", "")

        return JobPosting(
            source=self.source,
            source_id=source_id,
            title=title,
            company=CompanyInfo(name=company_name, location=location),
            job_type=job_type,
            job_category=job_categories,
            experience_level=experience,
            education=education,
            salary=SalaryInfo(text=salary_text) if salary_text else None,
            location=location,
            responsibilities=responsibilities,
            qualifications=qualifications,
            preferred_qualifications=preferred_qualifications,
            benefits=benefits,
            hiring_process=hiring_process,
            etc=etc,
            deadline=deadline,
            url=url,
        )
