"""공통 스키마 - Spring 스타일 응답 envelope"""

from enum import Enum
from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ResponseCode(str, Enum):
    """응답 코드"""

    OK = "OK"
    BAD_REQUEST = "BAD_REQUEST"
    NOT_FOUND = "NOT_FOUND"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    INTERNAL_SERVER_ERROR = "INTERNAL_SERVER_ERROR"


class ApiResponse(BaseModel, Generic[T]):
    """공통 API 응답 envelope"""

    code: ResponseCode = Field(..., description="응답 코드")
    data: T | None = Field(default=None, description="응답 데이터")


class ErrorDetail(BaseModel):
    """에러 상세 정보"""

    code: str | None = Field(default=None, description="에러 코드")
    detail: str | None = Field(default=None, description="에러 상세 메시지")


class ValidationErrorData(BaseModel):
    """유효성 검증 에러 데이터"""

    fields: list[str] = Field(default_factory=list, description="검증 실패 필드 목록")


class NotFoundErrorData(BaseModel):
    """리소스 미발견 에러 데이터"""

    resource: str | None = Field(default=None, description="리소스 타입")
    id: int | None = Field(default=None, description="리소스 ID")
