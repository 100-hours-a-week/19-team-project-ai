"""현직자 피드백 데이터 수집 및 관리 서비스 — 채팅 로그 → Q&A 추출 → 마스킹 → 임베딩 → 저장"""

import logging
from typing import Any, Optional

from adapters.backend_client import BackendAPIClient, get_backend_client
from adapters.db_client import VectorSearchClient, get_vector_search_client
from adapters.llm_client import LLMClient, get_llm_client
from prompts import load_prompt
from schemas.feedback import ExpertFeedback

from services.reco.embedder import ProfileEmbedder, get_embedder
from services.repo.pii_masker import mask_pii_regex

logger = logging.getLogger(__name__)


class FeedbackCollector:
    """현직자 피드백 데이터 수집 및 관리 서비스"""

    def __init__(
        self,
        backend_client: Optional[BackendAPIClient] = None,
        embedder: Optional[ProfileEmbedder] = None,
        llm: Optional[LLMClient] = None,
        vector_client: Optional[VectorSearchClient] = None,
    ):
        self.backend_client = backend_client or get_backend_client()
        self.embedder = embedder or get_embedder()
        self.llm = llm or get_llm_client()
        self.vector_client = vector_client or get_vector_search_client()

    # ============== Phase B: 피드백 검색 (RAG용) ==============

    async def search_feedbacks(
        self,
        query_text: str,
        job_tag: Optional[str] = None,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """
        쿼리 텍스트로 피드백 벡터 검색

        Args:
            query_text: 검색할 텍스트
            job_tag: 직무 필터 (None이면 전체)
            top_k: 반환할 결과 수

        Returns:
            [{id, question, answer, job_tag, question_type, mentor_id, quality_score, similarity_score}, ...]
        """
        # 쿼리 임베딩 생성
        query_embedding = await self.embedder.embed_text(query_text, is_query=True)
        embedding_list = query_embedding.tolist()

        # DB에서 벡터 검색
        results = await self.vector_client.search_feedbacks(
            query_embedding=embedding_list,
            top_k=top_k,
            job_tag=job_tag,
        )

        logger.info(f"피드백 검색 완료: {len(results)}건 (query={query_text[:50]}...)")
        return results

    # ============== Phase A: 채팅 로그 → 피드백 변환 ==============

    async def extract_feedbacks_from_chat(self, chat_room_id: int, mentor_id: int) -> list[ExpertFeedback]:
        """
        채팅 로그에서 가치 있는 Q&A를 추출하고 개인정보를 마스킹한다.

        Args:
            chat_room_id: 채팅방 ID
            mentor_id: 멘토 user_id

        Returns:
            추출된 ExpertFeedback 리스트
        """
        # 1. DB에서 채팅 메시지 직접 조회
        messages = await self.vector_client.get_chat_messages(chat_room_id)
        if not messages:
            logger.info(f"채팅 메시지 없음: room_id={chat_room_id}")
            return []

        # 2. 대화 로그를 텍스트로 변환
        chat_log = self._format_chat_log(messages)
        if not chat_log.strip():
            return []

        # 3. 정규식 1차 마스킹
        chat_log = mask_pii_regex(chat_log)

        # 4. LLM으로 Q&A 추출 + 2차 마스킹
        extracted = await self._extract_qa_pairs(chat_log)
        if not extracted:
            logger.info(f"추출된 Q&A 없음: room_id={chat_room_id}")
            return []

        # 5. ExpertFeedback 객체로 변환
        feedbacks = []
        for item in extracted:
            if item.get("quality_score", 0) < 3:
                continue
            feedbacks.append(
                ExpertFeedback(
                    mentor_id=mentor_id,
                    question=item["question"],
                    answer=item["answer"],
                    job_tag=item.get("job_tag", "common"),
                    question_type=item.get("question_type", "career_advice"),
                    source_type="real_mentor",
                    quality_score=item.get("quality_score", 3),
                )
            )

        logger.info(f"채팅에서 {len(feedbacks)}개 Q&A 추출: room_id={chat_room_id}")
        return feedbacks

    async def process_and_save_chat(self, chat_room_id: int, mentor_id: int) -> int:
        """
        채팅 로그 → Q&A 추출 → 임베딩 → 백엔드 API 저장까지 전체 파이프라인

        Returns:
            저장된 피드백 수
        """
        # 1. Q&A 추출
        feedbacks = await self.extract_feedbacks_from_chat(chat_room_id, mentor_id)
        if not feedbacks:
            return 0

        # 2. 임베딩 생성
        feedback_dicts = []
        for fb in feedbacks:
            embedding_text = f"질문: {fb.question}\n답변: {fb.answer}"
            embedding = await self.embedder.embed_text(embedding_text, is_query=False)

            feedback_dicts.append(
                {
                    "mentor_id": fb.mentor_id,
                    "question": fb.question,
                    "answer": fb.answer,
                    "job_tag": fb.job_tag,
                    "question_type": fb.question_type,
                    "embedding_text": embedding_text,
                    "source_type": fb.source_type,
                    "quality_score": fb.quality_score,
                    "embedding": embedding.tolist(),
                }
            )

        # 3. 백엔드 API로 저장
        inserted = await self.backend_client.save_feedbacks_batch(feedback_dicts)
        logger.info(f"피드백 저장 완료: room_id={chat_room_id}, {inserted}건")
        return inserted

    async def process_all_closed_chats(self) -> int:
        """
        종료된 전체 채팅방에서 피드백 추출 → 저장 (배치)

        Returns:
            총 저장된 피드백 수
        """
        rooms = await self.vector_client.get_closed_chat_rooms()
        if not rooms:
            logger.info("종료된 채팅방 없음")
            return 0

        logger.info(f"피드백 추출 대상: {len(rooms)}개 채팅방")
        total = 0

        for room in rooms:
            if room["msg_count"] < 4:
                continue
            try:
                count = await self.process_and_save_chat(
                    chat_room_id=room["room_id"],
                    mentor_id=room["expert_id"],
                )
                total += count
            except Exception as e:
                logger.error(f"채팅방 {room['room_id']} 처리 실패: {e}")

        logger.info(f"전체 피드백 추출 완료: {total}건")
        return total

    # ============== 내부 헬퍼 ==============

    def _format_chat_log(self, messages: list[dict]) -> str:
        """채팅 메시지 리스트를 텍스트 형식으로 변환"""
        lines = []
        for msg in messages:
            if msg.get("message_type") != "TEXT":
                continue
            content = msg.get("content", "").strip()
            if not content:
                continue

            sender_type = msg.get("sender_type", "UNKNOWN")
            role = "[멘토]" if sender_type == "EXPERT" else "[멘티]"
            lines.append(f"{role} {content}")

        return "\n".join(lines)

    async def _extract_qa_pairs(self, chat_log: str) -> list[dict]:
        """LLM을 사용하여 채팅 로그에서 Q&A 쌍 추출 + 개인정보 마스킹"""
        system_prompt = load_prompt("feedback_extract_system")

        user_prompt = f"""## 멘토링 대화 로그
{chat_log}

위 대화에서 가치 있는 Q&A 쌍을 추출하고 개인정보를 마스킹하세요. JSON 배열로 반환하세요."""

        try:
            result = await self.llm.generate_json(
                prompt=user_prompt,
                system_instruction=system_prompt,
                temperature=0.1,
            )
            # generate_json이 dict를 반환할 수 있으므로 리스트 확인
            if isinstance(result, list):
                return result
            if isinstance(result, dict) and "feedbacks" in result:
                return result["feedbacks"]
            return []
        except Exception as e:
            logger.error(f"Q&A 추출 실패: {e}")
            return []


# 싱글톤
_collector: Optional[FeedbackCollector] = None


def get_feedback_collector() -> FeedbackCollector:
    global _collector
    if _collector is None:
        _collector = FeedbackCollector()
    return _collector
