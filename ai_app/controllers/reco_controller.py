"""멘토 추천 API 컨트롤러"""

import logging
import os
from typing import Any, ContextManager

from adapters.backend_client import BackendAPIClient, get_backend_client
from fastapi import HTTPException
from middleware.otel_lgtm_metrics import tracked_db_connection
from schemas.common import ResponseCode
from schemas.reco import (
    EvaluationDetail,
    EvaluationResponse,
    EvaluationSummary,
    MentorRecommendation,
    MentorRecommendResponse,
)
from services.reco.retrieval import MentorRetriever
from sqlalchemy import create_engine


class RecoController:
    """멘토 추천 API 컨트롤러"""

    def __init__(self, backend_client: BackendAPIClient | None = None):
        self.backend_client = backend_client or get_backend_client()
        self.database_url = os.getenv("DATABASE_URL")
        self._engine = None

    @property
    def engine(self):
        """Lazy loading으로 엔진 생성"""
        if self._engine is None and self.database_url:
            self._engine = create_engine(self.database_url)
        return self._engine

    def get_connection(self) -> ContextManager:
        """DB 연결 반환"""
        return tracked_db_connection(self.engine)

    def _get_retriever(self) -> MentorRetriever:
        """MentorRetriever 인스턴스 생성"""
        return MentorRetriever(backend_client=self.backend_client)

    async def recommend_mentors(
        self,
        user_id: int,
        top_k: int = 3,
        only_verified: bool = False,
        include_eval: bool = False,
        background_tasks: Any | None = None,
    ) -> MentorRecommendResponse:
        """사용자에게 멘토 추천"""
        retriever = self._get_retriever()
        results = await retriever.recommend_mentors(
            user_id=user_id,
            top_k=top_k,
            only_verified=only_verified,
            include_gt=include_eval,
        )

        if not results:
            # [자동 감지] 임베딩이 누락된 전문가가 있는 경우 백그라운드 업데이트 트리거
            status = await retriever.vector_search_client.get_embedding_status()
            if status["total_count"] > 0 and status["embedded_count"] < status["total_count"]:
                if background_tasks:
                    logger = logging.getLogger(__name__)
                    missing = status["total_count"] - status["embedded_count"]
                    logger.warning(
                        f"🚨 임베딩 누락 자동 감지: {missing}명의 전문가 임베딩이 없습니다. 전체 일괄 업데이트를 백그라운드에서 시작합니다."
                    )
                    background_tasks.add_task(self.update_all_embeddings)
            # 유저 존재 여부 확인 (탈퇴한 유저 포함)
            user_exists = await self.backend_client.user_exists(user_id)

            if not user_exists:
                raise HTTPException(
                    status_code=404,
                    detail={
                        "code": ResponseCode.NOT_FOUND.value,
                        "data": {
                            "message": f"ID가 {user_id}인 사용자를 찾을 수 없거나 탈퇴한 사용자입니다.",
                            "user_id": user_id,
                        },
                    },
                )

            # 프로필 텍스트 확인 (직무/기술스택 등 필수 정보 부족 여부)
            profile_text = await retriever.get_user_profile_text(user_id)
            if not profile_text:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "code": ResponseCode.BAD_REQUEST.value,
                        "data": {
                            "message": "사용자의 프로필 정보(직무, 기술스택, 자기소개)가 부족하여 추천을 진행할 수 없습니다. 프로필을 먼저 완성해 주세요.",
                            "user_id": user_id,
                        },
                    },
                )

            # Fallback: 응답률 높은 순으로 멘토 추천
            logger = logging.getLogger(__name__)
            logger.info(f"유사도 기반 추천 결과 없음 (user_id={user_id}), 응답률 기반 fallback 실행")

            results = await retriever.fallback_by_response_rate(top_k=top_k)

        recommendations = [MentorRecommendation(**result) for result in results]

        # 평가 결과 포함 (요청 시에만 일부 샘플에 대해 수행)
        evaluation = None
        if include_eval:
            eval_result = await retriever.evaluate_silver_ground_truth(sample_size=3)
            evaluation = EvaluationSummary(
                hit_at_1=eval_result["hit_at_1"],
                hit_at_3=eval_result["hit_at_3"],
                hit_at_5=eval_result["hit_at_5"],
                hit_at_10=eval_result["hit_at_10"],
                mrr=eval_result["mrr"],
                total=eval_result["total"],
            )

        return MentorRecommendResponse(
            user_id=user_id,
            recommendations=recommendations,
            total_count=len(recommendations),
            evaluation=evaluation,
        )

    async def update_all_embeddings(self) -> int:
        """모든 멘토 임베딩 일괄 업데이트"""
        retriever = self._get_retriever()
        return await retriever.update_all_expert_embeddings()

    async def compute_and_send_embedding(self, user_id: int) -> dict:
        """
        개별 멘토 임베딩 계산 후 백엔드 API 및 로컬 DB 저장
        """
        retriever = self._get_retriever()
        success = await retriever.update_expert_embedding(user_id)

        if success:
            return {
                "success": True,
                "user_id": user_id,
                "message": "임베딩이 성공적으로 업데이트되었습니다 (로컬 DB 및 백엔드).",
            }
        else:
            return {
                "success": False,
                "user_id": user_id,
                "message": "임베딩 업데이트에 실패했습니다. 프로필 존재 여부와 네트워크 상태를 확인하세요.",
            }

    async def evaluate_silver_ground_truth(
        self,
        sample_size: int | None = None,
        include_details: bool = False,
    ) -> EvaluationResponse:
        """Silver Ground Truth 평가 실행"""
        retriever = self._get_retriever()
        result = await retriever.evaluate_silver_ground_truth(
            sample_size=sample_size,
        )

        details = []
        if include_details:
            details = [EvaluationDetail(**d) for d in result["details"]]

        return EvaluationResponse(
            hit_at_1=result["hit_at_1"],
            hit_at_3=result["hit_at_3"],
            hit_at_5=result["hit_at_5"],
            hit_at_10=result["hit_at_10"],
            mrr=result["mrr"],
            total=result["total"],
            details=details,
        )


# 싱글톤
_controller: RecoController | None = None


def get_reco_controller() -> RecoController:
    """컨트롤러 싱글톤"""
    global _controller
    if _controller is None:
        _controller = RecoController()
    return _controller
