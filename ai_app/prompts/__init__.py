"""프롬프트 로더 - 외부 .md 파일에서 프롬프트 로드"""

from functools import lru_cache
from pathlib import Path

PROMPTS_DIR = Path(__file__).parent


@lru_cache(maxsize=32)
def load_prompt(name: str) -> str:
    """
    프롬프트 파일 로드 (캐싱됨)

    Args:
        name: 프롬프트 파일명 (확장자 제외)
              예: "resume_extraction_system"

    Returns:
        프롬프트 내용

    Raises:
        FileNotFoundError: 파일이 없을 경우
    """
    file_path = PROMPTS_DIR / f"{name}.md"
    if not file_path.exists():
        raise FileNotFoundError(f"Prompt file not found: {file_path}")
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


def clear_prompt_cache():
    """프롬프트 캐시 초기화 (개발/테스트용)"""
    load_prompt.cache_clear()
