"""멘토 추천 API 라우터"""

from controllers.reco_controller import RecoController, get_reco_controller
from fastapi import APIRouter, Depends, Query
from schemas.common import ApiResponse, ResponseCode
from schemas.reco import MentorRecommendResponse

router = APIRouter(prefix="/mentors", tags=["Mentors"])


@router.get(
    "/recommend/{user_id}",
    response_model=ApiResponse[MentorRecommendResponse],
    summary="멘토 추천",
    description="사용자 프로필 기반으로 유사한 멘토를 추천합니다. (1차: 직무 필터링, 2차: 기술스택 필터링, 정렬: 임베딩 유사도)",
)
async def recommend_mentors(
    user_id: int,
    top_k: int = Query(default=3, ge=1, le=20, description="추천 개수"),
    only_verified: bool = Query(default=False, description="인증 멘토만 추천"),
    include_eval: bool = Query(default=True, description="평가 결과 포함"),
    controller: RecoController = Depends(get_reco_controller),
) -> ApiResponse[MentorRecommendResponse]:
    """사용자에게 멘토 추천"""
    result = await controller.recommend_mentors(
        user_id=user_id,
        top_k=top_k,
        only_verified=only_verified,
        include_eval=include_eval,
    )
    return ApiResponse(code=ResponseCode.OK, data=result)


@router.post(
    "/embeddings/update",
    response_model=ApiResponse[dict],
    summary="멘토 임베딩 일괄 업데이트 (테스트용)",
    description="모든 멘토의 프로필 임베딩을 일괄 업데이트합니다.",
)
async def update_all_embeddings(
    controller: RecoController = Depends(get_reco_controller),
) -> ApiResponse[dict]:
    """모든 멘토 임베딩 업데이트"""
    updated_count = await controller.update_all_embeddings()
    return ApiResponse(
        code=ResponseCode.OK,
        data={"updated_count": updated_count, "message": f"{updated_count}명의 멘토 임베딩이 업데이트되었습니다."},
    )


@router.put(
    "/embeddings/{user_id}",
    response_model=ApiResponse[dict],
    summary="멘토 임베딩 개별 업데이트",
    description="특정 멘토의 프로필 임베딩을 계산하여 백엔드 API로 전송합니다. 회원가입 또는 프로필(기술스택, 직무) 변경 시 호출하세요.",
)
async def update_mentor_embedding(
    user_id: int,
    controller: RecoController = Depends(get_reco_controller),
) -> ApiResponse[dict]:
    """개별 멘토 임베딩 계산 및 백엔드 전송"""
    result = await controller.compute_and_send_embedding(user_id)
    if result["success"]:
        return ApiResponse(code=ResponseCode.OK, data=result)
    else:
        return ApiResponse(code=ResponseCode.NOT_FOUND, data=result)
