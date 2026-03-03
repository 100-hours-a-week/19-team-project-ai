"""범용 채용공고 크롤러 - LLM(Gemini) 활용"""

import logging

from schemas.jobs import CompanyInfo, JobPosting, JobSource, JobType

from adapters.job_crawlers.base_crawler import BaseJobCrawler, CrawlerConfig
from adapters.llm_client import get_llm_client

logger = logging.getLogger(__name__)


class GeneralCrawler(BaseJobCrawler):
    """모든 도메인을 위한 LLM 기반 범용 크롤러"""

    source = JobSource.GENERAL

    def __init__(self, config: CrawlerConfig | None = None):
        super().__init__(config)
        self.llm_client = get_llm_client()

    async def get_detail(self, source_id: str) -> JobPosting | None:
        """범용 크롤러는 ID 기반 조회를 지원하지 않음 (URL 직접 파싱 필요)"""
        return None

    async def parse_from_url(self, url: str) -> JobPosting | None:
        """URL에서 HTML을 가져와 Gemini로 구조화된 데이터 추출"""
        html = await self._fetch(url)
        if not html:
            logger.error(f"Failed to fetch content from {url}")
            return None

        # HTML 내 실제 본문 텍스트만 추출 (너무 크면 LLM 비용/성능 이슈 방지)
        # BeautifulSoup을 사용하여 스크립트, 스타일 태그 등 제거
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "lxml")

        # 불필요한 태그 제거
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()

        # 텍스트 추출 (여백 정리)
        body_text = soup.get_text(separator="\n", strip=True)

        # 너무 길 경우 제한 (Gemini 콘텍스트 윈도우 고려)
        if len(body_text) > 30000:
            body_text = body_text[:30000] + "..."

        system_prompt = (
            "당신은 구인구직 사이트의 채용공고를 분석하는 전문가입니다.\n"
            "입력된 웹페이지 텍스트에서 채용공고 정보를 추출하여 JSON 형식으로 응답하세요.\n"
            "추출할 항목: 제목(title), 회사명(company_name), 업종(industry), 위치(location), "
            "고용형태(job_type: 정규직, 계약직, 상관없음 중 하나), "
            "경력사항(experience_level), 학력사항(education), "
            "급여정보(salary_text), 주요업무(responsibilities: 리스트), "
            "자격요건(qualifications: 리스트), 우대사항(preferred: 리스트), "
            "기술스택(tech_stack: 리스트), 복지(benefits: 리스트), "
            "채용절차(process: 리스트), 마감일(deadline).\n"
            "만약 특정 정보를 찾을 수 없다면 null 또는 빈 리스트를 반환하세요."
        )

        user_prompt = f"다음은 채용공고 웹페이지 텍스트입니다:\n\n{body_text}\n\n원본 URL: {url}"

        try:
            # LLM 호출
            raw_data = await self.llm_client.generate_json(
                prompt=user_prompt, system_instruction=system_prompt, temperature=0.1
            )

            # JobPosting 모델로 변환
            # 모델 필드명에 맞게 매핑
            return JobPosting(
                source=self.source,
                source_id=url,  # 범용은 URL을 ID로 사용
                title=raw_data.get("title") or "제목 없음",
                company=CompanyInfo(
                    name=raw_data.get("company_name") or "회사명 미상",
                    industry=raw_data.get("industry"),
                    location=raw_data.get("location"),
                ),
                job_type=self._map_job_type(raw_data.get("job_type")),
                job_category=[],  # LLM에서 추론하기 어려울 수 있으므로 비움
                experience_level=raw_data.get("experience_level"),
                education=raw_data.get("education"),
                salary=None if not raw_data.get("salary_text") else {"text": raw_data.get("salary_text")},
                location=raw_data.get("location"),
                responsibilities=raw_data.get("responsibilities") or [],
                qualifications=raw_data.get("qualifications") or [],
                preferred_qualifications=raw_data.get("preferred") or [],
                tech_stack=raw_data.get("tech_stack") or [],
                benefits=raw_data.get("benefits") or [],
                hiring_process=raw_data.get("process") or [],
                deadline=raw_data.get("deadline"),
                url=url,
            )
        except Exception as e:
            logger.error(f"Gemini parsing failed for {url}: {e}")
            return None

    def _map_job_type(self, jt_str: str | None) -> JobType:
        if not jt_str:
            return JobType.ANY
        if "정규" in jt_str:
            return JobType.FULL_TIME
        if "계약" in jt_str:
            return JobType.CONTRACT
        return JobType.ANY
