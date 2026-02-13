"""채용공고 파서 - URL/텍스트에서 채용 정보 추출

service.md 스펙:
- 실시간 공고 URL은 Playwright로 파싱하여 즉시 컨텍스트화
- LLM을 통한 구조화 추출
"""

import logging
from typing import Any

from adapters.llm_client import get_llm_client
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ============== LLM 추출 스키마 ==============


class ExtractedJobPosting(BaseModel):
    """LLM이 추출하는 채용공고 구조"""

    responsibilities: list[str] = Field(default_factory=list, description="주요 업무/담당 업무")
    qualifications: list[str] = Field(default_factory=list, description="자격 요건 (필수)")
    preferred_qualifications: list[str] = Field(default_factory=list, description="우대 조건 (선택)")
    tech_stack: list[str] = Field(
        default_factory=list, description="사용 기술/기술 스택 (예: React, Spring Boot, Docker 등)"
    )
    benefits: list[str] = Field(default_factory=list, description="복지 및 혜택 (복리후생, 근무 환경 등)")
    hiring_process: list[str] = Field(default_factory=list, description="채용 절차/전형")
    etc: list[str] = Field(default_factory=list, description="기타 (유의사항, 분류 불가 정보)")


# ============== 채용공고 파싱 시스템 프롬프트 ==============

JOB_PARSING_SYSTEM_PROMPT = """당신은 채용공고 분석 전문가입니다.
주어진 채용공고 텍스트에서 구조화된 정보를 추출합니다.

추출 규칙:
1. 명시적으로 언급된 정보만 추출합니다
2. 불확실하면 빈 리스트로 남깁니다
3. 섹션 헤더가 표준적이지 않아도 (예: "함께 할 직무", "이런 분을 찾아요") 내용을 보고 적절한 필드에 분류합니다
4. responsibilities: 주요 업무, 담당 업무, 역할, 직무 내용
5. qualifications: 자격 요건, 필수 조건, 지원 자격, 필요 역량
6. preferred_qualifications: 우대 사항, 우대 조건, 이런 분이면 더 좋아요
7. tech_stack: 사용 기술, 기술 스택, 개발 환경 (예: React, Spring Boot, Docker 등 기술명 위주로 추출)
8. benefits: 복지 및 혜택, 복리후생 (고용형태, 급여, 근무지는 제외)
9. hiring_process: 전형 절차, 채용 과정, 접수 기간/방법
10. etc: 유의사항, 분류하기 어려운 정보
10. 각 항목은 간결하게 한 줄로 정리합니다
"""


async def parse_job_content_with_llm(text: str) -> dict[str, list[str]]:
    """LLM을 사용하여 채용공고 텍스트에서 섹션별 정보 추출

    키워드 매칭 실패 시 fallback으로 사용됩니다.

    Args:
        text: 채용공고 텍스트

    Returns:
        섹션별 파싱 결과 딕셔너리
    """
    logger.info("LLM fallback 파싱 시작")

    llm = get_llm_client()

    prompt = f"""다음 채용공고 텍스트에서 구조화된 정보를 추출하세요:

<채용공고>
{text[:8000]}
</채용공고>

JSON 형식으로 응답하세요."""

    try:
        result = await llm.generate_json(
            prompt=prompt,
            system_instruction=JOB_PARSING_SYSTEM_PROMPT,
            response_schema=ExtractedJobPosting,
            temperature=0.1,
        )

        logger.info(
            f"LLM fallback 파싱 완료 - responsibilities: {len(result.get('responsibilities', []))}개, "
            f"qualifications: {len(result.get('qualifications', []))}개"
        )
        return result

    except Exception as e:
        logger.error(f"LLM fallback 파싱 실패: {e}")
        return {
            "responsibilities": [],
            "qualifications": [],
            "preferred_qualifications": [],
            "tech_stack": [],
            "benefits": [],
            "hiring_process": [],
            "etc": [],
        }


async def parse_job_from_url(job_url: str) -> dict[str, Any]:
    """URL에서 채용공고 파싱

    Args:
        job_url: 채용공고 URL

    Returns:
        파싱된 채용공고 정보
    """
    logger.info(f"채용공고 URL 파싱 시작: {job_url}")

    # Playwright로 웹 페이지 텍스트 추출
    job_text = await _fetch_page_content(job_url)

    if not job_text:
        logger.warning(f"URL에서 텍스트 추출 실패: {job_url}")
        return {"success": False, "error": "페이지 텍스트 추출 실패"}

    # LLM으로 구조화 추출
    return await parse_job_from_text(job_text)


async def parse_job_from_text(job_text: str) -> dict[str, Any]:
    """텍스트에서 채용공고 파싱

    Args:
        job_text: 채용공고 텍스트

    Returns:
        파싱된 채용공고 정보
    """
    logger.info("채용공고 텍스트 파싱 시작")

    try:
        result = await parse_job_content_with_llm(job_text)
        return {
            "success": True,
            "data": result,
        }

    except Exception as e:
        logger.error(f"채용공고 파싱 실패: {e}")
        return {"success": False, "error": str(e)}


async def _fetch_page_content(url: str) -> str | None:
    """Playwright로 웹 페이지 텍스트 추출

    Args:
        url: 웹 페이지 URL

    Returns:
        추출된 텍스트 또는 None
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.warning("Playwright not installed. Using httpx fallback.")
        return await _fetch_page_content_httpx(url)

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()

            await page.goto(url, wait_until="networkidle", timeout=30000)
            content = await page.inner_text("body")

            await browser.close()
            return content

    except Exception as e:
        logger.error(f"Playwright 페이지 로드 실패: {e}")
        return await _fetch_page_content_httpx(url)


async def _fetch_page_content_httpx(url: str) -> str | None:
    """httpx로 웹 페이지 텍스트 추출 (Fallback)

    Args:
        url: 웹 페이지 URL

    Returns:
        추출된 텍스트 또는 None
    """
    import re
    from html import unescape

    import httpx

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url)
            response.raise_for_status()

            html = response.text
            # 간단한 HTML 태그 제거
            text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL)
            text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
            text = re.sub(r"<[^>]+>", " ", text)
            text = unescape(text)
            text = re.sub(r"\s+", " ", text).strip()

            return text

    except Exception as e:
        logger.error(f"httpx 페이지 로드 실패: {e}")
        return None
