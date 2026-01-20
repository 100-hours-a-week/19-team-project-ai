"""이력서 관련 스키마 - v1"""

from enum import Enum

from pydantic import BaseModel, Field

from schemas.common import ErrorDetail


class ResumeStatus(str, Enum):
    """이력서 처리 상태"""

    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ContentJson(BaseModel):
    """추출된 이력서 콘텐츠 구조"""

    careers: list[dict] = Field(default_factory=list, description="주요 경력 (회사명, 기간, 직무, 직책)")
    projects: list[dict] = Field(default_factory=list, description="주요 프로젝트 (이름, 기간, 설명)")
    education: list[str] = Field(default_factory=list, description="학력 (텍스트)")
    awards: list[str] = Field(default_factory=list, description="수상 내역 (텍스트)")
    certificates: list[str] = Field(default_factory=list, description="자격증 (텍스트)")
    activities: list[str] = Field(default_factory=list, description="대외 활동/기타 (텍스트)")


class ResumeResult(BaseModel):
    """추출 결과"""

    is_fresher: bool = Field(default=False, description="신입 여부")
    education_level: str | None = Field(default=None, description="학력 수준")
    content_json: ContentJson = Field(default_factory=ContentJson, description="추출된 콘텐츠")
    raw_text_excerpt: str | None = Field(default=None, description="원본 텍스트 발췌")


class ResumeParseRequest(BaseModel):
    """POST /resumes/{resume_id}/parse 요청"""

    file_url: str = Field(..., description="PDF 파일 URL")
    enable_pii_masking: bool = Field(default=True, description="PII 마스킹 활성화 여부")


class ResumeParseData(BaseModel):
    """POST /resumes/{resume_id}/parse 응답 데이터"""

    resume_id: int = Field(..., description="이력서 ID")
    status: ResumeStatus = Field(..., description="처리 상태")
    result: ResumeResult | None = Field(default=None, description="추출 결과 (완료 시)")
    error: ErrorDetail | None = Field(default=None, description="에러 정보 (실패 시)")


class ResumeGetData(BaseModel):
    """GET /resumes/{resume_id} 응답 데이터"""

    resume_id: int = Field(..., description="이력서 ID")
    status: ResumeStatus = Field(..., description="처리 상태")
    result: ResumeResult | None = Field(default=None, description="추출 결과 (완료 시)")
    error: ErrorDetail | None = Field(default=None, description="에러 정보 (실패 시)")


class ResumeUploadData(BaseModel):
    """[임시] POST /resumes/upload 응답 데이터"""

    resume_id: int = Field(..., description="생성된 이력서 ID")
    file_path: str = Field(..., description="저장된 파일 경로")
