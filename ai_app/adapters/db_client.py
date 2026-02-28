"""pgvector 직접 검색 DB 클라이언트 — 임베딩 조회 및 벡터 유사도 검색"""

import logging
import os
from typing import Any

import asyncpg
from opentelemetry import trace

logger = logging.getLogger(__name__)

# 기본 타임아웃 (초)
DEFAULT_TIMEOUT = 30.0

# 커넥션 풀 (싱글톤)
_pool: asyncpg.Pool | None = None


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
            timeout=DEFAULT_TIMEOUT,
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
        exclude_user_id: int | None = None,
    ) -> list[dict[str, Any]]:
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

    async def get_expert_embeddings_exist(self, user_ids: list[int]) -> list[int]:
        """임베딩이 존재하는 멘토 ID 목록 조회"""
        pool = await get_pool()
        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT user_id FROM expert_profiles
                    WHERE user_id = ANY($1::int[]) AND embedding IS NOT NULL
                    """,
                    user_ids,
                )
            return [row["user_id"] for row in rows]
        except Exception as e:
            logger.error(f"임베딩 존재 확인 실패: {e}")
            raise


# 싱글톤
_client: VectorSearchClient | None = None
tracer = trace.get_tracer(__name__)


def get_vector_search_client() -> VectorSearchClient:
    """VectorSearchClient 싱글톤"""
    global _client
    if _client is None:
        _client = VectorSearchClient()
    return _client
