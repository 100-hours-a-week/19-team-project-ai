"""프롬프트 로더 - 외부 .md 파일에서 프롬프트 로드"""

import logging
import os
from functools import lru_cache
from pathlib import Path

from langfuse import Langfuse

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).parent

# Langfuse 클라이언트 초기화 (환경 변수 기반)
langfuse = Langfuse(
    public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
    secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
    host=os.getenv("LANGFUSE_HOST", "https://us.cloud.langfuse.com"),
)


@lru_cache(maxsize=32)
def load_prompt(name: str) -> str:
    """
    프롬프트 파일 로드 (캐싱됨)
    Langfuse에서 먼저 시도하고, 실패 시 로컬 .md 파일에서 로드(Fallback).

    Args:
        name: 프롬프트 파일명 (확장자 제외)
              예: "resume_extraction_system"

    Returns:
        프롬프트 내용
    """
    # 1. Langfuse에서 로드 시도
    try:
        # fetch_load=True를 사용하여 최신 버전을 명시적으로 가져옴
        prompt = langfuse.get_prompt(name, type="chat" if "_system" in name or "_user" in name else "text")
        if prompt:
            logger.info(f"✅ Loaded prompt '{name}' from Langfuse (v{prompt.version})")
            # Langchain prompt template 포맷인 경우 .prompt를 사용하거나, 일반 텍스트인 경우 처리
            # 여기서는 기본적으로 문자열 반환을 위해 compile() 후 content 추출 또는 raw content 사용
            if hasattr(prompt, "get_langchain_prompt"):
                # If the app treats the compiled output as a string, attempt compile
                compiled = prompt.compile()
                if isinstance(compiled, list):
                    return "\n\n".join(
                        [msg.get("content", "") if isinstance(msg, dict) else str(msg) for msg in compiled]
                    )
                return str(compiled)

            if isinstance(prompt.prompt, list):
                return "\n\n".join(
                    [msg.get("content", "") if isinstance(msg, dict) else str(msg) for msg in prompt.prompt]
                )
            return prompt.prompt
    except Exception as e:
        logger.warning(f"⚠️ Failed to load prompt '{name}' from Langfuse, falling back to local: {e}")

    # 2. 로컬 Fallback
    file_path = PROMPTS_DIR / f"{name}.md"
    if not file_path.exists():
        logger.error(f"❌ Prompt file not found: {file_path}")
        raise FileNotFoundError(f"Prompt file not found: {file_path}")

    logger.info(f"📁 Loaded prompt '{name}' from local file")
    return file_path.read_text(encoding="utf-8")


def get_resume_extraction_prompts() -> tuple[str, str]:
    """
    이력서 추출용 프롬프트 로드

    Returns:
        (system_prompt, user_prompt_template) 튜플
    """
    system_prompt = load_prompt("resume_extraction_system")
    user_prompt = load_prompt("resume_extraction_user")
    return system_prompt, user_prompt


def get_vlm_ocr_pii_prompts() -> tuple[str, str]:
    """
    VLM OCR + PII 탐지용 프롬프트 로드

    Returns:
        (system_prompt, user_prompt) 튜플
    """
    system_prompt = load_prompt("vlm_ocr_pii_system")
    user_prompt = load_prompt("vlm_ocr_pii_user")
    return system_prompt, user_prompt


def clear_prompt_cache():
    """프롬프트 캐시 초기화 (개발/테스트용)"""
    load_prompt.cache_clear()
