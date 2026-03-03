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

# Fallback 모델 (rate limit 시 시도)
FALLBACK_MODELS = ["gemini-2.0-flash-lite"]


class LLMClient:
    """Wrapper for LLM API calls (Gemini) with retry and API key rotation."""

    def __init__(self, model_name: str = "gemini-2.5-flash-lite"):
        self.model_name = model_name
        self._clients: list[genai.Client] = []
        self._client_labels: list[str] = []  # 디버깅용 라벨
        self._current_client_idx = 0
        self._initialized = False
        self.max_retries = 2
        self.base_delay = 1

    def _init_clients(self) -> None:
        """클라이언트 초기화 (lazy) - 리스트 분리하여 저장"""
        if self._initialized:
            return

        self._vertex_clients: list[genai.Client] = []
        self._vertex_labels: list[str] = []
        self._api_key_clients: list[genai.Client] = []
        self._api_key_labels: list[str] = []

        # 1. API 키 클라이언트 로드
        api_keys = self._load_api_keys()
        for i, key in enumerate(api_keys):
            self._api_key_clients.append(genai.Client(api_key=key))
            self._api_key_labels.append(f"APIKey_{i + 1}({key[:8]}...)")

        # 2. Vertex AI 클라이언트 로드
        project_id = os.getenv("GCP_PROJECT_ID")
        location = os.getenv("GCP_LOCATION", "asia-northeast3")
        credentials_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")

        if project_id and credentials_path:
            self._vertex_clients.append(genai.Client(vertexai=True, project=project_id, location=location))
            self._vertex_labels.append(f"VertexAI({location})")

        if not self._api_key_clients and not self._vertex_clients:
            raise ValueError("No LLM clients configured.")

        # 기본 순서: Vertex 우선
        self._clients = self._vertex_clients + self._api_key_clients
        self._client_labels = self._vertex_labels + self._api_key_labels
        
        logger.info(f"LLM 클라이언트 초기화 완료 (Vertex {len(self._vertex_clients)}개, APIKey {len(self._api_key_clients)}개)")
        self._initialized = True

    def _load_api_keys(self) -> list[str]:
        """환경변수에서 API 키 목록 로드"""
        keys = []
        multi_keys = os.getenv("GOOGLE_API_KEYS", "")
        if multi_keys:
            keys.extend([k.strip() for k in multi_keys.split(",") if k.strip()])

        if not keys:
            primary = os.getenv("GOOGLE_API_KEY", "")
            if primary:
                keys.append(primary)
            for i in range(2, 11):
                extra = os.getenv(f"GOOGLE_API_KEY_{i}", "")
                if extra:
                    keys.append(extra)
        return keys

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 4096,
        prefer_api_key: bool = False,
    ) -> str:
        """Generate text completion."""
        self._init_clients()
        
        # 호출 전용으로 클라이언트 리스트 재구성 (정적 변수 오염 방지)
        if prefer_api_key:
            target_clients = self._api_key_clients + self._vertex_clients
            target_labels = self._api_key_labels + self._vertex_labels
        else:
            target_clients = self._vertex_clients + self._api_key_clients
            target_labels = self._vertex_labels + self._api_key_labels

        config = types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
            system_instruction=system_instruction,
        )

        for client, label in zip(target_clients, target_labels):
            try:
                response = await client.aio.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                    config=config,
                )
                return response.text
            except Exception as e:
                logger.warning(f"⚠️ {label} 호출 실패: {e}")
                continue
                
        raise RuntimeError("모든 클라이언트 호출에 실패했습니다.")

    async def generate_json(
        self,
        prompt: str,
        system_instruction: str | None = None,
        response_schema: type[BaseModel] | None = None,
        temperature: float = 0.1,
        prefer_api_key: bool = False,
    ) -> dict[str, Any]:
        """Generate structured JSON output with conditional priority."""
        self._init_clients()

        if prefer_api_key:
            target_clients = self._api_key_clients + self._vertex_clients
            target_labels = self._api_key_labels + self._vertex_labels
        else:
            target_clients = self._vertex_clients + self._api_key_clients
            target_labels = self._vertex_labels + self._api_key_labels

        config = types.GenerateContentConfig(
            temperature=temperature,
            response_mime_type="application/json",
            system_instruction=system_instruction,
        )
        if response_schema:
            config.response_schema = response_schema

        models_to_try = [self.model_name] + [m for m in FALLBACK_MODELS if m != self.model_name]
        last_error = None

        for client, label in zip(target_clients, target_labels):
            for model in models_to_try:
                for attempt in range(self.max_retries):
                    try:
                        response = await client.aio.models.generate_content(
                            model=model,
                            contents=prompt,
                            config=config,
                        )
                        text = response.text.strip()
                        if text.startswith("```"):
                            lines = text.split("\n")
                            if lines[0].startswith("```"): lines = lines[1:]
                            if lines and lines[-1].strip() == "```": lines = lines[:-1]
                            text = "\n".join(lines)
                        return json.loads(text)
                    except Exception as e:
                        last_error = e
                        error_str = str(e).upper()
                        if any(code in error_str for code in ["429", "RESOURCE_EXHAUSTED", "503", "OVERLOADED"]):
                            logger.warning(f"⚠️ 할당량 초과 ({label}, {model}, 시도 {attempt + 1}/{self.max_retries})")
                            if attempt == self.max_retries - 1: break
                            await asyncio.sleep(self.base_delay * (2**attempt))
                            continue
                        logger.warning(f"⚠️ {model} 호출 실패 ({label}): {e}")
                        break
                else: continue
                break
            else: continue
            # If we got here via 'break' inside retry/model loop without returning, it means we need next client
        
        raise last_error or RuntimeError("모든 API 키 및 모델 호출에 실패했습니다.")

    async def generate_json_with_images(
        self,
        contents: list[types.Part],
        system_instruction: str | None = None,
        response_schema: type[BaseModel] | None = None,
        temperature: float = 0.1,
        prefer_api_key: bool = False,
    ) -> dict[str, Any]:
        """Generate structured JSON output from images with conditional priority."""
        self._init_clients()

        if prefer_api_key:
            target_clients = self._api_key_clients + self._vertex_clients
            target_labels = self._api_key_labels + self._vertex_labels
        else:
            target_clients = self._vertex_clients + self._api_key_clients
            target_labels = self._vertex_labels + self._api_key_labels

        config = types.GenerateContentConfig(
            temperature=temperature,
            response_mime_type="application/json",
            system_instruction=system_instruction,
        )
        if response_schema:
            config.response_schema = response_schema

        models_to_try = [self.model_name] + [m for m in FALLBACK_MODELS if m != self.model_name]
        last_error = None

        for client, label in zip(target_clients, target_labels):
            for model in models_to_try:
                for attempt in range(self.max_retries):
                    try:
                        response = await client.aio.models.generate_content(
                            model=model,
                            contents=contents,
                            config=config,
                        )
                        text = response.text.strip()
                        if text.startswith("```"):
                            lines = text.split("\n")
                            if lines[0].startswith("```"): lines = lines[1:]
                            if lines and lines[-1].strip() == "```": lines = lines[:-1]
                            text = "\n".join(lines)
                        return json.loads(text)
                    except Exception as e:
                        last_error = e
                        error_str = str(e).upper()
                        if any(code in error_str for code in ["429", "RESOURCE_EXHAUSTED", "503", "OVERLOADED"]):
                            logger.warning(f"⚠️ 할당량 초과 ({label}, {model}, 시도 {attempt + 1}/{self.max_retries})")
                            if attempt == self.max_retries - 1: break
                            await asyncio.sleep(self.base_delay * (2**attempt))
                            continue
                        logger.warning(f"⚠️ {model} 호출 실패 ({label}): {e}")
                        break
                else: continue
                break
            else: continue
        
        raise last_error or RuntimeError("모든 API 키 및 모델 호출에 실패했습니다.")


# 싱글톤
_llm_client: LLMClient | None = None


def get_llm_client() -> LLMClient:
    """Get or create LLM client singleton."""
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient()
    return _llm_client
