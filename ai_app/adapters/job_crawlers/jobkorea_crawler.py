"""잡코리아 채용공고 크롤러"""

from bs4 import BeautifulSoup
from schemas.jobs import CompanyInfo, JobPosting, JobSource, SalaryInfo

from adapters.job_crawlers.base_crawler import BaseJobCrawler, CrawlerConfig


class JobKoreaCrawler(BaseJobCrawler):
    """잡코리아 HTML 파싱 크롤러"""

    source = JobSource.JOBKOREA

    def __init__(self, config: CrawlerConfig | None = None):
        if config is None:
            config = CrawlerConfig(
                base_url="https://www.jobkorea.co.kr",
                rate_limit_delay=1.5,
            )
        super().__init__(config)

    async def get_detail(self, source_id: str) -> JobPosting | None:
        """채용공고 상세 조회"""
        url = f"{self.config.base_url}/Recruit/GI_Read/{source_id}"
        html = await self._fetch(url)

        if not html:
            return None

        return self._parse_detail_page(html, source_id, url)

    def _parse_detail_page(self, html: str, source_id: str, url: str) -> JobPosting | None:
        """상세 페이지 HTML 파싱"""
        soup = BeautifulSoup(html, "lxml")

        # 제목
        title_elem = soup.select_one(".titWrap .tit")
        title = title_elem.get_text(strip=True) if title_elem else ""

        # 회사명
        company_elem = soup.select_one(".coName")
        company_name = company_elem.get_text(strip=True) if company_elem else ""

        # 기본 정보 파싱
        location = ""
        experience = ""
        education = ""
        job_type = ""
        deadline = ""
        salary_text = ""

        # 요약 정보 테이블
        summary_table = soup.select(".tbRow tr")
        for row in summary_table:
            th = row.select_one("th")
            td = row.select_one("td")
            if th and td:
                th_text = th.get_text(strip=True)
                td_text = td.get_text(strip=True)

                if "경력" in th_text:
                    experience = td_text
                elif "학력" in th_text:
                    education = td_text
                elif "고용형태" in th_text or "근무형태" in th_text:
                    job_type = td_text
                elif "급여" in th_text:
                    salary_text = td_text
                elif "근무지역" in th_text or "지역" in th_text:
                    location = td_text
                elif "마감" in th_text:
                    deadline = td_text

        # 상세 정보 섹션 파싱
        responsibilities = []
        qualifications = []
        preferred_qualifications = []
        benefits = []
        hiring_process = []
        etc = []

        # 직무 상세 영역
        detail_sections = soup.select(".tbCol")
        for section in detail_sections:
            header = section.select_one("th, .tit")
            content = section.select_one("td, .cont")

            if header and content:
                header_text = header.get_text(strip=True).lower()
                items = self._extract_list_items_from_element(content)

                # BaseJobCrawler의 공통 메서드 사용
                if any(kw in header_text for kw in ["주요업무", "담당업무", "업무내용"]):
                    responsibilities = items
                elif any(kw in header_text for kw in ["자격요건", "필수", "지원자격"]):
                    qualifications = items
                elif any(kw in header_text for kw in ["우대"]):
                    preferred_qualifications = items
                elif any(kw in header_text for kw in ["복리후생", "복지", "혜택"]):
                    benefits = items
                elif any(kw in header_text for kw in ["전형절차", "채용절차"]):
                    hiring_process = items

        # 상세 정보가 분리되지 않은 경우 - BaseJobCrawler의 공통 메서드 사용
        if not responsibilities and not qualifications:
            detail_content = soup.select_one(".artReadJobSum, .rcrtJobSum")
            if detail_content:
                full_text = detail_content.get_text("\n", strip=True)
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

        # 복리후생 별도 영역
        if not benefits:
            welfare_section = soup.select_one(".welfareWrap")
            if welfare_section:
                benefits = self._extract_list_items_from_element(welfare_section)

        # 직무 카테고리
        job_categories = []
        category_elem = soup.select_one(".tbCol .job")
        if category_elem:
            categories_text = category_elem.get_text(strip=True)
            job_categories = [c.strip() for c in categories_text.split(",") if c.strip()][:3]

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
