import logging
import os
from functools import lru_cache
from typing import Optional

import httpx
import numpy as np
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

# 전역 HTTP 클라이언트 (커넥션 풀 공유)
_async_client: Optional[httpx.AsyncClient] = None


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
        # 메모리 캐시 (LRU)
        self._cache = {}

    @property
    def model(self) -> SentenceTransformer:
        """Lazy loading으로 모델 로드"""
        if self._model is None:
            logger.info(f"Loading embedding model: {self.model_name}")
            self._model = SentenceTransformer(self.model_name)
            logger.info("Embedding model loaded successfully")
        return self._model

    async def embed_text(self, text: str, is_query: bool = True) -> np.ndarray:
        """단일 텍스트 임베딩 생성 (캐싱 지원)"""
        cache_key = (text, is_query)
        if cache_key in self._cache:
            return self._cache[cache_key]

        if self.use_runpod and self.runpod_url and self.runpod_api_key:
            try:
                embedding = (await self._embed_via_runpod([text], is_query))[0]
                self._cache[cache_key] = embedding
                return embedding
            except Exception as e:
                logger.error(f"RunPod embedding failed, falling back to local: {e}")

        if "e5" in self.model_name.lower():
            prefix = "query" if is_query else "passage"
            text = f"{prefix}: {text}"

        # 로설 모델 연산도 CPU를 많이 쓰므로 비동기 이벤트 루프 배려 필요 (Thread 사용 권장되나 여기선 캐시로 해결)
        embedding = self.model.encode(text, normalize_embeddings=True)
        self._cache[cache_key] = embedding
        return embedding

    async def embed_texts(self, texts: list[str]) -> np.ndarray:
        """여러 텍스트 임베딩 생성"""
        if self.use_runpod and self.runpod_url and self.runpod_api_key:
            try:
                return await self._embed_via_runpod(texts, is_query=False)
            except Exception as e:
                logger.error(f"RunPod batch embedding failed, falling back to local: {e}")

        if "e5" in self.model_name.lower():
            texts = [f"passage: {t}" for t in texts]
        return self.model.encode(texts, normalize_embeddings=True)

    async def _embed_via_runpod(self, texts: list[str], is_query: bool = True) -> np.ndarray:
        """RunPod Serverless API를 통한 실시간 임베딩 생성 (Async)"""
        if not self.runpod_url or not self.runpod_api_key:
            raise RuntimeError("RunPod configuration missing (URL or API Key)")

        import time

        headers = {"Authorization": f"Bearer {self.runpod_api_key}", "Content-Type": "application/json"}
        payload = {"input": {"texts": texts, "is_query": is_query}}

        start_time = time.time()
        try:
            client = await get_async_client()
            response = await client.post(self.runpod_url, headers=headers, json=payload)
            response.raise_for_status()
            result = response.json()

            elapsed = time.time() - start_time
            status = result.get("status")

            if status == "COMPLETED":
                logger.info(f"RunPod API success: {len(texts)} texts, took {elapsed:.2f}s")
                return np.array(result["output"])
            elif status in ["FAILED", "CANCELLED"]:
                logger.error(f"RunPod job {status} after {elapsed:.2f}s: {result}")
                raise RuntimeError(f"RunPod job {status}")
            else:
                logger.warning(f"RunPod unexpected status {status} after {elapsed:.2f}s")
                raise RuntimeError(f"RunPod returned unexpected status: {status}")

        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"RunPod API request failed after {elapsed:.2f}s: {e}")
            raise e

    def get_embedding_dim(self) -> int:
        """임베딩 차원 반환"""
        return self.model.get_sentence_embedding_dimension()


@lru_cache(maxsize=1)
def get_embedder() -> ProfileEmbedder:
    """임베더 싱글톤 (thread-safe via lru_cache)"""
    return ProfileEmbedder()
