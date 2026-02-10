"""스코어링 서비스 - 기술 스택 커버리지 및 역량 분석"""

import logging
from typing import Any

from adapters.llm_client import get_llm_client
from pydantic import BaseModel, Field
from schemas.repo import FitLevel, FulfillmentLevel

logger = logging.getLogger(__name__)


# ============== AI 분석 결과 스키마 ==============


class RequirementAssessment(BaseModel):
    """요구사항 평가"""
    requirement: str = Field(..., description="요구사항")
    level: str = Field(..., description="충족 수준")
    reason: str = Field(..., description="판단 근거")


class AIAnalysisResult(BaseModel):
    """AI 분석 결과"""
    top_requirements: list[str] = Field(default_factory=list, description="중요 요구사항 Top 3")
    assessments: list[RequirementAssessment] = Field(default_factory=list, description="요구사항별 평가")
    strengths: list[str] = Field(default_factory=list, description="강점 2개")
    improvements: list[str] = Field(default_factory=list, description="보완점 2개")
    action_items: list[str] = Field(default_factory=list, description="2주 내 액션 2개")
    job_fit: str = Field(default="중", description="직무 적합도")
    pass_probability: str = Field(default="중", description="서류 통과 가능성")
    overall_comment: str = Field(default="", description="AI 총평")
    unverifiable_items: list[str] = Field(default_factory=list, description="확인 불가 항목")
    confidence_score: float = Field(default=70.0, description="신뢰도")
    confidence_reason: str = Field(default="", description="신뢰도 근거")


# ============== 시스템 프롬프트 ==============

ANALYSIS_SYSTEM_PROMPT = """당신은 채용 전문가입니다. 이력서와 채용공고를 분석하여 적합도를 평가합니다.

평가 규칙:
1. top_requirements: 공고에서 가장 중요한 요구사항 3개 선정
2. assessments: 각 요구사항에 대해 충족/부분충족/미충족 판단 + 구체적 근거
3. strengths: 이 공고에 특히 유리한 강점 2개
4. improvements: 보완이 필요한 점 2개
5. action_items: 2주 내 실행 가능한 구체적 액션 2개
6. job_fit: 상(잘 맞음)/중(기본은 갖춤)/하(적합도 낮음)
7. pass_probability: 상(높음)/중(보완 시 가능)/하(어려움)
8. overall_comment: 200자 이내 종합 평가
9. unverifiable_items: 이력서에서 확인 불가한 사항
10. confidence_score: 분석 신뢰도 (0-100)
"""


async def analyze_requirements(resume_data: dict, job_data: dict) -> dict[str, Any]:
    """이력서-채용공고 요구사항 분석

    Args:
        resume_data: 이력서 파싱 데이터
        job_data: 채용공고 파싱 데이터

    Returns:
        AI 분석 결과
    """
    logger.info("AI 요구사항 분석 시작")

    llm = get_llm_client()

    # company 필드는 dict 또는 str일 수 있음 (CrawlerService vs LLM parser)
    company_info = job_data.get('company', '미상')
    if isinstance(company_info, dict):
        company_name = company_info.get('name', '미상')
    else:
        company_name = company_info

    prompt = f"""다음 이력서와 채용공고를 분석하세요:

<이력서>
{_format_resume(resume_data)}
</이력서>

<채용공고>
포지션: {job_data.get('title', '미상')}
회사: {company_name}
요구 경력: {job_data.get('experience_level') or job_data.get('experience_required', '미상')}
주요 업무: {', '.join(job_data.get('responsibilities', []))}
자격 요건: {', '.join(job_data.get('qualifications', []))}
우대 사항: {', '.join(job_data.get('preferred_qualifications', []))}
근무조건/복지: {', '.join(job_data.get('benefits', []))}
</채용공고>

분석 결과를 JSON 형식으로 응답하세요."""

    try:
        result = await llm.generate_json(
            prompt=prompt,
            system_instruction=ANALYSIS_SYSTEM_PROMPT,
            response_schema=AIAnalysisResult,
            temperature=0.2,
        )

        # 문자열 → Enum 변환
        fit_map = {"상": FitLevel.HIGH, "중": FitLevel.MEDIUM, "하": FitLevel.LOW}
        level_map = {"충족": FulfillmentLevel.FULFILLED, "부분충족": FulfillmentLevel.PARTIAL, "미충족": FulfillmentLevel.NOT_FULFILLED}

        result["job_fit"] = fit_map.get(result.get("job_fit", "중"), FitLevel.MEDIUM)
        result["pass_probability"] = fit_map.get(result.get("pass_probability", "중"), FitLevel.MEDIUM)

        # assessments를 dict로 변환
        assessments_dict = {}
        for a in result.get("assessments", []):
            req = a.get("requirement", "")
            assessments_dict[req] = {
                "level": level_map.get(a.get("level", "미충족"), FulfillmentLevel.NOT_FULFILLED),
                "reason": a.get("reason", ""),
            }
        result["assessments"] = assessments_dict

        logger.info("AI 분석 완료")
        return result

    except Exception as e:
        logger.error(f"AI 분석 실패: {e}")
        return {
            "top_requirements": [],
            "assessments": {},
            "strengths": [],
            "improvements": [],
            "action_items": [],
            "job_fit": FitLevel.MEDIUM,
            "pass_probability": FitLevel.MEDIUM,
            "overall_comment": "분석 중 오류가 발생했습니다.",
            "unverifiable_items": [],
            "confidence_score": 0.0,
            "confidence_reason": str(e),
        }


async def analyze_tech_coverage(resume_data: dict, job_data: dict) -> dict[str, Any]:
    """기술 스택 커버리지 분석

    Args:
        resume_data: 이력서 데이터
        job_data: 채용공고 데이터

    Returns:
        기술 커버리지 분석 결과
    """
    logger.info("기술 스택 커버리지 분석 시작")

    # 공고의 자격요건에서 기술 추출
    required_techs = set(t.lower() for t in job_data.get("qualifications", []))
    preferred_techs = set()

    # 우대사항에서 기술 추출
    for pref in job_data.get("preferred_qualifications", []):
        preferred_techs.add(pref.lower())

    # 이력서 기술 (프로젝트/경력에서 추출)
    owned_techs = set()
    for exp in resume_data.get("work_experience", []):
        if isinstance(exp, dict):
            for tech in exp.get("technologies", []):
                owned_techs.add(tech.lower())
        elif isinstance(exp, str):
            owned_techs.add(exp.lower())

    for proj in resume_data.get("projects", []):
        if isinstance(proj, dict):
            for tech in proj.get("technologies", []):
                owned_techs.add(tech.lower())
        elif isinstance(proj, str):
            owned_techs.add(proj.lower())

    # 커버리지 계산
    if required_techs:
        matched = required_techs & owned_techs
        coverage_rate = (len(matched) / len(required_techs)) * 100
    else:
        coverage_rate = 0.0

    missing_required = list(required_techs - owned_techs)
    missing_preferred = list(preferred_techs - owned_techs)

    logger.info(f"기술 커버리지: {coverage_rate:.1f}%")

    return {
        "coverage_rate": round(coverage_rate, 1),
        "missing_required": missing_required,
        "missing_preferred": missing_preferred,
        "matched_techs": list(required_techs & owned_techs),
    }


def _format_resume(resume_data: dict) -> str:
    """이력서 데이터를 텍스트로 포맷"""
    parts = []

    if resume_data.get("title"):
        parts.append(f"제목: {resume_data['title']}")

    work_exp = resume_data.get("work_experience", [])
    if work_exp:
        parts.append(f"경력: {len(work_exp)}건")
        for exp in work_exp[:3]:
            parts.append(f"  - {exp}")

    projects = resume_data.get("projects", [])
    if projects:
        parts.append(f"프로젝트: {len(projects)}건")
        for proj in projects[:3]:
            parts.append(f"  - {proj}")

    edu = resume_data.get("education", [])
    if edu:
        parts.append(f"학력: {', '.join(edu[:2])}")

    certs = resume_data.get("certifications", [])
    if certs:
        parts.append(f"자격증: {', '.join(certs[:3])}")

    return "\n".join(parts) if parts else "정보 없음"
