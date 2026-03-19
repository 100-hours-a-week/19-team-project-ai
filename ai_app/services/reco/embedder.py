import asyncio
import logging
import os
from collections import OrderedDict
from functools import lru_cache
from typing import Optional

import httpx
import numpy as np
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

# 전역 HTTP 클라이언트 (커넥션 풀 공유)
_async_client: Optional[httpx.AsyncClient] = None

# 임베딩 캐시 최대 크기
EMBEDDING_CACHE_MAX_SIZE = 512


async def get_async_client() -> httpx.AsyncClient:
    global _async_client
    if _async_client is None or _async_client.is_closed:
        _async_client = httpx.AsyncClient(timeout=30.0)
    return _async_client


class ProfileEmbedder:
    """프로필 텍스트 임베딩 생성 (로컬 모델 or RunPod API)"""

    def __init__(self, model_name: str = "intfloat/multilingual-e5-large-instruct"):
        self.model_name = model_name
        self._model: Optional[SentenceTransformer] = None

        # RunPod 설정
        self.use_runpod = os.getenv("USE_RUNPOD_EMBEDDING", "false").lower() == "true"
        self.runpod_api_key = os.getenv("RUNPOD_API_KEY")
        self.runpod_endpoint_id = os.getenv("RUNPOD_EMBEDDING_ENDPOINT_ID")
        self.runpod_url = (
            f"https://api.runpod.ai/v2/{self.runpod_endpoint_id}/runsync" if self.runpod_endpoint_id else None
        )
        # 메모리 캐시 (LRU, 크기 제한)
        self._cache: OrderedDict = OrderedDict()
        self._cache_max_size = EMBEDDING_CACHE_MAX_SIZE

    @property
    def model(self) -> SentenceTransformer:
        """Lazy loading으로 모델 로드"""
        if self._model is None:
            logger.info(f"Loading embedding model: {self.model_name}")
            self._model = SentenceTransformer(self.model_name)
            logger.info("Embedding model loaded successfully")
        return self._model

    def _put_cache(self, key: tuple, value: np.ndarray) -> None:
        """LRU 캐시에 저장 (크기 초과 시 가장 오래된 항목 제거)"""
        if key in self._cache:
            self._cache.move_to_end(key)
        else:
            if len(self._cache) >= self._cache_max_size:
                self._cache.popitem(last=False)
        self._cache[key] = value

    async def embed_text(self, text: str, is_query: bool = True) -> np.ndarray:
        """단일 텍스트 임베딩 생성 (캐싱 + 스레드풀 지원)"""
        cache_key = (text, is_query)
        if cache_key in self._cache:
            self._cache.move_to_end(cache_key)
            return self._cache[cache_key]

        if self.use_runpod and self.runpod_url and self.runpod_api_key:
            try:
                embedding = (await self._embed_via_runpod([text], is_query))[0]
                self._put_cache(cache_key, embedding)
                return embedding
            except Exception as e:
                logger.error(f"RunPod embedding failed, falling back to local: {e}")

        encode_text = text
        if "e5" in self.model_name.lower():
            prefix = "query" if is_query else "passage"
            encode_text = f"{prefix}: {text}"

        # CPU-bound 연산을 스레드풀에서 실행하여 이벤트 루프 블로킹 방지
        loop = asyncio.get_running_loop()
        embedding = await loop.run_in_executor(None, lambda: self.model.encode(encode_text, normalize_embeddings=True))
        self._put_cache(cache_key, embedding)
        return embedding

    async def embed_texts(self, texts: list[str]) -> np.ndarray:
        """여러 텍스트 임베딩 생성 (스레드풀 지원)"""
        if self.use_runpod and self.runpod_url and self.runpod_api_key:
            try:
                return await self._embed_via_runpod(texts, is_query=False)
            except Exception as e:
                logger.error(f"RunPod batch embedding failed, falling back to local: {e}")

        encode_texts = texts
        if "e5" in self.model_name.lower():
            encode_texts = [f"passage: {t}" for t in texts]

        # CPU-bound 배치 연산을 스레드풀에서 실행
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: self.model.encode(encode_texts, normalize_embeddings=True))

    async def _embed_via_runpod(self, texts: list[str], is_query: bool = True) -> np.ndarray:
        """RunPod Serverless API를 통한 임베딩 생성 (polling 방식)"""
        if not self.runpod_endpoint_id or not self.runpod_api_key:
            raise RuntimeError("RunPod configuration missing (Endpoint ID or API Key)")

        headers = {"Authorization": f"Bearer {self.runpod_api_key}", "Content-Type": "application/json"}
        payload = {"input": {"texts": texts, "is_query": is_query}}

        try:
            client = await get_async_client()
            # 1. 작업 요청 (/run)
            run_url = f"https://api.runpod.ai/v2/{self.runpod_endpoint_id}/run"
            response = await client.post(run_url, headers=headers, json=payload)
            response.raise_for_status()
            job_data = response.json()
            job_id = job_data.get("id")

            if not job_id:
                raise RuntimeError(f"Failed to get job ID from RunPod: {job_data}")

            # 2. 결과 대기 (polling)
            status_url = f"https://api.runpod.ai/v2/{self.runpod_endpoint_id}/status/{job_id}"
            import asyncio

            max_retries = 150  # 총 150초 대기
            logger.info(f"RunPod 작업 시작됨 (ID: {job_id}). 결과를 기다리는 중...")

            for i in range(max_retries):
                status_response = await client.get(status_url, headers=headers)
                status_response.raise_for_status()
                result = status_response.json()

                status = result.get("status")
                if status == "COMPLETED":
                    return np.array(result["output"])
                elif status in ["FAILED", "CANCELLED"]:
                    logger.error(f"RunPod job {status}: {result}")
                    raise RuntimeError(f"RunPod job {job_id} {status}")

                # 아직 대기 중 (IN_QUEUE, IN_PROGRESS 등)
                await asyncio.sleep(1)

            raise TimeoutError(f"RunPod job {job_id} timed out after polling ({max_retries}s). Status was: {status}")

        except Exception as e:
            logger.error(f"RunPod API request failed: {e}. Falling back to local model if available.")
            raise e

    def get_embedding_dim(self) -> int:
        """임베딩 차원 반환"""
        return self.model.get_sentence_embedding_dimension()


@lru_cache(maxsize=1)
def get_embedder() -> ProfileEmbedder:
    """임베더 싱글톤 (thread-safe via lru_cache)"""
    return ProfileEmbedder()
