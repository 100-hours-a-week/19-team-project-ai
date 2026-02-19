"""리포트 스키마 - 현직자 피드백 + AI 분석 통합"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

# ============== Enums ==============


class FulfillmentLevel(str, Enum):
    """충족 수준"""

    FULFILLED = "충족"
    PARTIAL = "부분충족"
    NOT_FULFILLED = "미충족"


class FitLevel(str, Enum):
    """적합도/가능성 수준"""

    HIGH = "상"
    MEDIUM = "중"
    LOW = "하"


# ============== 현직자 피드백 스키마 ==============


class RequirementSelection(BaseModel):
    """핵심 요구사항 선택"""

    requirement: str = Field(..., description="선택한 요구사항")
    fulfillment: FulfillmentLevel = Field(..., description="충족 여부")
    reason: str = Field(..., description="판단 근거 (100자)")


class MentorFeedback(BaseModel):
    """현직자 피드백 폼"""

    # 1. 공고 핵심 요구사항 (3개 필수)
    key_requirements: list[str] = Field(
        ...,
        min_length=3,
        max_length=3,
        description="중요하다고 생각하는 역량/요건 3가지",
    )

    # 2. 충족 여부
    requirement_assessments: list[RequirementSelection] = Field(
        ...,
        description="핵심 요구사항별 충족 여부 및 근거",
    )

    # 3. 강점 (2개 필수)
    strengths: list[str] = Field(
        ...,
        min_length=2,
        max_length=2,
        description="강점 2개",
    )
    strengths_reason: str = Field(..., description="강점 판단 근거 (100자)")

    # 4. 보완점 (2개 필수)
    improvements: list[str] = Field(
        ...,
        min_length=2,
        max_length=2,
        description="보완점 2개",
    )
    improvements_reason: str = Field(..., description="보완점 판단 근거 (100자)")

    # 5. 2주 내 액션
    action_items: list[str] = Field(
        ...,
        min_length=2,
        max_length=2,
        description="2주 내 보완 가능한 액션 2개 (100자 이내)",
    )

    # 6. 직무 적합도
    job_fit: FitLevel = Field(..., description="직무 적합도")

    # 7. 서류 통과 가능성
    pass_probability: FitLevel = Field(..., description="서류 통과 가능성")

    # 8. 총평
    overall_comment: str = Field(..., description="현직자 관점 총평 (300자 이내)")


# ============== 채팅 메시지 스키마 (백엔드 API 형식) ==============


class ChatSender(BaseModel):
    """채팅 발신자"""

    user_id: int
    nickname: str
    profile_image_url: str | None = None
    user_type: str  # JOB_SEEKER, EXPERT


class ChatMessage(BaseModel):
    """채팅 메시지 - 백엔드 API 형식"""

    message_id: int
    chat_id: int | None = None
    room_sequence: int | None = None
    sender: ChatSender
    message_type: str = "TEXT"
    content: str
    client_message_id: str | None = None
    created_at: str


# ============== 리포트 요청/응답 스키마 ==============


class JobParseRequest(BaseModel):
    """채용공고 파싱 요청"""

    job_url: str = Field(..., description="채용공고 URL")


class JobParseResponse(BaseModel):
    """채용공고 파싱 응답"""

    job_post_id: int = Field(..., description="채용공고 ID")
    job_post_title: str | None = Field(default=None, description="채용공고 원문 제목")
    job_post_position: str | None = Field(default=None, description="정규화된 직무 명칭")
    company: str | None = Field(default=None, description="회사명")
    employment_type: str | None = Field(default=None, description="고용 형태")
    experience_level: str | None = Field(default=None, description="요구 경력")
    education: str | None = Field(default=None, description="요구 학력")
    responsibilities: list[str] = Field(default_factory=list, description="주요 업무")
    qualifications: list[str] = Field(default_factory=list, description="자격요건")
    preferred_qualifications: list[str] = Field(default_factory=list, description="우대사항")
    tech_stack: list[str] = Field(default_factory=list, description="사용 기술")
    location: str | None = Field(default=None, description="근무지")
    benefits: list[str] = Field(default_factory=list, description="복지 및 혜택")
    hiring_process: list[str] = Field(default_factory=list, description="채용절차")
    notes: list[str] = Field(default_factory=list, description="유의사항")


class ReportGenerateRequest(BaseModel):
    """리포트 생성 요청"""

    resume_id: int = Field(..., description="이력서 ID")
    job_post_id: int = Field(..., description="채용공고 ID (/repo/job-post에서 반환된 ID)")
    user_skills: list[str] | None = Field(default=None, description="사용자 보유 기술 스택 (DB에서 조회)")
    mentor_feedback: MentorFeedback | None = Field(default=None, description="현직자 피드백")
    chat_messages: list[ChatMessage] | None = Field(default=None, description="채팅 메시지")


# ============== 리포트 섹션 스키마 ==============


class BasicInfo(BaseModel):
    """1. 기본 정보"""

    job_post_title: str | None = Field(default=None, description="지원 공고 제목")
    job_post_position: str | None = Field(default=None, description="지원하는 직무")
    report_date: str = Field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d"), description="리포트 생성일")


class AIRequirement(BaseModel):
    """AI가 선정한 요구사항과 이유"""

    requirement: str = Field(..., description="요구사항")
    reason: str = Field(..., description="선택 이유")


class TechCoverage(BaseModel):
    """2. 기술 스택 커버리지"""

    required_techs: list[str] = Field(default_factory=list, description="공고 요구 기술 (필수)")
    preferred_techs: list[str] = Field(default_factory=list, description="공고 요구 기술 (우대)")
    owned_techs: list[str] = Field(default_factory=list, description="보유 기술")
    coverage_rate: float = Field(default=0.0, description="기술 스택 커버율 (%)")
    missing_required: list[str] = Field(default_factory=list, description="미충족 기술 (필수)")
    missing_preferred: list[str] = Field(default_factory=list, description="미충족 기술 (우대)")


class CapabilityMatch(BaseModel):
    """역량 매칭 항목"""

    requirement: str = Field(..., description="핵심 요구사항")
    mentor_assessment: FulfillmentLevel = Field(..., description="현직자 판단")
    mentor_reason: str = Field(default="", description="현직자 근거")
    ai_assessment: FulfillmentLevel = Field(..., description="AI 판단")
    ai_reason: str = Field(default="", description="AI 근거")
    is_matched: bool = Field(default=False, description="판단 일치 여부")


class CapabilityMatching(BaseModel):
    """3. 역량 매칭 비교"""

    ai_top_requirements: list[AIRequirement] = Field(
        default_factory=list, description="AI가 중요하다고 판단한 요구사항 3개와 이유"
    )
    matches: list[CapabilityMatch] = Field(
        default_factory=list, description="핵심 요구사항(현직자 선택 3가지) 매칭 결과"
    )


class StrengthsAnalysis(BaseModel):
    """4. 강점 통합 분석"""

    common_strengths: list[str] = Field(default_factory=list, description="공통 강점")
    mentor_only_strengths: list[str] = Field(default_factory=list, description="현직자만 언급한 강점")
    ai_only_strengths: list[str] = Field(default_factory=list, description="AI만 언급한 강점")
    ai_reason: str = Field(default="", description="AI 관점 강점 분석 이유 (2개 추출 근거)")


class ImprovementsAnalysis(BaseModel):
    """5. 보완점 통합 분석"""

    common_improvements: list[str] = Field(default_factory=list, description="공통 보완점")
    mentor_only_improvements: list[str] = Field(default_factory=list, description="현직자만 언급한 보완점")
    ai_only_improvements: list[str] = Field(default_factory=list, description="AI만 언급한 보완점")
    ai_reason: str = Field(default="", description="AI 관점 보완점 분석 이유 (2개 추출 근거)")


class ActionPlan(BaseModel):
    """6. 2주 액션 플랜"""

    mentor_actions: list[str] = Field(default_factory=list, description="현직자 관점 2주 내 액션 2개")
    ai_actions: list[str] = Field(default_factory=list, description="AI 관점 2주 내 액션 2개")


class OverallEvaluation(BaseModel):
    """7. 종합 평가 요약"""

    job_fit: FitLevel = Field(default=FitLevel.MEDIUM, description="현직자의 직무 적합도")
    pass_probability: FitLevel = Field(default=FitLevel.MEDIUM, description="현직자의 서류 통과 가능성")


class FinalComment(BaseModel):
    """8. 총평"""

    mentor_comment: str = Field(default="", description="현직자 총평")
    ai_comment: str = Field(default="", description="AI 총평 (300자 내)")


class DataSources(BaseModel):
    """9. 사용된 데이터"""

    resume_used: bool = Field(default=False, description="이력서 사용 여부 (선택)")
    job_posting_used: bool = Field(default=False, description="채용 공고 사용 여부 (선택)")
    chat_used: bool = Field(default=True, description="채팅 사용 여부 (필수)")
    ai_analysis_used: bool = Field(default=True, description="AI 분석 사용 여부 (필수)")
    privacy_notice: str = Field(
        default="이력서 원문 파일은 사용되지 않으며 공고 원문은 리포트 생성에만 사용됩니다. 민감한 중간 결과는 저장하지 않습니다.",
        description="정책 안내",
    )


class Reliability(BaseModel):
    """10. 확인 불가 항목 및 신뢰도"""

    unverifiable_items: list[str] = Field(default_factory=list, description="확인 불가 항목")
    confidence_score: float = Field(default=0.0, description="신뢰도/확신도 (0-100)")
    confidence_reason: str = Field(default="", description="신뢰도 판단 근거")


# ============== 전체 리포트 응답 ==============


class ReportGenerateResponse(BaseModel):
    """리포트 생성 응답 - 11개 섹션"""

    report_id: int = Field(..., description="리포트 ID")
    resume_id: int = Field(..., description="이력서 ID")

    # 10개 섹션
    basic_info: BasicInfo = Field(default_factory=BasicInfo, description="1. 기본 정보")
    tech_coverage: TechCoverage = Field(default_factory=TechCoverage, description="2. 기술 스택 커버리지")
    capability_matching: CapabilityMatching = Field(default_factory=CapabilityMatching, description="3. 역량 매칭 비교")
    strengths_analysis: StrengthsAnalysis = Field(default_factory=StrengthsAnalysis, description="4. 강점 통합 분석")
    improvements_analysis: ImprovementsAnalysis = Field(
        default_factory=ImprovementsAnalysis, description="5. 보완점 통합 분석"
    )
    action_plan: ActionPlan = Field(default_factory=ActionPlan, description="6. 2주 액션 플랜")
    overall_evaluation: OverallEvaluation = Field(default_factory=OverallEvaluation, description="7. 종합 평가 요약")
    final_comment: FinalComment = Field(default_factory=FinalComment, description="8. 총평")
    data_sources: DataSources = Field(default_factory=DataSources, description="9. 사용된 데이터")
    reliability: Reliability = Field(default_factory=Reliability, description="10. 확인 불가 항목 및 신뢰도")

    processing_time_ms: int | None = Field(default=None, description="처리 시간(ms)")
