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
        """클라이언트 초기화 (lazy) - 여러 API 키 지원"""
        if self._initialized:
            return

        # 1. Vertex AI 클라이언트 (최우선)
        project_id = os.getenv("GCP_PROJECT_ID")
        location = os.getenv("GCP_LOCATION", "asia-northeast3")
        credentials_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")

        if project_id and credentials_path:
            logger.info(f"Using Vertex AI (Project: {project_id}, Location: {location})")
            self._clients.append(genai.Client(vertexai=True, project=project_id, location=location))
            self._client_labels.append(f"VertexAI({location})")

        # 2. 여러 API 키 클라이언트 (GOOGLE_API_KEY, GOOGLE_API_KEY_2, ...)
        api_keys = self._load_api_keys()
        for i, key in enumerate(api_keys):
            self._clients.append(genai.Client(api_key=key))
            label = f"APIKey_{i + 1}({key[:8]}...)"
            self._client_labels.append(label)

        if not self._clients:
            raise ValueError(
                "No LLM client configured. Set GCP_PROJECT_ID/GOOGLE_APPLICATION_CREDENTIALS "
                "or GOOGLE_API_KEY / GOOGLE_API_KEYS."
            )

        logger.info(f"LLM 클라이언트 {len(self._clients)}개 초기화: {self._client_labels}")
        self._initialized = True

    def _load_api_keys(self) -> list[str]:
        """환경변수에서 API 키 목록 로드"""
        keys = []

        # 방법 1: 콤마 구분 (GOOGLE_API_KEYS)
        multi_keys = os.getenv("GOOGLE_API_KEYS", "")
        if multi_keys:
            keys.extend([k.strip() for k in multi_keys.split(",") if k.strip()])

        # 방법 2: 개별 환경변수 (GOOGLE_API_KEY, GOOGLE_API_KEY_2, ...)
        if not keys:
            primary = os.getenv("GOOGLE_API_KEY", "")
            if primary:
                keys.append(primary)
            # _2, _3, ... 순서로 탐색
            for i in range(2, 11):
                extra = os.getenv(f"GOOGLE_API_KEY_{i}", "")
                if extra:
                    keys.append(extra)

        return keys

    def _get_client(self) -> genai.Client:
        """현재 active 클라이언트 반환"""
        self._init_clients()
        return self._clients[self._current_client_idx]

    def _rotate_client(self) -> bool:
        """다음 클라이언트로 전환. 다음이 있으면 True, 없으면 False."""
        self._init_clients()
        next_idx = self._current_client_idx + 1
        if next_idx < len(self._clients):
            old_label = self._client_labels[self._current_client_idx]
            self._current_client_idx = next_idx
            new_label = self._client_labels[self._current_client_idx]
            logger.info(f"🔄 API 키 전환: {old_label} → {new_label}")
            return True
        # 모두 소진 → 처음으로 리셋
        self._current_client_idx = 0
        return False

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
        """Generate structured JSON output with retry, key rotation, and model fallback."""
        self._init_clients()

        config = types.GenerateContentConfig(
            temperature=temperature,
            response_mime_type="application/json",
            system_instruction=system_instruction,
        )

        if response_schema:
            config.response_schema = response_schema

        # 현재 모델 + fallback 모델 리스트
        models_to_try = [self.model_name] + [m for m in FALLBACK_MODELS if m != self.model_name]
        last_error = None

        # 모든 클라이언트(API 키)를 시도
        clients_tried = 0
        total_clients = len(self._clients)

        while clients_tried < total_clients:
            client = self._clients[self._current_client_idx]
            client_label = self._client_labels[self._current_client_idx]

            for model in models_to_try:
                for attempt in range(self.max_retries):
                    try:
                        response = await client.aio.models.generate_content(
                            model=model,
                            contents=prompt,
                            config=config,
                        )

                        if model != self.model_name:
                            logger.info(f"✅ Fallback 모델 사용 성공: {model} ({client_label})")

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

                        # 429(할당량 초과) 또는 503(서버 과부하) → 다음 API 키로 전환
                        if any(code in error_str for code in ["429", "RESOURCE_EXHAUSTED", "503", "OVERLOADED"]):
                            logger.warning(
                                f"⚠️ 할당량 초과 ({client_label}, {model}, 시도 {attempt + 1}/{self.max_retries})"
                            )

                            # 마지막 retry면 다음 API 키로 전환
                            if attempt == self.max_retries - 1:
                                break  # model loop 밖으로 → client rotation

                            wait_time = self.base_delay * (2**attempt)
                            logger.info(f"⏳ {wait_time}초 후 재시도...")
                            await asyncio.sleep(wait_time)
                            continue

                        # 그 외 에러는 다음 모델로
                        logger.warning(f"⚠️ {model} 호출 실패 ({client_label}): {e}")
                        break

                else:
                    # 모든 retry 성공 없이 끝남 → 다음 모델 시도
                    continue
                # 429로 인해 break 된 경우 → 다음 클라이언트로
                break
            else:
                # 모든 모델 시도 실패 → 다음 클라이언트
                pass

            # 다음 API 키로 전환
            has_next = self._rotate_client()
            clients_tried += 1

            if has_next and clients_tried < total_clients:
                logger.info(f"🔄 다음 API 키로 전환 ({self._client_labels[self._current_client_idx]})")
            else:
                break

        raise last_error or RuntimeError("모든 API 키 및 모델 호출에 실패했습니다.")

    async def generate_json_with_images(
        self,
        contents: list[types.Part],
        system_instruction: str | None = None,
        response_schema: type[BaseModel] | None = None,
        temperature: float = 0.1,
    ) -> dict[str, Any]:
        """Generate structured JSON output from image+text parts with retry, key rotation, and model fallback."""
        self._init_clients()

        config = types.GenerateContentConfig(
            temperature=temperature,
            response_mime_type="application/json",
            system_instruction=system_instruction,
        )

        if response_schema:
            config.response_schema = response_schema

        models_to_try = [self.model_name] + [m for m in FALLBACK_MODELS if m != self.model_name]
        last_error = None

        clients_tried = 0
        total_clients = len(self._clients)

        while clients_tried < total_clients:
            client = self._clients[self._current_client_idx]
            client_label = self._client_labels[self._current_client_idx]

            for model in models_to_try:
                for attempt in range(self.max_retries):
                    try:
                        response = await client.aio.models.generate_content(
                            model=model,
                            contents=contents,
                            config=config,
                        )

                        if model != self.model_name:
                            logger.info(f"✅ Fallback 모델 사용 성공: {model} ({client_label})")

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
                        error_str = str(e).upper()

                        if any(code in error_str for code in ["429", "RESOURCE_EXHAUSTED", "503", "OVERLOADED"]):
                            logger.warning(
                                f"⚠️ 할당량 초과 ({client_label}, {model}, 시도 {attempt + 1}/{self.max_retries})"
                            )

                            if attempt == self.max_retries - 1:
                                break

                            wait_time = self.base_delay * (2**attempt)
                            logger.info(f"⏳ {wait_time}초 후 재시도...")
                            await asyncio.sleep(wait_time)
                            continue

                        logger.warning(f"⚠️ {model} 호출 실패 ({client_label}): {e}")
                        break

                else:
                    continue
                break
            else:
                pass

            has_next = self._rotate_client()
            clients_tried += 1

            if has_next and clients_tried < total_clients:
                logger.info(f"🔄 다음 API 키로 전환 ({self._client_labels[self._current_client_idx]})")
            else:
                break

        raise last_error or RuntimeError("모든 API 키 및 모델 호출에 실패했습니다.")


# 싱글톤
_llm_client: LLMClient | None = None


def get_llm_client() -> LLMClient:
    """Get or create LLM client singleton."""
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient()
    return _llm_client
