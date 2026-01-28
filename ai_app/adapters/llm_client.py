"""LLM Client adapter for Gemini and other models."""

import json
import os
from typing import Any

from google import genai
from google.genai import types
from pydantic import BaseModel


class LLMClient:
    """Wrapper for LLM API calls (Gemini)."""

    def __init__(self, model_name: str = "gemini-2.0-flash"):
        self.model_name = model_name
        self._client: genai.Client | None = None

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
        """Generate structured JSON output."""
        client = self._get_client()

        config = types.GenerateContentConfig(
            temperature=temperature,
            response_mime_type="application/json",
            system_instruction=system_instruction,
        )

        if response_schema:
            config.response_schema = response_schema

        response = await client.aio.models.generate_content(
            model=self.model_name,
            contents=prompt,
            config=config,
        )

        # 마크다운 코드 블록 제거 (```json ... ``` 또는 ``` ... ```)
        text = response.text.strip()
        if text.startswith("```"):
            # 첫 번째 줄 제거 (```json 또는 ```)
            lines = text.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            # 마지막 ``` 제거
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines)

        return json.loads(text)


# Singleton instance
_llm_client: LLMClient | None = None


def get_llm_client() -> LLMClient:
    """Get or create LLM client singleton."""
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient()
    return _llm_client
