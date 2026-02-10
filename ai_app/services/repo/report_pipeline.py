"""리포트 생성 파이프라인 - 현직자 피드백 + AI 분석 통합
"""

import logging
import time
import uuid
from dataclasses import dataclass

from schemas.repo import (
    ActionPlan,
    BasicInfo,
    CapabilityMatch,
    CapabilityMatching,
    DataSources,
    FinalComment,
    FitLevel,
    FulfillmentLevel,
    ImprovementsAnalysis,
    MentorFeedback,
    OverallEvaluation,
    Reliability,
    RequirementComparison,
    StrengthsAnalysis,
    TechCoverage,
)

from services.repo.scoring import analyze_requirements, analyze_tech_coverage

logger = logging.getLogger(__name__)


@dataclass
class ReportResult:
    """리포트 생성 결과"""

    success: bool
    report_id: str | None
    resume_id: str | None
    report_data: dict | None
    processing_time_ms: int
    error_message: str | None = None


class ReportPipeline:
    """리포트 생성 파이프라인 - 현직자 피드백 + AI 분석 통합

    파이프라인 단계:
    1. 채용공고 파싱 (CrawlerService 우선, LLM fallback)
    2. AI 분석 (기술 커버리지, 역량 매칭)
    3. 현직자 피드백 통합
    4. 11개 섹션 리포트 생성
    """

    async def _parse_job(self, job_url: str | None, job_text: str | None) -> dict:
        """채용공고 파싱 - CrawlerService 우선, LLM fallback

        사람인/잡코리아/원티드 URL이면 CrawlerService를 사용하고,
        그 외 URL이거나 텍스트이면 LLM 파서를 사용합니다.
        """
        # URL이 제공된 경우 - CrawlerService 우선 시도
        if job_url:
            try:
                from services.job_crawler.crawler_service import get_crawler_service

                crawler_service = get_crawler_service()
                job_posting = await crawler_service.parse_url(job_url)

                if job_posting:
                    # JobPosting → dict 변환
                    posting_dict = job_posting.model_dump()
                    logger.info(f"CrawlerService 파싱 성공 - {posting_dict.get('title')}")
                    return {"success": True, "data": posting_dict}

                logger.info("CrawlerService가 이 URL을 지원하지 않음, LLM fallback 시도")
            except Exception as e:
                logger.warning(f"CrawlerService 파싱 실패, LLM fallback: {e}")

            # CrawlerService 실패 시 LLM fallback
            from services.repo.job_parser import parse_job_from_url

            return await parse_job_from_url(job_url)

        # 텍스트만 제공된 경우 - LLM 파서
        if job_text:
            from services.repo.job_parser import parse_job_from_text

            return await parse_job_from_text(job_text)

        return {"success": False, "error": "job_url 또는 job_text 중 하나는 필수입니다."}

    async def generate(
        self,
        resume_data: dict,
        job_url: str | None = None,
        job_text: str | None = None,
        resume_id: str | None = None,
        mentor_feedback: MentorFeedback | None = None,
        chat_messages: list[dict] | None = None,
    ) -> ReportResult:
        """리포트 생성 파이프라인 실행"""
        start_time = time.time()
        report_id = str(uuid.uuid4())

        logger.info(f"리포트 생성 시작 - report_id: {report_id}")

        try:
            # 1. 채용공고 파싱 (CrawlerService 우선)
            job_result = await self._parse_job(job_url, job_text)

            if not job_result.get("success"):
                return ReportResult(
                    success=False,
                    report_id=report_id,
                    resume_id=resume_id,
                    report_data=None,
                    processing_time_ms=int((time.time() - start_time) * 1000),
                    error_message=f"채용공고 파싱 실패: {job_result.get('error')}",
                )

            job_data = job_result.get("data", {})
            logger.info(f"채용공고 파싱 완료 - 포지션: {job_data.get('title')}")
            logger.info(f"채용공고 자격요건: {job_data.get('qualifications', [])}")
            logger.info(f"채용공고 주요업무: {job_data.get('responsibilities', [])}")

            # 2. AI 분석
            ai_analysis = await self._run_ai_analysis(resume_data, job_data)

            # 3. 11개 섹션 리포트 생성
            report_sections = await self._build_report_sections(
                resume_data=resume_data,
                job_data=job_data,
                ai_analysis=ai_analysis,
                mentor_feedback=mentor_feedback,
                chat_messages=chat_messages,
            )

            processing_time = int((time.time() - start_time) * 1000)
            logger.info(f"리포트 생성 완료 - {processing_time}ms")

            return ReportResult(
                success=True,
                report_id=report_id,
                resume_id=resume_id,
                report_data=report_sections,
                processing_time_ms=processing_time,
            )

        except Exception as e:
            logger.error(f"리포트 생성 실패: {e}", exc_info=True)
            return ReportResult(
                success=False,
                report_id=report_id,
                resume_id=resume_id,
                report_data=None,
                processing_time_ms=int((time.time() - start_time) * 1000),
                error_message=str(e),
            )

    async def _run_ai_analysis(self, resume_data: dict, job_data: dict) -> dict:
        """AI 분석 수행"""
        # 기술 스택 커버리지
        tech_coverage = await analyze_tech_coverage(resume_data, job_data)

        # 요구사항 분석
        requirements_analysis = await analyze_requirements(resume_data, job_data)

        return {
            "tech_coverage": tech_coverage,
            "requirements": requirements_analysis,
        }

    async def _build_report_sections(
        self,
        resume_data: dict,
        job_data: dict,
        ai_analysis: dict,
        mentor_feedback: MentorFeedback | None,
        chat_messages: list[dict] | None,
    ) -> dict:
        """11개 섹션 리포트 빌드"""

        # 1. 기본 정보
        basic_info = BasicInfo(
            job_title=job_data.get("title"),
            job_position=job_data.get("department") or job_data.get("title"),
        )

        # 2. 공고 핵심 요구사항 비교
        mentor_reqs = mentor_feedback.key_requirements if mentor_feedback else []
        ai_reqs = ai_analysis.get("requirements", {}).get("top_requirements", [])[:3]
        common_reqs = list(set(mentor_reqs) & set(ai_reqs))

        requirement_comparison = RequirementComparison(
            mentor_selected=mentor_reqs,
            ai_selected=ai_reqs,
            common_items=common_reqs,
            mentor_perspective=ai_analysis.get("requirements", {}).get("mentor_perspective_diff", ""),
            ai_perspective=ai_analysis.get("requirements", {}).get("ai_perspective_diff", ""),
        )

        # 3. 기술 스택 커버리지
        tech_data = ai_analysis.get("tech_coverage", {})
        tech_coverage = TechCoverage(
            required_techs=job_data.get("qualifications", []),
            preferred_techs=job_data.get("preferred_qualifications", []),
            owned_techs=resume_data.get("skills", []),
            coverage_rate=tech_data.get("coverage_rate", 0.0),
            missing_required=tech_data.get("missing_required", []),
            missing_preferred=tech_data.get("missing_preferred", []),
        )

        # 4. 역량 매칭 비교
        matches = []
        if mentor_feedback:
            for assessment in mentor_feedback.requirement_assessments:
                ai_assessment = ai_analysis.get("requirements", {}).get("assessments", {}).get(
                    assessment.requirement, {"level": FulfillmentLevel.NOT_FULFILLED, "reason": ""}
                )
                matches.append(CapabilityMatch(
                    requirement=assessment.requirement,
                    mentor_assessment=assessment.fulfillment,
                    mentor_reason=assessment.reason,
                    ai_assessment=ai_assessment.get("level", FulfillmentLevel.NOT_FULFILLED),
                    ai_reason=ai_assessment.get("reason", ""),
                    is_matched=assessment.fulfillment == ai_assessment.get("level"),
                ))

        capability_matching = CapabilityMatching(matches=matches)

        # 5. 강점 통합 분석
        mentor_strengths = set(mentor_feedback.strengths) if mentor_feedback else set()
        ai_strengths = set(ai_analysis.get("requirements", {}).get("strengths", []))
        common_strengths = list(mentor_strengths & ai_strengths)

        strengths_analysis = StrengthsAnalysis(
            common_strengths=common_strengths,
            mentor_only_strengths=list(mentor_strengths - ai_strengths),
            ai_only_strengths=list(ai_strengths - mentor_strengths),
        )

        # 6. 보완점 통합 분석
        mentor_improvements = set(mentor_feedback.improvements) if mentor_feedback else set()
        ai_improvements = set(ai_analysis.get("requirements", {}).get("improvements", []))
        common_improvements = list(mentor_improvements & ai_improvements)

        improvements_analysis = ImprovementsAnalysis(
            common_improvements=common_improvements,
            mentor_only_improvements=list(mentor_improvements - ai_improvements),
            ai_only_improvements=list(ai_improvements - ai_improvements),
        )

        # 7. 2주 액션 플랜
        mentor_actions = mentor_feedback.action_items if mentor_feedback else []
        ai_actions = ai_analysis.get("requirements", {}).get("action_items", [])[:2]
        # 우선순위 Top 3 통합
        all_actions = mentor_actions + ai_actions
        top_priorities = all_actions[:3]

        action_plan = ActionPlan(
            mentor_actions=mentor_actions,
            ai_actions=ai_actions,
            top_priorities=top_priorities,
        )

        # 8. 종합 평가 요약
        mentor_fit = mentor_feedback.job_fit if mentor_feedback else FitLevel.MEDIUM
        mentor_pass = mentor_feedback.pass_probability if mentor_feedback else FitLevel.MEDIUM
        ai_fit = ai_analysis.get("requirements", {}).get("job_fit", FitLevel.MEDIUM)
        ai_pass = ai_analysis.get("requirements", {}).get("pass_probability", FitLevel.MEDIUM)

        # 현직자와 AI 평가 종합 (보수적으로)
        overall_evaluation = OverallEvaluation(
            job_fit=mentor_fit if mentor_feedback else ai_fit,
            pass_probability=mentor_pass if mentor_feedback else ai_pass,
        )

        # 9. 총평
        final_comment = FinalComment(
            mentor_comment=mentor_feedback.overall_comment if mentor_feedback else "",
            ai_comment=ai_analysis.get("requirements", {}).get("overall_comment", ""),
        )

        # 10. 사용된 데이터
        data_sources = DataSources(
            resume_used=bool(resume_data),
            job_posting_used=bool(job_data),
            chat_used=bool(chat_messages),
            ai_analysis_used=True,
        )

        # 11. 신뢰도
        unverifiable = ai_analysis.get("requirements", {}).get("unverifiable_items", [])
        confidence = ai_analysis.get("requirements", {}).get("confidence_score", 70.0)

        reliability = Reliability(
            unverifiable_items=unverifiable,
            confidence_score=confidence,
            confidence_reason=ai_analysis.get("requirements", {}).get("confidence_reason", ""),
        )

        return {
            "basic_info": basic_info.model_dump(),
            "requirement_comparison": requirement_comparison.model_dump(),
            "tech_coverage": tech_coverage.model_dump(),
            "capability_matching": capability_matching.model_dump(),
            "strengths_analysis": strengths_analysis.model_dump(),
            "improvements_analysis": improvements_analysis.model_dump(),
            "action_plan": action_plan.model_dump(),
            "overall_evaluation": overall_evaluation.model_dump(),
            "final_comment": final_comment.model_dump(),
            "data_sources": data_sources.model_dump(),
            "reliability": reliability.model_dump(),
        }


# 싱글톤 인스턴스
_report_pipeline: ReportPipeline | None = None


def get_report_pipeline() -> ReportPipeline:
    """리포트 파이프라인 싱글톤"""
    global _report_pipeline
    if _report_pipeline is None:
        _report_pipeline = ReportPipeline()
    return _report_pipeline
