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


class LLMClient:
    """Wrapper for LLM API calls (Gemini) with retry."""

    def __init__(self, model_name: str = "gemini-3.0-flash-lite"):
        self.model_name = model_name
        self._client: genai.Client | None = None
        self.max_retries = 2  # 빠른 실패를 위해 축소 (5 → 2)
        self.base_delay = 1  # 대기 시간 축소 (3 → 1초)

    def _get_client(self) -> genai.Client:
        """Get or create the Gemini client (lazy initialization)."""
        if self._client is None:
            # Vertex AI 설정 확인
            project_id = os.getenv("GCP_PROJECT_ID")
            location = os.getenv("GCP_LOCATION", "asia-northeast3")
            credentials_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")

            if project_id and credentials_path:
                logger.info(f"Using Vertex AI (Project: {project_id}, Location: {location})")
                self._client = genai.Client(
                    vertexai=True,
                    project=project_id,
                    location=location,
                )
            else:
                # 기존 API 키 방식
                api_key = os.getenv("GOOGLE_API_KEY")
                if not api_key:
                    raise ValueError(
                        "Neither Vertex AI (GCP_PROJECT_ID/GOOGLE_APPLICATION_CREDENTIALS) "
                        "nor Gemini API Key (GOOGLE_API_KEY) is set."
                    )
                logger.info("Using Gemini API Key")
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
        """Generate structured JSON output with retry."""
        client = self._get_client()

        config = types.GenerateContentConfig(
            temperature=temperature,
            response_mime_type="application/json",
            system_instruction=system_instruction,
        )

        if response_schema:
            config.response_schema = response_schema

        last_error = None

        for attempt in range(self.max_retries):
            try:
                response = await client.aio.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                    config=config,
                )

                text = response.text.strip()
                # 마크다운 코드 블록 제거 로직
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
                error_str = str(e).upper()

                # 429(할당량 초과) 또는 503(서버 과부하) 에러 처리
                if any(code in error_str for code in ["429", "RESOURCE_EXHAUSTED", "503", "OVERLOADED"]):
                    wait_time = self.base_delay * (2**attempt)
                    logger.warning(
                        f"⚠️ 할당량 초과 또는 서버 과부하 (시도 {attempt + 1}/{self.max_retries}). "
                        f"{wait_time}초 후 다시 시도합니다... 에러 메시지: {e}"
                    )
                    await asyncio.sleep(wait_time)
                    continue

                # 그 외의 에러는 즉시 실패
                logger.error(f"❌ LLM 호출 중 에러 발생: {e}")
                raise

        raise last_error or RuntimeError("LLM 호출 재시도에 실패했습니다.")


# Singleton instance
_llm_client: LLMClient | None = None


def get_llm_client() -> LLMClient:
    """Get or create LLM client singleton."""
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient()
    return _llm_client
