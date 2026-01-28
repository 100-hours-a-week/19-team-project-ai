"""이력서 관련 스키마 - v1"""

from enum import Enum

from pydantic import BaseModel, Field

from schemas.common import ErrorDetail


class ResumeStatus(str, Enum):
    """이력서 처리 상태"""

    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


# ============== 추출 필드 모델 ==============


class WorkExperience(BaseModel):
    """경력 정보"""

    company: str | None = Field(default=None, description="회사명")
    position: str | None = Field(default=None, description="직책 (팀장, 시니어 엔지니어 등)")
    job: str | None = Field(default=None, description="직무 (서버 개발자, 프론트엔드 개발자 등)")
    start_date: str | None = Field(default=None, description="시작일")
    end_date: str | None = Field(default=None, description="종료일")
    description: str | None = Field(default=None, description="업무 설명")


class Project(BaseModel):
    """프로젝트 정보"""

    title: str | None = Field(default=None, description="프로젝트명")
    start_date: str | None = Field(default=None, description="시작일")
    end_date: str | None = Field(default=None, description="종료일")
    description: str | None = Field(default=None, description="설명 (역할, 성과 포함)")


class ContentJson(BaseModel):
    """추출된 이력서 콘텐츠 구조"""

    work_experience: list[WorkExperience] = Field(default_factory=list, description="주요 경력")
    projects: list[Project] = Field(default_factory=list, description="주요 프로젝트")
    education: list[str] = Field(default_factory=list, description="학력 (텍스트)")
    awards: list[str] = Field(default_factory=list, description="수상 내역 (텍스트)")
    certifications: list[str] = Field(default_factory=list, description="자격증 (텍스트)")
    etc: list[str] = Field(default_factory=list, description="대외 활동/기타 (텍스트)")


class ResumeResult(BaseModel):
    """추출 결과"""

    is_fresher: bool = Field(default=False, description="신입 여부")
    education_level: str | None = Field(default=None, description="학력 수준")
    content_json: ContentJson = Field(default_factory=ContentJson, description="추출된 콘텐츠")
    raw_text_excerpt: str | None = Field(default=None, description="원본 텍스트 발췌")


class ResumeParseRequest(BaseModel):
    """POST /resumes/{task_id}/parse 요청"""

    file_url: str = Field(..., description="S3 PDF 파일 URL")
    mode: str = Field(default="sync", description="처리 모드 (sync 또는 async)")


class ResumeData(BaseModel):
    """이력서 응답 데이터 (파싱/조회 공통)"""

    resume_id: int = Field(..., description="이력서 ID")
    status: ResumeStatus = Field(..., description="처리 상태")
    result: ResumeResult | None = Field(default=None, description="추출 결과 (완료 시)")
    error: ErrorDetail | None = Field(default=None, description="에러 정보 (실패 시)")
