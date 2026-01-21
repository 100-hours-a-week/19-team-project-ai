"""이력서 라우터 - 이력서 추출 API 엔드포인트"""

import os
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, UploadFile, HTTPException

from controllers.resumes_controller import ResumesController, get_resumes_controller
from schemas.common import ApiResponse, ResponseCode
from schemas.resumes import (
    ResumeParseData,
    ResumeParseRequest,
    ResumeUploadData,
)

router = APIRouter(prefix="/resumes", tags=["Resumes"])

# 업로드 디렉토리 설정
UPLOAD_DIR = Path(__file__).parent.parent.parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

# 간단한 resume_id 카운터 (테스트용)
_resume_id_counter = 0

# 업로드된 파일 경로 저장 (테스트용)
_uploaded_files: dict[int, Path] = {}


@router.post(
    "/upload",
    response_model=ApiResponse[ResumeUploadData],
    summary="[임시] PDF 파일 업로드",
    description="PDF 파일을 업로드하고 resume_id를 반환합니다. (테스트용)",
    responses={
        200: {"description": "업로드 성공"},
        400: {"description": "PDF 파일이 아님"},
        500: {"description": "서버 오류"},
    },
)
async def upload_resume(
    file: UploadFile = File(..., description="PDF 파일"),
) -> ApiResponse[ResumeUploadData]:
    """[임시] PDF 파일 업로드 - resume_id 반환"""
    global _resume_id_counter
    
    # PDF 파일 검증
    if not file.content_type or "pdf" not in file.content_type.lower():
        raise HTTPException(
            status_code=400,
            detail={"code": ResponseCode.BAD_REQUEST.value, "data": {"message": "PDF 파일만 업로드 가능합니다."}},
        )
    
    # resume_id 생성
    _resume_id_counter += 1
    resume_id = _resume_id_counter
    
    # 파일 저장
    file_name = f"{resume_id}_{uuid.uuid4().hex[:8]}.pdf"
    file_path = UPLOAD_DIR / file_name
    
    content = await file.read()
    with open(file_path, "wb") as f:
        f.write(content)
    
    # 파일 경로 저장
    _uploaded_files[resume_id] = file_path
    
    return ApiResponse(
        code=ResponseCode.OK,
        data=ResumeUploadData(resume_id=resume_id, file_path=str(file_path)),
    )


@router.post(
    "/{resume_id}/parse",
    response_model=ApiResponse[ResumeParseData],
    summary="이력서 추출 파이프라인 실행",
    description="업로드된 PDF 파일에서 이력서 정보를 추출합니다.",
    responses={
        200: {"description": "추출 완료/실패"},
        404: {"description": "resume_id 없음"},
        500: {"description": "서버 오류"},
    },
)
async def parse_resume(
    resume_id: int,
    enable_pii_masking: bool = True,
    controller: ResumesController = Depends(get_resumes_controller),
) -> ApiResponse[ResumeParseData]:
    """이력서 추출 실행 - 업로드된 파일 사용"""
    # 업로드된 파일 확인
    file_path = _uploaded_files.get(resume_id)
    if not file_path or not file_path.exists():
        raise HTTPException(
            status_code=404,
            detail={"code": ResponseCode.NOT_FOUND.value, "data": {"resource": "resume", "id": resume_id}},
        )
    
    # 파일 읽기
    with open(file_path, "rb") as f:
        pdf_bytes = f.read()
    
    # 파싱 실행
    result = await controller.parse_resume_from_bytes(resume_id, pdf_bytes, enable_pii_masking)
    return ApiResponse(code=ResponseCode.OK, data=result)
