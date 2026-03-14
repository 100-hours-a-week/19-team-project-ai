from typing import Optional

from pydantic import BaseModel, Field


class ExpertFeedback(BaseModel):
    """현직자 피드백 데이터 스키마 (RAG용)"""

    id: Optional[int] = Field(None, description="피드백 식별자")
    mentor_id: Optional[int] = Field(None, description="피드백을 제공한 멘토 ID")
    question: str = Field(..., description="사용자 질문 또는 멘토링 요청 내용")
    answer: str = Field(..., description="현직자의 답변 내용")
    job_tag: str = Field(..., description="직무 태그 (예: 백엔드, 프론트엔드, 데이터 엔지니어)")
    question_type: str = Field(..., description="질문 유형 (예: 프로젝트, 기술스택, 커리어, 이력서)")
    mentor_nickname: Optional[str] = Field(None, description="답변한 멘토 닉네임")
    company_name: Optional[str] = Field(None, description="멘토 소속 회사")
    source_type: str = Field("seed", description="데이터 출처 (seed, real_mentor, reviewed)")
    quality_score: int = Field(5, description="답변 품질 점수 (1~5)")
    embedding: Optional[list[float]] = Field(None, description="질문/답변 데이터의 벡터 임베딩")


class FeedbackSearchQuery(BaseModel):
    """피드백 검색 쿼리 스키마"""

    query_text: str = Field(..., description="검색용 텍스트")
    job_tag: Optional[str] = Field(None, description="직무 필터")
    question_type: Optional[str] = Field(None, description="질문 유형 필터")
    top_k: int = Field(5, ge=1, le=20, description="반환할 결과 수")
