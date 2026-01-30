"""LLM Client adapter for Gemini and other models."""

import asyncio
import json
import logging
import os
from typing import Any

from google import genai
from google.genai import types
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Fallback 모델 순서 (rate limit 시 순차 시도)
FALLBACK_MODELS = [
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",  # 더 가벼운 모델
]


class LLMClient:
    """Wrapper for LLM API calls (Gemini) with retry and fallback."""

    def __init__(self, model_name: str = "gemini-2.0-flash"):
        self.model_name = model_name
        self._client: genai.Client | None = None
        self.max_retries = 3
        self.base_delay = 2  # 초

    def _get_client(self) -> genai.Client:
        """Get or create the Gemini client (lazy initialization)."""
        if self._client is None:
            api_key = os.getenv("GOOGLE_API_KEY")
            if not api_key:
                raise ValueError("GOOGLE_API_KEY environment variable is not set")
            self._client = genai.Client(api_key=api_key)
        return self._client

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 4096,
    ) -> str:
        """Generate text completion."""
        client = self._get_client()

        config = types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
            system_instruction=system_instruction,
        )

        response = await client.aio.models.generate_content(
            model=self.model_name,
            contents=prompt,
            config=config,
        )

        return response.text

    async def generate_json(
        self,
        prompt: str,
        system_instruction: str | None = None,
        response_schema: type[BaseModel] | None = None,
        temperature: float = 0.1,
    ) -> dict[str, Any]:
        """Generate structured JSON output with retry and fallback."""
        client = self._get_client()

        config = types.GenerateContentConfig(
            temperature=temperature,
            response_mime_type="application/json",
            system_instruction=system_instruction,
        )

        if response_schema:
            config.response_schema = response_schema

        # 현재 모델부터 시작하는 fallback 리스트 생성
        models_to_try = [self.model_name]
        for model in FALLBACK_MODELS:
            if model not in models_to_try:
                models_to_try.append(model)

        last_error = None

        for model in models_to_try:
            for attempt in range(self.max_retries):
                try:
                    response = await client.aio.models.generate_content(
                        model=model,
                        contents=prompt,
                        config=config,
                    )

                    # 성공 시 모델 이름 로깅
                    if model != self.model_name:
                        logger.info(f"Fallback 모델 사용 성공: {model}")

                    # 마크다운 코드 블록 제거
                    text = response.text.strip()
                    if text.startswith("```"):
                        lines = text.split("\n")
                        if lines[0].startswith("```"):
                            lines = lines[1:]
                        if lines and lines[-1].strip() == "```":
                            lines = lines[:-1]
                        text = "\n".join(lines)

                    return json.loads(text)

                except Exception as e:
                    last_error = e
                    error_str = str(e)

                    # 429 Rate Limit 에러인 경우
                    if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                        delay = self.base_delay * (2 ** attempt)
                        logger.warning(
                            f"Rate limit ({model}, 시도 {attempt + 1}/{self.max_retries}). "
                            f"{delay}초 후 재시도..."
                        )
                        await asyncio.sleep(delay)
                        continue

                    # 다른 에러는 바로 다음 모델로
                    logger.warning(f"모델 {model} 에러: {e}")
                    break

            # 현재 모델 실패, 다음 fallback 모델 시도
            if model != models_to_try[-1]:
                logger.info(f"모델 {model} 실패, 다음 fallback 모델 시도...")

        # 모든 모델/재시도 실패
        raise last_error or RuntimeError("모든 LLM 호출 시도 실패")


# Singleton instance
_llm_client: LLMClient | None = None


def get_llm_client() -> LLMClient:
    """Get or create LLM client singleton."""
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient()
    return _llm_client
