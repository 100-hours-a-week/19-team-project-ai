"""프로필 임베딩 생성 모듈"""

import logging

import numpy as np
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)


class ProfileEmbedder:
    """프로필 텍스트 임베딩 생성"""

    _instance: "ProfileEmbedder | None" = None

    def __init__(self, model_name: str = "intfloat/multilingual-e5-large-instruct"):
        self.model_name = model_name
        self._model: SentenceTransformer | None = None

    @property
    def model(self) -> SentenceTransformer:
        """Lazy loading으로 모델 로드"""
        if self._model is None:
            logger.info(f"Loading embedding model: {self.model_name}")
            self._model = SentenceTransformer(self.model_name)
            logger.info("Embedding model loaded successfully")
        return self._model

    def embed_text(self, text: str) -> np.ndarray:
        """단일 텍스트 임베딩 생성"""
        if "e5" in self.model_name.lower():
            text = f"query: {text}"
        return self.model.encode(text, normalize_embeddings=True)

    def embed_texts(self, texts: list[str]) -> np.ndarray:
        """여러 텍스트 임베딩 생성"""
        if "e5" in self.model_name.lower():
            texts = [f"passage: {t}" for t in texts]
        return self.model.encode(texts, normalize_embeddings=True)

    def get_embedding_dim(self) -> int:
        """임베딩 차원 반환"""
        return self.model.get_sentence_embedding_dimension()


# 싱글톤
def get_embedder() -> ProfileEmbedder:
    """임베더 싱글톤"""
    if ProfileEmbedder._instance is None:
        ProfileEmbedder._instance = ProfileEmbedder()
    return ProfileEmbedder._instance
