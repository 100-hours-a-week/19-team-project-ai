"""스코어링 서비스 - 기술 스택 커버리지 및 역량 분석"""

import logging
from typing import Any

from adapters.llm_client import get_llm_client
from pydantic import BaseModel, Field
from schemas.repo import FitLevel, FulfillmentLevel

logger = logging.getLogger(__name__)

# 경력/학력 등 메타데이터 키워드 (기술 요구사항이 아닌 항목 필터링용)
_NON_TECH_KEYWORDS = ["경력", "학력", "신입", "졸업", "무관"]


def _is_tech_requirement(text: str) -> bool:
    """기술 요구사항인지 판별 (경력/학력 메타데이터 제외)"""
    lower = text.lower().strip()
    return not any(kw in lower for kw in _NON_TECH_KEYWORDS)


def filter_tech_requirements(items: list[str]) -> list[str]:
    """기술 요구사항만 필터링 (경력/학력 관련 항목 제외)"""
    return [item for item in items if _is_tech_requirement(item)]


# ============== AI 분석 결과 스키마 ==============


class RequirementAssessment(BaseModel):
    """요구사항 평가"""
    requirement: str = Field(..., description="요구사항")
    level: str = Field(..., description="충족 수준")
    reason: str = Field(..., description="판단 근거")


class TechMatch(BaseModel):
    """기술 스택 매핑 결과"""
    tech: str = Field(..., description="공고 요구 기술")
    status: str = Field(..., description="충족/부분충족/미충족")
    reason: str = Field(..., description="매핑 근거 (예: 동의어, 유사 기술 등)")

class ItemWithReason(BaseModel):
    """항목과 그에 대한 AI의 분석 이유"""
    item: str = Field(..., description="항목 (요구사항/강점/보완점 등)")
    reason: str = Field(..., description="분석 근거 및 이유")


class AIAnalysisResult(BaseModel):
    """AI 분석 결과"""
    short_title: str = Field(..., description="지원 공고 요약 제목 (30자 내)")
    top_requirements: list[ItemWithReason] = Field(default_factory=list, description="중요 요구사항 Top 3와 이유")
    assessments: list[RequirementAssessment] = Field(default_factory=list, description="현직자 요구사항에 대한 AI 평가")
    strengths: list[ItemWithReason] = Field(default_factory=list, description="강점 2개와 이유")
    improvements: list[ItemWithReason] = Field(default_factory=list, description="보완점 2개와 이유")
    action_items: list[str] = Field(default_factory=list, description="2주 내 액션 2개")
    overall_comment: str = Field(default="", description="AI 총평 (300자 이내)")
    tech_matches: list[TechMatch] = Field(default_factory=list, description="기술 스택 지능형 매칭 결과 (동의어 매핑, 유사 기술 부분 충족 반영)")
    unverifiable_items: list[str] = Field(default_factory=list, description="확인 불가 항목")
    confidence_score: float = Field(default=70.0, description="신뢰도")
    confidence_reason: str = Field(default="", description="신뢰도 근거")


# ============== 시스템 프롬프트 ==============

ANALYSIS_SYSTEM_PROMPT = """당신은 현직자(멘토) 수준의 시각을 가진 채용 전문가입니다. 이력서, 채용공고, 그리고 대화 채팅 로그를 종합적으로 분석하여 핵심 데이터를 생성합니다.

평가 규정:
1. short_title: 채용공고의 특징을 살려 30자 이내의 매력적인 요약 제목 생성
2. top_requirements: 다음 카테고리 중 가장 중요한 3개를 선정하고, 왜 중요한지 AI 관점의 이유(reason)를 구체적으로 기술
   [특정 기술 스택 숙련도, 관련 프로젝트 경험, 도메인 지식, 협업/커뮤니케이션 경험, 문제 해결력/트러블슈팅 경험, 대용량 트래픽/성능 최적화 경험, 경력 연차 및 학력, 성장 가능성/학습 의지]
3. assessments: 현직자(멘토)가 선택해서 넘어온 3개 요구사항에 대해 AI가 충족/부분충족/미충족 판단 + 구체적 근거
4. strengths: 다음 중 강점 2개 선정 + 분석 이유(AI 관점)
   [기술 역량, 문제 해결력, 커뮤니케이션, 프로젝트 경험, 성장 가능성, 도메인 이해도, 협업 능력, 자기 표현력]
5. improvements: 다음 중 보완점 2개 선정 + 분석 이유(AI 관점)
   [기술 깊이 부족, 도메인 지식 부족, 프로젝트 규모/복잡도 부족, 성과 정량화 부족, 경력 부족/연속성, 직무 연관성 부족, 포트폴리오 보완 필요, 경험 다양성 부족]
6. action_items: 2주 내 실행 가능한 구체적 액션 2개
7. overall_comment: 300자 이내의 종합 분석 총평 (핵심 위주로 기술)
8. tech_matches: 공고 기술과 이력서 기술의 지능형 매칭 (동의어 '충족', 유사 '부분충족')
9. unverifiable_items: 데이터 부족으로 확인 불가한 사항 리스트
10. confidence_score: 분석 신뢰도 (0-100)
"""


async def analyze_requirements(
    resume_data: dict,
    job_data: dict,
    chat_messages: list[dict] | None = None,
    mentor_requirements: list[str] | None = None,
) -> dict[str, Any]:
    """이력서-채용공고 요구사항 분석 (채팅 내역 포함)

    Args:
        resume_data: 이력서 파싱 데이터
        job_data: 채용공고 파싱 데이터
        chat_messages: 채팅 메시지 목록
        mentor_requirements: 현직자가 선택한 핵심 요구사항 3개

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

    # 현직자 요구사항 섹션
    mentor_req_text = ""
    if mentor_requirements:
        mentor_req_text = f"""
<현직자 선택 핵심 요구사항>
{chr(10).join([f'{i+1}. {req}' for i, req in enumerate(mentor_requirements)])}
</현직자 선택 핵심 요구사항>

위 현직자가 선택한 3개 요구사항에 대해 assessments 필드에서 각각 AI 관점의 충족/부분충족/미충족 판단과 근거를 작성하세요.
"""

    prompt = f"""다음 이력서와 채용공고를 분석하세요:

<이력서>
{_format_resume(resume_data)}
</이력서>

<대화 내용>
{', '.join([f"{msg.get('sender', {}).get('nickname')}: {msg.get('content')}" for msg in chat_messages]) if chat_messages else '채팅 내역 없음'}
</대화 내용>

<채용공고>
포지션: {job_data.get('title', '미상')}
회사: {company_name}
요구 경력: {job_data.get('experience_level', '미상')}
주요 업무: {', '.join(job_data.get('responsibilities', []))}
자격 요건: {', '.join(job_data.get('qualifications', []))}
우대 사항: {', '.join(job_data.get('preferred_qualifications', []))}
근무조건/복지: {', '.join(job_data.get('benefits', []))}
</채용공고>
{mentor_req_text}
분석 결과를 JSON 형식으로 응답하세요."""

    try:
        result = await llm.generate_json(
            prompt=prompt,
            system_instruction=ANALYSIS_SYSTEM_PROMPT,
            response_schema=AIAnalysisResult,
            temperature=0.2,
        )

        # assessments의 level 문자열을 Enum으로 변환
        level_map = {"충족": FulfillmentLevel.FULFILLED, "부분충족": FulfillmentLevel.PARTIAL, "미충족": FulfillmentLevel.NOT_FULFILLED}
        for a in result.get("assessments", []):
            a["level"] = level_map.get(a.get("level", "미충족"), FulfillmentLevel.NOT_FULFILLED)

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

    # 공고의 자격요건에서 기술 추출 (경력/학력 메타데이터 제외)
    raw_qualifications = job_data.get("qualifications", [])
    filtered_qualifications = filter_tech_requirements(raw_qualifications)
    required_techs = set(t.lower() for t in filtered_qualifications)
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

    # 보유 기술 스택
    skills = resume_data.get("skills", []) or resume_data.get("owned_techs", [])
    if skills:
        parts.append(f"보유 기술: {', '.join(skills)}")

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
