"""이력서 컨트롤러 - 이력서 추출 파이프라인"""

import httpx
from typing import Any

from fastapi import HTTPException

from schemas.common import ErrorDetail, ResponseCode
from schemas.resumes import (
    ContentJson,
    ResumeGetData,
    ResumeParseData,
    ResumeParseRequest,
    ResumeResult,
    ResumeStatus,
)
from services.doc_ai.parse_pipeline import ParsePipeline


class ResumesController:
    """이력서 추출 파이프라인 컨트롤러"""

    def __init__(self, parse_pipeline: ParsePipeline | None = None):
        self.parse_pipeline = parse_pipeline or ParsePipeline()
        self._resume_store: dict[int, dict[str, Any]] = {}

    async def _download_pdf(self, file_url: str) -> bytes:
        """URL에서 PDF 파일 다운로드"""
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(file_url)
            response.raise_for_status()
            return response.content

    def _convert_to_resume_result(self, parse_result: Any) -> ResumeResult:
        """ParseResult를 ResumeResult로 변환"""
        fields = parse_result.extracted_fields

        # 경력 여부로 신입 판단 
        is_fresher = len(fields.work_experience) == 0 if fields else True

        # 학력 수준 추출 (첫번째 학력에서)
        education_level = None
        if fields and fields.education:
            education_level = fields.education[0] if fields.education else None

        # content_json 구성
        content_json = ContentJson(
            careers=[exp.model_dump() for exp in (fields.work_experience if fields else [])],
            projects=[proj.model_dump() for proj in (fields.projects if fields else [])],
            education=fields.education if fields else [],
            awards=fields.awards if fields else [],
            certificates=fields.certifications if fields else [],
            activities=fields.etc if fields else [],
        )

        # 원본 텍스트 발췌 (500자 제한)
        raw_text_excerpt = None
        if parse_result.raw_text:
            if len(parse_result.raw_text) > 500:
                raw_text_excerpt = parse_result.raw_text[:500] + "..."
            else:
                raw_text_excerpt = parse_result.raw_text

        return ResumeResult(
            is_fresher=is_fresher,
            education_level=education_level,
            content_json=content_json,
            raw_text_excerpt=raw_text_excerpt,
        )

    async def parse_resume(
        self,
        resume_id: int,
        request: ResumeParseRequest,
    ) -> ResumeParseData:
        """
        이력서 추출 파이프라인 실행

        Args:
            resume_id: 이력서 ID
            request: 파싱 요청 정보

        Returns:
            ResumeParseData: 파싱 결과
        """
        # PDF 다운로드
        try:
            pdf_bytes = await self._download_pdf(request.file_url)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise HTTPException(
                    status_code=404,
                    detail={"code": ResponseCode.NOT_FOUND.value, "data": {"resource": "file", "id": resume_id}},
                )
            raise HTTPException(
                status_code=500,
                detail={"code": ResponseCode.INTERNAL_SERVER_ERROR.value, "data": None},
            )
        except Exception:
            raise HTTPException(
                status_code=500,
                detail={"code": ResponseCode.INTERNAL_SERVER_ERROR.value, "data": None},
            )

        # PDF 파싱 및 필드 추출
        result = await self.parse_pipeline.parse_bytes(
            pdf_bytes=pdf_bytes,
            extract_pii=not request.enable_pii_masking,
        )

        if result.success:
            # 성공: 결과 변환 및 저장
            resume_result = self._convert_to_resume_result(result)
            response_data = ResumeParseData(
                resume_id=resume_id,
                status=ResumeStatus.COMPLETED,
                result=resume_result,
                error=None,
            )
        else:
            # 실패: 에러 정보 저장
            error_code = "OCR_REQUIRED" if result.needs_ocr else "EXTRACTION_FAILED"
            response_data = ResumeParseData(
                resume_id=resume_id,
                status=ResumeStatus.FAILED,
                result=None,
                error=ErrorDetail(code=error_code, detail=result.error_message),
            )

        # 결과 저장 (GET 조회용)
        self._resume_store[resume_id] = response_data.model_dump()

        return response_data

    async def parse_resume_from_bytes(
        self,
        resume_id: int,
        pdf_bytes: bytes,
        enable_pii_masking: bool = True,
    ) -> ResumeParseData:
        """
        [임시] PDF bytes에서 직접 이력서 추출 파이프라인 실행

        Args:
            resume_id: 이력서 ID
            pdf_bytes: PDF 파일 바이트
            enable_pii_masking: PII 마스킹 활성화 여부

        Returns:
            ResumeParseData: 파싱 결과
        """
        # PDF 파싱 및 필드 추출
        result = await self.parse_pipeline.parse_bytes(
            pdf_bytes=pdf_bytes,
            extract_pii=not enable_pii_masking,
        )

        if result.success:
            # 성공: 결과 변환 및 저장
            resume_result = self._convert_to_resume_result(result)
            response_data = ResumeParseData(
                resume_id=resume_id,
                status=ResumeStatus.COMPLETED,
                result=resume_result,
                error=None,
            )
        else:
            # 실패: 에러 정보 저장
            error_code = "OCR_REQUIRED" if result.needs_ocr else "EXTRACTION_FAILED"
            response_data = ResumeParseData(
                resume_id=resume_id,
                status=ResumeStatus.FAILED,
                result=None,
                error=ErrorDetail(code=error_code, detail=result.error_message),
            )

        # 결과 저장 (GET 조회용)
        self._resume_store[resume_id] = response_data.model_dump()

        return response_data

    async def get_resume(self, resume_id: int) -> ResumeGetData:
        """
        이력서 추출 결과 조회

        Args:
            resume_id: 이력서 ID

        Returns:
            ResumeGetData: 이력서 상태 및 결과
        """
        stored = self._resume_store.get(resume_id)

        if not stored:
            raise HTTPException(
                status_code=404,
                detail={"code": ResponseCode.NOT_FOUND.value, "data": {"resource": "resume", "id": resume_id}},
            )

        return ResumeGetData(**stored)


# 싱글톤 인스턴스
_controller: ResumesController | None = None


def get_resumes_controller() -> ResumesController:
    """컨트롤러 싱글톤 반환"""
    global _controller
    if _controller is None:
        _controller = ResumesController()
    return _controller
