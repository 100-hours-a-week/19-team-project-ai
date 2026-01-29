"""채용공고 API 라우터"""

from fastapi import APIRouter, Depends
from controllers.jobs_controller import JobsController, get_jobs_controller
from schemas.common import ApiResponse, ResponseCode
from schemas.jobs import JobParseRequest, JobPosting


router = APIRouter(prefix="/jobs", tags=["Jobs"])


@router.post(
    "/parse",
    response_model=ApiResponse[JobPosting],
    summary="채용공고 URL 파싱",
    description="채용공고 URL을 입력하면 상세 정보를 파싱하여 반환합니다. (사람인, 잡코리아, 원티드 지원)",
)
async def parse_job_url(
    request: JobParseRequest,
    controller: JobsController = Depends(get_jobs_controller),
) -> ApiResponse[JobPosting]:
    """채용공고 URL 파싱"""
    result = await controller.parse_job_url(request.url)
    return ApiResponse(code=ResponseCode.OK, data=result)
