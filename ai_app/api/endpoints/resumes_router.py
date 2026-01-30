"""이력서 라우터 - 이력서 추출 API 엔드포인트"""

import time

import httpx
from controllers.resumes_controller import ResumesController, get_resumes_controller
from fastapi import APIRouter, Depends, HTTPException
from schemas.common import ApiResponse, ResponseCode
from schemas.resumes import ResumeData, ResumeParseRequest

from middleware.cloudwatch_metrics import metrics_service

router = APIRouter(prefix="/resumes", tags=["Resumes"])


@router.post(
    "/{task_id}/parse",
    response_model=ApiResponse[ResumeData],
    summary="이력서 추출 파이프라인 실행",
    description="S3 URL에서 PDF를 다운로드하여 이력서 정보를 추출합니다.",
    responses={
        200: {"description": "추출 완료/실패"},
        400: {"description": "잘못된 요청"},
        500: {"description": "서버 오류"},
    },
)
async def parse_resume(
    task_id: int,
    request: ResumeParseRequest,
    controller: ResumesController = Depends(get_resumes_controller),
) -> ApiResponse[ResumeData]:
    """이력서 추출 실행 - S3 URL에서 PDF 다운로드 후 파싱"""

    # 메트릭 시작
    start_time = time.time()
    success = False

    try:
        # S3에서 PDF 다운로드
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(request.file_url)
                response.raise_for_status()
                pdf_bytes = response.content
        except httpx.HTTPStatusError as e:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": ResponseCode.BAD_REQUEST.value,
                    "data": {"message": f"PDF 다운로드 실패: {e.response.status_code}"},
                },
            )
        except httpx.RequestError as e:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": ResponseCode.BAD_REQUEST.value,
                    "data": {"message": f"PDF 다운로드 오류: {e!s}"},
                },
            )

        # Content-Type 검증
        content_type = response.headers.get("content-type", "")
        if "pdf" not in content_type.lower() and not request.file_url.lower().endswith(".pdf"):
            raise HTTPException(
                status_code=400,
                detail={
                    "code": ResponseCode.BAD_REQUEST.value,
                    "data": {"message": "PDF 파일이 아닙니다."},
                },
            )

        # 파싱 실행 (mode는 향후 async 처리 구현 시 사용)
        enable_pii_masking = True  # 기본값
        result = await controller.parse_resume_from_bytes(task_id, pdf_bytes, enable_pii_masking)

        # 성공 표시
        success = True

        return ApiResponse(code=ResponseCode.OK, data=result)

    # 메트릭 전송 (finally)
    finally:
        duration = time.time() - start_time
        metrics_service.track_request(feature="DocumentAnalysis", success=success, duration=duration)
