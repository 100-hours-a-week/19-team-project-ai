"""채용공고 관련 스키마"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class JobSource(str, Enum):
    """채용공고 소스"""

    SARAMIN = "saramin"
    JOBKOREA = "jobkorea"
    WANTED = "wanted"


class JobType(str, Enum):
    """고용 형태"""

    FULL_TIME = "정규직"
    CONTRACT = "계약직"
    ANY = "상관없음"


# ============== 채용공고 모델 ==============


class CompanyInfo(BaseModel):
    """회사 정보"""

    name: str = Field(..., description="회사명")
    industry: str | None = Field(default=None, description="업종")
    location: str | None = Field(default=None, description="회사 위치")


class SalaryInfo(BaseModel):
    """급여 정보"""

    text: str | None = Field(default=None, description="급여 텍스트 (예: 3000~4000만원)")


class JobPosting(BaseModel):
    """채용공고 정보"""

    # 식별자
    source: JobSource = Field(..., description="채용공고 소스")
    source_id: str = Field(..., description="소스별 고유 ID")

    # 기본 정보
    title: str = Field(..., description="채용공고 제목")
    company: CompanyInfo = Field(..., description="회사 정보")

    # 직무 정보
    job_type: JobType | None = Field(default=None, description="고용형태 (정규직, 계약직, 상관없음)")
    job_category: list[str] = Field(default_factory=list, description="직무 카테고리")
    experience_level: str | None = Field(default=None, description="경력 요건")
    education: str | None = Field(default=None, description="학력 요건")

    # 조건
    salary: SalaryInfo | None = Field(default=None, description="급여 정보")
    location: str | None = Field(default=None, description="근무지")

    # 상세 정보
    responsibilities: list[str] = Field(default_factory=list, description="주요 업무")
    qualifications: list[str] = Field(default_factory=list, description="자격 요건")
    preferred_qualifications: list[str] = Field(default_factory=list, description="우대사항")
    tech_stack: list[str] = Field(default_factory=list, description="사용 기술")
    benefits: list[str] = Field(default_factory=list, description="복지 및 혜택")
    hiring_process: list[str] = Field(default_factory=list, description="채용절차")
    etc: list[str] = Field(default_factory=list, description="기타 정보")

    # 메타 정보
    deadline: str | None = Field(default=None, description="마감일")
    url: str = Field(..., description="원본 공고 URL")
    crawled_at: datetime = Field(default_factory=datetime.utcnow, description="크롤링 시간")


# ============== 요청/응답 모델 ==============


class JobParseRequest(BaseModel):
    """채용공고 URL 파싱 요청"""

    url: str = Field(..., description="채용공고 URL (사람인, 잡코리아, 원티드)")
