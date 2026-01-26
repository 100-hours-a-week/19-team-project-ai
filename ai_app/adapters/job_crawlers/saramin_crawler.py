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
            script_match = re.search(
                r"companyNm\s*=\s*'([^']+)'", main_html
            )
            if script_match and not company_name:
                company_name = script_match.group(1)

            category_match = re.search(
                r"jobCategoryNm\s*=\s*'([^']+)'", main_html
            )
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
                parsed = self._parse_job_content_text(full_text)
                responsibilities = parsed.get("responsibilities", [])
                qualifications = parsed.get("qualifications", [])
                preferred_qualifications = parsed.get("preferred", [])
                benefits = parsed.get("benefits", [])
                hiring_process = parsed.get("process", [])
                etc = parsed.get("etc", [])

                # 마감일/근무지 추출
                if not deadline or not location:
                    deadline_location = parsed.get("deadline_location", {})
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

    def _extract_list_items(self, element) -> list[str]:
        """HTML 요소에서 리스트 아이템 추출"""
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
        lines = [line.strip() for line in text.split("\n") if line.strip()]

        for line in lines:
            # - 또는 • 로 시작하는 항목 정리
            line = re.sub(r"^[-•·]\s*", "", line)
            if line and len(line) > 1:
                items.append(line)

        return items

    def _parse_job_content_text(self, text: str) -> dict:
        """전체 텍스트에서 섹션별로 파싱"""
        result = {
            "responsibilities": [],
            "qualifications": [],
            "preferred": [],
            "benefits": [],
            "process": [],
            "etc": [],
            "deadline_location": {},
        }

        current_section = None
        lines = text.split("\n")

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # 섹션 헤더 감지 (정확한 매칭)
            if "주요업무" in line:
                current_section = "responsibilities"
                continue
            elif "자격요건" in line:
                current_section = "qualifications"
                continue
            elif "우대사항" in line or "우대조건" in line:
                current_section = "preferred"
                continue
            elif "마감일 및 근무지" in line or "마감일" in line and "근무지" in line:
                current_section = "deadline_location"
                continue
            elif "복지 및 혜택" in line or "복리후생" in line:
                current_section = "benefits"
                continue
            elif "채용절차" in line or "전형절차" in line:
                current_section = "process"
                continue
            elif "모집부문" in line or "상세내용" in line or "사용 기술" in line:
                current_section = "etc"
                continue
            elif "서비스 소개" in line or "회사 소개" in line:
                current_section = "company_intro"
                continue

            # 현재 섹션에 내용 추가
            if current_section and len(line) > 1:
                # - 또는 • 등 제거
                clean_line = re.sub(r"^[-•·]\s*", "", line)
                # 숫자. 형태 제거
                clean_line = re.sub(r"^\d+\.\s*", "", clean_line)

                if not clean_line:
                    continue

                if current_section == "deadline_location":
                    if "마감일" in clean_line:
                        match = re.search(r"마감일\s*[:：]\s*(.+)", clean_line)
                        if match:
                            result["deadline_location"]["deadline"] = match.group(1).strip()
                        else:
                            result["deadline_location"]["deadline"] = clean_line.replace("마감일", "").strip(" :：")
                    elif "근무지" in clean_line:
                        # 근무지 뒤에 주소가 같은 줄에 있는 경우
                        match = re.search(r"근무지\s*[:：]?\s*[-]?\s*(.+)", clean_line)
                        if match and match.group(1).strip():
                            result["deadline_location"]["location"] = match.group(1).strip()
                        # 근무지만 있는 경우 (주소는 다음 줄)
                    elif not result["deadline_location"].get("location"):
                        # 근무지 키워드 없이 주소가 오는 경우 (이전 줄이 "근무지"였을 때)
                        # 주소 패턴 확인 (서울, 경기 등으로 시작하거나 지역명 포함)
                        if any(loc in clean_line for loc in ["서울", "경기", "부산", "대구", "인천", "광주", "대전", "울산", "세종", "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주"]):
                            result["deadline_location"]["location"] = clean_line
                elif current_section == "company_intro":
                    # 회사 소개는 스킵
                    continue
                elif current_section in result and isinstance(result[current_section], list):
                    result[current_section].append(clean_line)

        return result
