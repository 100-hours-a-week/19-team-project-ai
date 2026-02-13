"""리포트 생성 파이프라인 - 현직자 피드백 + AI 분석 통합
"""

import logging
import time
import uuid
from datetime import datetime
from dataclasses import dataclass

from schemas.repo import (
    ActionPlan,
    AIRequirement,
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
    StrengthsAnalysis,
    TechCoverage,
)

from services.repo.scoring import analyze_requirements, analyze_tech_coverage, filter_tech_requirements

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
        job_data: dict,
        resume_id: str | None = None,
        mentor_feedback: MentorFeedback | None = None,
        chat_messages: list[dict] | None = None,
    ) -> ReportResult:
        """리포트 생성 파이프라인 실행"""
        start_time = time.time()
        report_id = str(uuid.uuid4())

        logger.info(f"리포트 생성 시작 - report_id: {report_id}")

        try:
            # 1. 저장된 채용공고 데이터 사용 (이미 파싱 완료)
            logger.info(f"채용공고 데이터 사용 - 포지션: {job_data.get('title')}")
            logger.info(f"채용공고 자격요건: {job_data.get('qualifications', [])}")
            logger.info(f"채용공고 주요업무: {job_data.get('responsibilities', [])}")

            # 2. AI 분석 (채팅 내역 + 현직자 피드백 포함)
            ai_analysis = await self._run_ai_analysis(resume_data, job_data, chat_messages, mentor_feedback)

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

    async def _run_ai_analysis(
        self,
        resume_data: dict,
        job_data: dict,
        chat_messages: list[dict] | None = None,
        mentor_feedback: MentorFeedback | None = None,
    ) -> dict:
        """AI 분석 수행"""
        # 현직자가 선택한 핵심 요구사항 추출
        mentor_requirements = None
        if mentor_feedback and mentor_feedback.key_requirements:
            mentor_requirements = mentor_feedback.key_requirements

        # 기술 스택 커버리지 및 요구사항 통합 분석
        requirements_analysis = await analyze_requirements(
            resume_data, job_data, chat_messages, mentor_requirements
        )

        return {
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
        """10개 섹션 리포트 빌드"""
        ai_data = ai_analysis.get("requirements", {})

        # 1. 기본 정보
        # AI가 뽑은 30자 이내 제목 사용
        short_title = ai_data.get("short_title", job_data.get("title", ""))
        basic_info = BasicInfo(
            job_title=short_title,
            job_position=job_data.get("title", ""),
            report_date=datetime.now().strftime("%Y-%m-%d"),
        )

        # 2. 기술 스택 커버리지
        tech_matches = ai_data.get("tech_matches", [])
        
        total_techs = len(tech_matches)
        if total_techs > 0:
            score = 0
            for tm in tech_matches:
                if tm.get("status") == "충족":
                    score += 1.0
                elif tm.get("status") == "부분충족":
                    score += 0.5
            coverage_rate = (score / total_techs) * 100
        else:
            coverage_rate = 0.0

        missing_required = [tm.get("tech") for tm in tech_matches if tm.get("status") == "미충족"]

        # 자격요건 + 우대사항을 합쳐서 기술 요구사항으로 분석
        # (크롤러가 자격요건을 제대로 파싱하지 못하는 경우 대비)
        all_requirements = job_data.get("qualifications", []) + job_data.get("preferred_qualifications", [])

        tech_coverage = TechCoverage(
            required_techs=filter_tech_requirements(all_requirements),
            preferred_techs=[],  # 이미 all_requirements에 포함됨
            owned_techs=resume_data.get("skills", []) or resume_data.get("owned_techs", []),
            coverage_rate=round(coverage_rate, 1),
            missing_required=missing_required,
            missing_preferred=[],
        )

        # 3. 역량 매칭 비교 (기존 2, 4 통합)
        # AI가 선정한 3가지 요구사항 + 이유
        ai_top = [
            AIRequirement(requirement=item.get("item", ""), reason=item.get("reason", ""))
            for item in ai_data.get("top_requirements", [])
        ]
        
        capability_matches = []
        if mentor_feedback:
            ai_assessments = ai_data.get("assessments", [])
            for assessment in mentor_feedback.requirement_assessments:
                # AI 평가 매칭
                ai_ass = next((a for a in ai_assessments if a.get("requirement") == assessment.requirement), None)
                
                capability_matches.append(CapabilityMatch(
                    requirement=assessment.requirement,
                    mentor_assessment=assessment.fulfillment,
                    mentor_reason=assessment.reason,
                    ai_assessment=ai_ass.get("level", "미충족") if ai_ass else "미충족",
                    ai_reason=ai_ass.get("reason", "") if ai_ass else "",
                    is_matched=(assessment.fulfillment == (ai_ass.get("level") if ai_ass else None))
                ))

        capability_matching = CapabilityMatching(
            ai_top_requirements=ai_top,
            matches=capability_matches
        )

        # 4. 강점 통합 분석
        mentor_strengths = mentor_feedback.strengths if mentor_feedback else []
        ai_strengths_raw = ai_data.get("strengths", [])
        ai_strengths = [s.get("item") for s in ai_strengths_raw]
        
        strengths_analysis = StrengthsAnalysis(
            common_strengths=list(set(mentor_strengths) & set(ai_strengths)),
            mentor_only_strengths=list(set(mentor_strengths) - set(ai_strengths)),
            ai_only_strengths=list(set(ai_strengths) - set(mentor_strengths)),
            ai_reason=". ".join([f"{s.get('item')}: {s.get('reason')}" for s in ai_strengths_raw])
        )

        # 5. 보완점 통합 분석
        mentor_improvements = mentor_feedback.improvements if mentor_feedback else []
        ai_improvements_raw = ai_data.get("improvements", [])
        ai_improvements = [i.get("item") for i in ai_improvements_raw]

        improvements_analysis = ImprovementsAnalysis(
            common_improvements=list(set(mentor_improvements) & set(ai_improvements)),
            mentor_only_improvements=list(set(mentor_improvements) - set(ai_improvements)),
            ai_only_improvements=list(set(ai_improvements) - set(mentor_improvements)),
            ai_reason=". ".join([f"{i.get('item')}: {i.get('reason')}" for i in ai_improvements_raw])
        )

        # 6. 2주 액션 플랜
        action_plan = ActionPlan(
            mentor_actions=mentor_feedback.action_items if mentor_feedback else [],
            ai_actions=ai_data.get("action_items", [])
        )

        # 7. 종합 평가 요약 (현직자 기준)
        overall_evaluation = OverallEvaluation(
            job_fit=mentor_feedback.job_fit if mentor_feedback else "중",
            pass_probability=mentor_feedback.pass_probability if mentor_feedback else "중",
        )

        # 8. 총평
        final_comment = FinalComment(
            mentor_comment=mentor_feedback.overall_comment if mentor_feedback else "",
            ai_comment=ai_data.get("overall_comment", "")
        )

        # 9. 사용된 데이터
        data_sources = DataSources(
            resume_used=bool(resume_data),
            job_posting_used=bool(job_data),
            chat_used=bool(chat_messages),
            ai_analysis_used=True
        )

        # 10. 확인 불가 항목 및 신뢰도
        reliability = Reliability(
            unverifiable_items=ai_data.get("unverifiable_items", []),
            confidence_score=ai_data.get("confidence_score", 0.0),
            confidence_reason=ai_data.get("confidence_reason", "")
        )

        return {
            "basic_info": basic_info.model_dump(),
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
