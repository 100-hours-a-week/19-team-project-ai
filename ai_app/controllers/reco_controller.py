"""멘토 추천 API 컨트롤러"""

import os

from fastapi import HTTPException
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
from sqlalchemy.engine import Connection


class RecoController:
    """멘토 추천 API 컨트롤러"""

    def __init__(self, database_url: str | None = None):
        self.database_url = database_url or os.getenv(
            "DATABASE_URL",
            "postgresql://postgres:postgres@localhost:5432/devmentor",
        )
        self._engine = None

    @property
    def engine(self):
        """Lazy loading으로 엔진 생성"""
        if self._engine is None:
            self._engine = create_engine(self.database_url)
        return self._engine

    def get_connection(self) -> Connection:
        """DB 연결 반환"""
        return self.engine.connect()

    async def recommend_mentors(
        self,
        user_id: int,
        top_k: int = 5,
        only_verified: bool = False,
        include_eval: bool = False,
    ) -> MentorRecommendResponse:
        """사용자에게 멘토 추천"""
        with self.get_connection() as conn:
            retriever = MentorRetriever(conn)
            results = retriever.recommend_mentors(
                user_id=user_id,
                top_k=top_k,
                only_verified=only_verified,
                include_gt=include_eval,  # GT 검증도 함께 수행
            )

            if not results:
                raise HTTPException(
                    status_code=404,
                    detail={
                        "code": ResponseCode.NOT_FOUND.value,
                        "data": {
                            "message": "사용자를 찾을 수 없거나 추천할 멘토가 없습니다.",
                            "user_id": user_id,
                        },
                    },
                )

            recommendations = [MentorRecommendation(**result) for result in results]

            # 평가 결과 포함 (옵션)
            evaluation = None
            if include_eval:
                eval_result = retriever.evaluate_silver_ground_truth()
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
        with self.get_connection() as conn:
            retriever = MentorRetriever(conn)
            return retriever.update_all_expert_embeddings()

    async def compute_and_send_embedding(self, user_id: int) -> dict:
        """
        개별 멘토 임베딩 계산 후 백엔드 API로 전송

        회원가입 또는 프로필(기술스택, 직무) 변경 시 호출

        Returns:
            {"success": bool, "user_id": int, "message": str}
        """
        import httpx

        backend_url = os.getenv("BACKEND_API_URL", "http://localhost:8080/api/v1")

        with self.get_connection() as conn:
            retriever = MentorRetriever(conn)
            embedding_data = retriever.compute_embedding(user_id)

            if not embedding_data:
                return {
                    "success": False,
                    "user_id": user_id,
                    "message": "프로필 정보가 없어 임베딩을 생성할 수 없습니다.",
                }

            # 백엔드 API로 임베딩 전송
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.post(
                        f"{backend_url}/experts/embeddings",
                        json=embedding_data,
                    )
                    response.raise_for_status()

                return {
                    "success": True,
                    "user_id": user_id,
                    "message": "임베딩이 계산되어 백엔드로 전송되었습니다.",
                    "embedding_dim": len(embedding_data["embedding"]),
                }
            except httpx.HTTPStatusError as e:
                return {
                    "success": False,
                    "user_id": user_id,
                    "message": f"백엔드 API 오류: {e.response.status_code}",
                }
            except httpx.RequestError as e:
                return {
                    "success": False,
                    "user_id": user_id,
                    "message": f"백엔드 연결 실패: {e!s}",
                }

    async def evaluate_silver_ground_truth(
        self,
        sample_size: int | None = None,
        include_details: bool = False,
    ) -> EvaluationResponse:
        """Silver Ground Truth 평가 실행"""
        with self.get_connection() as conn:
            retriever = MentorRetriever(conn)
            result = retriever.evaluate_silver_ground_truth(
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
