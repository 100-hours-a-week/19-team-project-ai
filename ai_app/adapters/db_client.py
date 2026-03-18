"""pgvector 직접 검색 DB 클라이언트 — 임베딩 조회 및 벡터 유사도 검색"""

import logging
import os
from typing import Any, Dict, List, Optional

import asyncpg
from opentelemetry import trace

logger = logging.getLogger(__name__)

# 기본 타임아웃 (초)
DEFAULT_TIMEOUT = 30.0

# 커넥션 풀 (싱글톤)
_pool: Optional[asyncpg.Pool] = None


async def get_pool() -> asyncpg.Pool:
    """비동기 커넥션 풀 싱글톤"""
    global _pool
    if _pool is None:
        database_url = os.getenv("DATABASE_URL")
        if not database_url:
            raise RuntimeError("DATABASE_URL 환경변수가 설정되지 않았습니다.")

        _pool = await asyncpg.create_pool(
            dsn=database_url,
            min_size=5,
            max_size=20,
            command_timeout=60.0,
            timeout=60.0,
        )
        logger.info("✅ DB 커넥션 풀 초기화 완료")
    return _pool


async def close_pool() -> None:
    """커넥션 풀 종료"""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("DB 커넥션 풀 종료")


class VectorSearchClient:
    """pgvector 직접 검색 클라이언트"""

    async def search_similar_experts(
        self,
        query_embedding: list[float],
        top_n: int = 50,
        exclude_user_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        pgvector 코사인 유사도 기반 멘토 검색

        Args:
            query_embedding: 쿼리 임베딩 벡터 (1024차원)
            top_n: 반환할 최대 후보 수
            exclude_user_id: 제외할 유저 ID

        Returns:
            [{user_id, similarity_score}, ...]
        """
        pool = await get_pool()
        embedding_str = "[" + ",".join(str(v) for v in query_embedding) + "]"

        try:
            async with pool.acquire() as conn:
                if exclude_user_id is not None:
                    with tracer.start_as_current_span("db_fetch_experts_filtered"):
                        rows = await conn.fetch(
                            """
                            SELECT user_id,
                                   1 - (embedding <=> $1::vector) AS similarity_score
                            FROM expert_profiles
                            WHERE user_id != $2 AND embedding IS NOT NULL
                            ORDER BY embedding <=> $1::vector ASC
                            LIMIT $3
                            """,
                            embedding_str,
                            exclude_user_id,
                            top_n,
                        )
                else:
                    with tracer.start_as_current_span("db_fetch_experts_unfiltered"):
                        rows = await conn.fetch(
                            """
                            SELECT user_id,
                                   1 - (embedding <=> $1::vector) AS similarity_score
                            FROM expert_profiles
                            WHERE embedding IS NOT NULL
                            ORDER BY embedding <=> $1::vector ASC
                            LIMIT $2
                            """,
                            embedding_str,
                            top_n,
                        )

            results = [
                {
                    "user_id": row["user_id"],
                    "similarity_score": float(row["similarity_score"]),
                }
                for row in rows
            ]
            logger.info(f"벡터 검색 완료: {len(results)}명 후보")
            return results

        except Exception as e:
            logger.error(f"벡터 검색 실패: {e}")
            raise

    async def search_feedbacks(
        self,
        query_embedding: list[float],
        top_k: int = 5,
        job_tag: Optional[str] = None,
        min_quality: int = 3,
    ) -> List[Dict[str, Any]]:
        """
        expert_feedbacks 테이블에서 벡터 유사도 기반 피드백 검색

        Args:
            query_embedding: 쿼리 임베딩 벡터 (1024차원)
            top_k: 반환할 최대 결과 수
            job_tag: 직무 필터 (None이면 전체)
            min_quality: 최소 품질 점수

        Returns:
            [{id, question, answer, job_tag, question_type, mentor_id, quality_score, similarity_score}, ...]
        """
        pool = await get_pool()
        embedding_str = "[" + ",".join(str(v) for v in query_embedding) + "]"

        try:
            async with pool.acquire() as conn:
                with tracer.start_as_current_span("db_search_feedbacks"):
                    if job_tag:
                        rows = await conn.fetch(
                            """
                            SELECT id, question, answer, job_tag, question_type,
                                   mentor_id, quality_score,
                                   1 - (embedding <=> $1::vector) AS similarity_score
                            FROM expert_feedbacks
                            WHERE embedding IS NOT NULL
                              AND job_tag = $2
                              AND quality_score >= $3
                            ORDER BY embedding <=> $1::vector ASC
                            LIMIT $4
                            """,
                            embedding_str,
                            job_tag,
                            min_quality,
                            top_k,
                        )
                    else:
                        rows = await conn.fetch(
                            """
                            SELECT id, question, answer, job_tag, question_type,
                                   mentor_id, quality_score,
                                   1 - (embedding <=> $1::vector) AS similarity_score
                            FROM expert_feedbacks
                            WHERE embedding IS NOT NULL
                              AND quality_score >= $2
                            ORDER BY embedding <=> $1::vector ASC
                            LIMIT $3
                            """,
                            embedding_str,
                            min_quality,
                            top_k,
                        )

            results = [
                {
                    "id": row["id"],
                    "question": row["question"],
                    "answer": row["answer"],
                    "job_tag": row["job_tag"],
                    "question_type": row["question_type"],
                    "mentor_id": row["mentor_id"],
                    "quality_score": row["quality_score"],
                    "similarity_score": float(row["similarity_score"]),
                }
                for row in rows
            ]
            logger.info(f"피드백 벡터 검색 완료: {len(results)}건 (job_tag={job_tag})")
            return results

        except Exception as e:
            logger.error(f"피드백 벡터 검색 실패: {e}")
            raise

    # ---------- 채팅 메시지 조회 ----------

    async def get_chat_messages(
        self, chat_room_id: int
    ) -> List[Dict[str, Any]]:
        """
        채팅방의 전체 메시지를 시간순으로 조회

        Args:
            chat_room_id: 채팅방 ID

        Returns:
            [{sender_id, content, message_type, created_at}, ...]
        """
        pool = await get_pool()
        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT cm.sender_id, cm.content, cm.message_type, cm.created_at,
                           CASE WHEN cm.sender_id = cr.receiver_id THEN 'EXPERT'
                                ELSE 'USER' END AS sender_type
                    FROM chat_messages cm
                    JOIN chat_rooms cr ON cr.id = cm.chat_room_id
                    WHERE cm.chat_room_id = $1
                    ORDER BY cm.room_sequence ASC
                    """,
                    chat_room_id,
                )

            results = [
                {
                    "sender_id": row["sender_id"],
                    "content": row["content"],
                    "message_type": row["message_type"],
                    "sender_type": row["sender_type"],
                    "created_at": str(row["created_at"]),
                }
                for row in rows
            ]
            logger.info(f"채팅 메시지 조회: room_id={chat_room_id}, {len(results)}건")
            return results

        except Exception as e:
            logger.error(f"채팅 메시지 조회 실패 (room_id={chat_room_id}): {e}")
            raise

    async def get_closed_chat_rooms(
        self, limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        종료된 채팅방 목록 조회 (피드백 추출 대상)

        Returns:
            [{room_id, expert_id, requester_id, msg_count, closed_at}, ...]
        """
        pool = await get_pool()
        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT cr.id AS room_id, cr.receiver_id AS expert_id,
                           cr.requester_id, cr.closed_at,
                           (SELECT count(*) FROM chat_messages cm
                            WHERE cm.chat_room_id = cr.id) AS msg_count
                    FROM chat_rooms cr
                    WHERE cr.status = 'CLOSED'
                    ORDER BY cr.closed_at DESC NULLS LAST
                    LIMIT $1
                    """,
                    limit,
                )

            return [
                {
                    "room_id": row["room_id"],
                    "expert_id": row["expert_id"],
                    "requester_id": row["requester_id"],
                    "msg_count": row["msg_count"],
                    "closed_at": str(row["closed_at"]) if row["closed_at"] else None,
                }
                for row in rows
            ]

        except Exception as e:
            logger.error(f"종료된 채팅방 조회 실패: {e}")
            raise

    async def get_embedding_status(self) -> dict[str, int]:
        """전체 현직자 수 및 임베딩 완료된 현직자 수 조회"""
        pool = await get_pool()
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT
                        count(*) as total_count,
                        count(embedding) as embedded_count
                    FROM expert_profiles
                    """
                )
            return {"total_count": row["total_count"], "embedded_count": row["embedded_count"]}
        except Exception as e:
            logger.error(f"임베딩 상태 조회 실패: {e}")
            return {"total_count": 0, "embedded_count": 0}


# 싱글톤
_client: Optional[VectorSearchClient] = None
tracer = trace.get_tracer(__name__)


def get_vector_search_client() -> VectorSearchClient:
    """VectorSearchClient 싱글톤"""
    global _client
    if _client is None:
        _client = VectorSearchClient()
    return _client
