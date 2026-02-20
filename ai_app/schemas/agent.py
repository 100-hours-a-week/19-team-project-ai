"""Agent 실시간 채팅 관련 스키마 (D1 조건 기반 멘토 탐색)"""

from typing import Literal

from pydantic import BaseModel, Field

# ============== 요청 ==============


class AgentReplyRequest(BaseModel):
    """Agent 답변 요청"""

    session_id: str | None = Field(default=None, description="세션 ID (없으면 새 세션 생성)")
    message: str = Field(..., min_length=1, description="사용자 메시지")
    top_k: int = Field(default=3, ge=1, le=20, description="추천 멘토 수")


# ============== 의도 분류 ==============


class IntentResult(BaseModel):
    """의도 분류 결과"""

    intent: Literal["D1", "D2", "D3"] = Field(..., description="D1: 멘토 탐색, D2: 질문 개선, D3: AI멘토 대화")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="분류 신뢰도")


# ============== D1 조건 추출 ==============


class MentorConditions(BaseModel):
    """LLM이 추출한 멘토 탐색 조건"""

    job: str | None = Field(default=None, description="직무 (예: 백엔드, 프론트엔드, ML)")
    experience_years: int | None = Field(default=None, description="희망 경력 연수")
    skills: list[str] = Field(default_factory=list, description="기술 스택 (예: Spring, React)")
    domain: str | None = Field(default=None, description="도메인/산업 (예: 핀테크, 헬스케어)")
    region: str | None = Field(default=None, description="지역 (예: 서울, 판교)")
    company_type: str | None = Field(default=None, description="회사 유형 (예: 대기업, 스타트업)")
    keywords: list[str] = Field(default_factory=list, description="기타 키워드")

    def filled_count(self) -> int:
        """채워진 조건 수"""
        count = 0
        if self.job:
            count += 1
        if self.experience_years is not None:
            count += 1
        if self.skills:
            count += 1
        if self.domain:
            count += 1
        if self.region:
            count += 1
        if self.company_type:
            count += 1
        if self.keywords:
            count += 1
        return count


# ============== D1 멘토 카드 ==============


class MentorCard(BaseModel):
    """추천 멘토 카드"""

    user_id: int = Field(..., description="멘토 사용자 ID")
    nickname: str = Field(..., description="닉네임")
    company_name: str | None = Field(default=None, description="회사명")
    verified: bool = Field(default=False, description="인증 여부")
    rating_avg: float = Field(default=0.0, description="평균 평점")
    rating_count: int = Field(default=0, description="리뷰 수")
    response_rate: float = Field(default=0.0, description="응답률 (%)")
    skills: list[str] = Field(default_factory=list, description="기술 스택")
    jobs: list[str] = Field(default_factory=list, description="직무")
    introduction: str = Field(default="", description="자기소개")
    similarity_score: float = Field(..., description="임베딩 유사도 (0~1)")
    rerank_score: float = Field(default=0.0, description="재정렬 후 최종 점수")
    filter_type: str | None = Field(default=None, description="필터 유형 (job/skill/response_rate)")


# ============== SSE 스트림 이벤트 ==============


class StreamEvent(BaseModel):
    """SSE 스트림 이벤트"""

    event: str = Field(..., description="이벤트 타입 (intent/conditions/cards/text/done/error)")
    data: dict = Field(default_factory=dict, description="이벤트 데이터")


# ============== 세션 ==============


class SessionInfo(BaseModel):
    """세션 정보"""

    session_id: str = Field(..., description="세션 ID")
    created_at: str = Field(..., description="생성 시각")
    message_count: int = Field(default=0, description="총 메시지 수")
    last_intent: str | None = Field(default=None, description="마지막 의도")
