"""프로필 임베딩 생성 모듈"""

import logging
import os
from functools import lru_cache

import httpx
import numpy as np
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)


class ProfileEmbedder:
    """프로필 텍스트 임베딩 생성 (로컬 모델 or RunPod API)"""

    def __init__(self, model_name: str = "intfloat/multilingual-e5-large-instruct"):
        self.model_name = model_name
        self._model: SentenceTransformer | None = None

        # RunPod 설정
        self.use_runpod = os.getenv("USE_RUNPOD_EMBEDDING", "false").lower() == "true"
        self.runpod_api_key = os.getenv("RUNPOD_API_KEY")
        self.runpod_endpoint_id = os.getenv("RUNPOD_EMBEDDING_ENDPOINT_ID")
        self.runpod_url = (
            f"https://api.runpod.ai/v2/{self.runpod_endpoint_id}/runsync" if self.runpod_endpoint_id else None
        )

    @property
    def model(self) -> SentenceTransformer:
        """Lazy loading으로 모델 로드"""
        if self._model is None:
            logger.info(f"Loading embedding model: {self.model_name}")
            self._model = SentenceTransformer(self.model_name)
            logger.info("Embedding model loaded successfully")
        return self._model

    def embed_text(self, text: str, is_query: bool = True) -> np.ndarray:
        """단일 텍스트 임베딩 생성 (E5 prefix 처리)"""
        if self.use_runpod and self.runpod_url and self.runpod_api_key:
            try:
                return self._embed_via_runpod([text], is_query)[0]
            except Exception as e:
                logger.error(f"RunPod embedding failed, falling back to local: {e}")

        if "e5" in self.model_name.lower():
            prefix = "query" if is_query else "passage"
            text = f"{prefix}: {text}"
        return self.model.encode(text, normalize_embeddings=True)

    def embed_texts(self, texts: list[str]) -> np.ndarray:
        """여러 텍스트 임베딩 생성"""
        if self.use_runpod and self.runpod_url and self.runpod_api_key:
            try:
                return self._embed_via_runpod(texts, is_query=False)
            except Exception as e:
                logger.error(f"RunPod batch embedding failed, falling back to local: {e}")

        if "e5" in self.model_name.lower():
            texts = [f"passage: {t}" for t in texts]
        return self.model.encode(texts, normalize_embeddings=True)

    def _embed_via_runpod(self, texts: list[str], is_query: bool = True) -> np.ndarray:
        """RunPod Serverless API를 통한 임베딩 생성 (polling 방식)"""
        headers = {"Authorization": f"Bearer {self.runpod_api_key}", "Content-Type": "application/json"}
        payload = {"input": {"texts": texts, "is_query": is_query}}

        try:
            with httpx.Client(timeout=10.0) as client:
                # 1. 작업 요청 (/run)
                run_url = f"https://api.runpod.ai/v2/{self.runpod_endpoint_id}/run"
                response = client.post(run_url, headers=headers, json=payload)
                response.raise_for_status()
                job_data = response.json()
                job_id = job_data.get("id")

                if not job_id:
                    raise RuntimeError(f"Failed to get job ID from RunPod: {job_data}")

                # 2. 결과 대기 (polling)
                status_url = f"https://api.runpod.ai/v2/{self.runpod_endpoint_id}/status/{job_id}"
                import time

                max_retries = 150  # 총 150초 대기 (1s * 150)
                logger.info(f"RunPod 작업 시작됨 (ID: {job_id}). 결과를 기다리는 중...")

                for i in range(max_retries):
                    status_response = client.get(status_url, headers=headers)
                    status_response.raise_for_status()
                    result = status_response.json()

                    status = result.get("status")
                    if status == "COMPLETED":
                        return np.array(result["output"])
                    elif status in ["FAILED", "CANCELLED"]:
                        logger.error(f"RunPod job {status}: {result}")
                        raise RuntimeError(f"RunPod job {job_id} {status}")

                    # 아직 대기 중 (IN_QUEUE, IN_PROGRESS 등)
                    time.sleep(1)  # 대기 시간을 5초에서 1초로 단축 (지연 시간 절감)

                raise TimeoutError(
                    f"RunPod job {job_id} timed out after polling ({max_retries * 5}s). Status was: {status}"
                )

        except Exception as e:
            logger.error(f"RunPod API request failed: {e}")
            raise e

    def get_embedding_dim(self) -> int:
        """임베딩 차원 반환"""
        return self.model.get_sentence_embedding_dimension()


@lru_cache(maxsize=1)
def get_embedder() -> ProfileEmbedder:
    """임베더 싱글톤 (thread-safe via lru_cache)"""
    return ProfileEmbedder()
