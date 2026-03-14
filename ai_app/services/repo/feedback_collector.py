import logging
from typing import Any, Optional
from adapters.backend_client import BackendAPIClient, get_backend_client
from services.reco.embedder import ProfileEmbedder, get_embedder
from schemas.feedback import ExpertFeedback

logger = logging.getLogger(__name__)

class FeedbackCollector:
    """현직자 피드백 데이터 수집 및 관리 서비스"""

    def __init__(
        self, 
        backend_client: Optional[BackendAPIClient] = None,
        embedder: Optional[ProfileEmbedder] = None
    ):
        self.backend_client = backend_client or get_backend_client()
        self.embedder = embedder or get_embedder()

    async def collect_from_mentoring_history(self, limit: int = 100) -> list[ExpertFeedback]:
        """
        기존 멘토링 이력에서 Q&A 데이터를 추출하여 피드백 객체 리스트로 변환
        (현재는 Mock 또는 백엔드 특정 엔드포인트 연동 필요)
        """
        # TODO: 백엔드 API에 멘토링 이력 조회 엔드포인트 추가 시 연동
        # 지금은 설계를 위해 샘플 데이터를 반환하는 구조로 잡음
        logger.info(f"멘토링 이력에서 {limit}개의 피드백 수집 시작")
        
        # 실제 구현 시에는 self.backend_client.get_mentoring_history() 호출
        samples = [
            ExpertFeedback(
                question="백엔드 신입으로 취업하고 싶은데 어떤 프로젝트가 경쟁력 있을까요?",
                answer="단순한 CRUD보다는 대용량 트래픽 처리를 고려한 아키텍처나, MSA 기반의 분산 시스템 경험이 담긴 프로젝트가 좋습니다.",
                job_tag="백엔드",
                question_type="프로젝트"
            ),
            ExpertFeedback(
                question="비전공자인데 자바 공부는 어떻게 시작하는 게 좋을까요?",
                answer="자바의 정석 같은 기본서로 문법을 익히되, 반드시 Spring Framework를 활용한 실무 프로젝트를 병행하세요.",
                job_tag="백엔드",
                question_type="기술스택"
            )
        ]
        return samples

    async def prepare_rag_dataset(self, feedbacks: list[ExpertFeedback]):
        """
        수집된 피드백 데이터에 대해 임베딩을 생성하고 저장 준비
        """
        for fb in feedbacks:
            # 질문과 답변을 결합하여 컨텍스트 임베딩 생성
            text_to_embed = f"질문: {fb.question}\n답변: {fb.answer}"
            embedding = await self.embedder.embed_text(text_to_embed)
            fb.embedding = embedding.tolist()
            
        logger.info(f"{len(feedbacks)}개의 피드백 데이터 임베딩 완료")
        return feedbacks

# 싱글톤
_collector: Optional[FeedbackCollector] = None

def get_feedback_collector() -> FeedbackCollector:
    global _collector
    if _collector is None:
        _collector = FeedbackCollector()
    return _collector
