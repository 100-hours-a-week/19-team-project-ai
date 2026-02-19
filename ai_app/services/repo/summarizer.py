"""요약/액션플랜 생성 서비스"""

import logging
from typing import Any

from adapters.llm_client import get_llm_client
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ============== 요약 결과 스키마 ==============


class ActionItem(BaseModel):
    """액션 아이템"""

    category: str = Field(..., description="카테고리 (기술/경력/학력/자격증 등)")
    priority: str = Field(..., description="우선순위 (상/중/하)")
    action: str = Field(..., description="구체적인 액션")
    reason: str = Field(..., description="이유")
    estimated_time: str | None = Field(default=None, description="예상 소요 기간")


class SummaryResult(BaseModel):
    """요약 결과"""

    overall_assessment: str = Field(..., description="종합 평가 (2-3문장)")
    strengths: list[str] = Field(default_factory=list, description="강점")
    weaknesses: list[str] = Field(default_factory=list, description="보완 필요 사항")
    action_items: list[ActionItem] = Field(default_factory=list, description="액션 아이템")
    interview_tips: list[str] = Field(default_factory=list, description="면접 팁")
    recommended_keywords: list[str] = Field(default_factory=list, description="이력서 추가 권장 키워드")


# ============== 요약 시스템 프롬프트 ==============

SUMMARY_SYSTEM_PROMPT = """당신은 커리어 컨설턴트입니다.
이력서와 채용공고 분석 결과를 바탕으로 지원 전략을 제안합니다.

작성 규칙:
1. overall_assessment: 솔직하고 건설적인 종합 평가
2. strengths: 이 공고에 특히 유리한 점 (구체적 근거 포함)
3. weaknesses: 보완이 필요한 점 (비판보다는 개선 방향 제시)
4. action_items: 실행 가능한 구체적 액션
   - 단기(1-2주), 중기(1-3개월), 장기(3개월+)로 구분
   - 우선순위 높은 것부터 정렬
5. interview_tips: 이 회사/포지션 면접 시 강조할 점
6. recommended_keywords: 이력서에 추가하면 좋을 키워드
"""


async def generate_summary(resume_data: dict, job_data: dict, scores: dict) -> dict[str, Any]:
    """요약 및 액션플랜 생성

    Args:
        resume_data: 이력서 파싱 데이터
        job_data: 채용공고 파싱 데이터
        scores: 스코어링 결과

    Returns:
        요약 및 액션플랜
    """
    logger.info("요약 및 액션플랜 생성 시작")

    llm = get_llm_client()

    prompt = f"""다음 분석 결과를 바탕으로 지원 전략을 제안하세요:

<이력서 요약>
{_format_resume_summary(resume_data)}
</이력서 요약>

<채용공고>
포지션: {job_data.get("title", "미상")}
회사: {job_data.get("company", "미상")}
자격요건: {", ".join(job_data.get("qualifications", [])[:5])}
우대사항: {", ".join(job_data.get("preferred_qualifications", [])[:5])}
</채용공고>

<적합도 분석>
커버리지 점수: {scores.get("coverage_score", 0)}/100
적합도 점수: {scores.get("fit_score", 0)}/100
충족 요구사항: {", ".join(scores.get("matched_requirements", [])[:5])}
미충족 요구사항: {", ".join(scores.get("unmatched_requirements", [])[:5])}
</적합도 분석>

실행 가능한 구체적인 전략을 JSON 형식으로 제안하세요."""

    try:
        result = await llm.generate_json(
            prompt=prompt,
            system_instruction=SUMMARY_SYSTEM_PROMPT,
            response_schema=SummaryResult,
            temperature=0.3,  # 약간의 창의성을 위해 높임
        )

        logger.info("요약 생성 완료")
        return result

    except Exception as e:
        logger.error(f"요약 생성 실패: {e}")
        return {
            "overall_assessment": "분석 중 오류가 발생했습니다.",
            "action_items": [],
            "error": str(e),
        }


def _format_resume_summary(resume_data: dict) -> str:
    """이력서 요약 텍스트 생성"""
    parts = []

    if resume_data.get("title"):
        parts.append(f"제목: {resume_data['title']}")

    work_exp = resume_data.get("work_experience", [])
    if work_exp:
        parts.append(f"경력: {len(work_exp)}개 회사/프로젝트")

    projects = resume_data.get("projects", [])
    if projects:
        parts.append(f"프로젝트: {len(projects)}개")

    certs = resume_data.get("certifications", [])
    if certs:
        parts.append(f"자격증: {', '.join(certs[:3])}")

    return "\n".join(parts) if parts else "정보 없음"
