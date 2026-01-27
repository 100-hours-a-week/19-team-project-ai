"""멘토 추천 관련 스키마"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class GroundTruthResult(BaseModel):
    """Silver Ground Truth 검증 결과 (개별 멘토)"""

    is_hit: bool = Field(..., description="자기 자신이 Top-K에 포함되는지")
    rank: int | None = Field(default=None, description="포함 시 순위 (1-based)")


class MentorRecommendation(BaseModel):
    """추천 멘토 정보"""

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
    filter_type: Literal["job", "skill"] | None = Field(
        default=None,
        description="필터 타입 (job: 직무 일치, skill: 기술스택 일치)",
    )
    ground_truth: GroundTruthResult | None = Field(default=None, description="Silver GT 검증 결과")
    last_active_at: datetime | None = Field(default=None, description="마지막 활동 시간")


class EvaluationSummary(BaseModel):
    """평가 요약 (추천 응답에 포함)"""

    hit_at_1: float = Field(..., description="Hit Rate @ 1 (%)")
    hit_at_3: float = Field(..., description="Hit Rate @ 3 (%)")
    hit_at_5: float = Field(..., description="Hit Rate @ 5 (%)")
    hit_at_10: float = Field(..., description="Hit Rate @ 10 (%)")
    mrr: float = Field(..., description="Mean Reciprocal Rank (0~1)")
    total: int = Field(..., description="총 평가 샘플 수")


class MentorRecommendResponse(BaseModel):
    """멘토 추천 응답"""

    user_id: int = Field(..., description="요청 사용자 ID")
    recommendations: list[MentorRecommendation] = Field(
        default_factory=list,
        description="추천 멘토 목록",
    )
    total_count: int = Field(..., description="추천 멘토 수")
    evaluation: EvaluationSummary | None = Field(
        default=None,
        description="Silver Ground Truth 평가 결과 (include_eval=true일 때)",
    )


class MentorSearchRequest(BaseModel):
    """멘토 검색 요청"""

    query: str = Field(..., description="검색어 (예: 백엔드 MSA 경험)")
    top_k: int = Field(default=5, ge=1, le=20, description="검색 개수")
    only_verified: bool = Field(default=False, description="인증 멘토만 검색")


class MentorSearchResult(BaseModel):
    """검색된 멘토 정보"""

    user_id: int = Field(..., description="멘토 사용자 ID")
    nickname: str = Field(..., description="닉네임")
    company_name: str | None = Field(default=None, description="회사명")
    verified: bool = Field(default=False, description="인증 여부")
    skills: list[str] = Field(default_factory=list, description="기술 스택")
    introduction: str = Field(default="", description="자기소개")
    similarity_score: float = Field(..., description="유사도 점수 (0~1)")


class MentorSearchResponse(BaseModel):
    """멘토 검색 응답"""

    query: str = Field(..., description="검색어")
    results: list[MentorSearchResult] = Field(
        default_factory=list,
        description="검색 결과",
    )
    total_count: int = Field(..., description="검색 결과 수")


# ============== Silver Ground Truth 평가 ==============


class EvaluationDetail(BaseModel):
    """개별 평가 상세"""

    gt_user_id: int = Field(..., description="정답 멘토 ID")
    is_hit: bool = Field(..., description="Top-K에 포함 여부")
    rank: int | None = Field(default=None, description="포함된 경우 순위 (1-based)")
    recommended_ids: list[int] = Field(..., description="추천된 멘토 ID 목록")


class EvaluationResponse(BaseModel):
    """Silver Ground Truth 평가 응답"""

    hit_at_1: float = Field(..., description="Hit Rate @ 1 (%)")
    hit_at_3: float = Field(..., description="Hit Rate @ 3 (%)")
    hit_at_5: float = Field(..., description="Hit Rate @ 5 (%)")
    hit_at_10: float = Field(..., description="Hit Rate @ 10 (%)")
    mrr: float = Field(..., description="Mean Reciprocal Rank (0~1)")
    total: int = Field(..., description="총 평가 샘플 수")
    details: list[EvaluationDetail] = Field(
        default_factory=list,
        description="개별 평가 상세 (선택적)",
    )
