"""LLM Client adapter for Gemini and other models."""

import json
import os
from typing import Any

import google.generativeai as genai
from pydantic import BaseModel


class LLMClient:
    """Wrapper for LLM API calls (Gemini)."""

    def __init__(self, model_name: str = "gemini-2.0-flash"):
        self.model_name = model_name
        self._model = None
        self._configured = False

    def _configure(self) -> None:
        """Configure the Gemini API (lazy initialization)."""
        if self._configured:
            return
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("GOOGLE_API_KEY environment variable is not set")
        genai.configure(api_key=api_key)
        self._model = genai.GenerativeModel(self.model_name)
        self._configured = True

    @property
    def model(self):
        """Get model with lazy initialization."""
        self._configure()
        return self._model

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 4096,
    ) -> str:
        """Generate text completion."""
        generation_config = genai.GenerationConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
        )

        if system_instruction:
            model = genai.GenerativeModel(
                self.model_name,
                system_instruction=system_instruction,
            )
        else:
            model = self.model

        response = await model.generate_content_async(
            prompt,
            generation_config=generation_config,
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
        generation_config = genai.GenerationConfig(
            temperature=temperature,
            response_mime_type="application/json",
        )

        if response_schema:
            generation_config.response_schema = response_schema

        if system_instruction:
            model = genai.GenerativeModel(
                self.model_name,
                system_instruction=system_instruction,
            )
        else:
            model = self.model

        response = await model.generate_content_async(
            prompt,
            generation_config=generation_config,
        )

        return json.loads(response.text)


# Singleton instance
_llm_client: LLMClient | None = None


def get_llm_client() -> LLMClient:
    """Get or create LLM client singleton."""
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient()
    return _llm_client
