"""의도 분류 모듈 — 사용자 메시지를 D1/D2/D3으로 분류"""

import logging

from adapters.llm_client import LLMClient, get_llm_client
from prompts import load_prompt
from schemas.agent import IntentResult

logger = logging.getLogger(__name__)


class IntentRouter:
    """LLM 기반 의도 분류기"""

    def __init__(self, llm: LLMClient | None = None):
        self.llm = llm or get_llm_client()
        self._system_prompt: str | None = None

    @property
    def system_prompt(self) -> str:
        if self._system_prompt is None:
            self._system_prompt = load_prompt("intent_router_system")
        return self._system_prompt

    async def classify(
        self,
        message: str,
        history: list[dict] | None = None,
    ) -> IntentResult:
        """
        사용자 메시지의 의도를 분류한다.

        Args:
            message: 현재 사용자 메시지
            history: 대화 이력 [{"role": "user"|"assistant", "content": "..."}]

        Returns:
            IntentResult (intent="D1"|"D2"|"D3", confidence=0.0~1.0)
        """
        # 대화 이력이 있으면 맥락 포함
        prompt_parts = []
        if history:
            prompt_parts.append("## 대화 이력")
            for msg in history[-6:]:  # 최근 6개까지만
                role = "사용자" if msg["role"] == "user" else "어시스턴트"
                prompt_parts.append(f"[{role}] {msg['content']}")
            prompt_parts.append("")

        prompt_parts.append(f"## 현재 사용자 메시지\n{message}")

        user_prompt = "\n".join(prompt_parts)

        try:
            result = await self.llm.generate_json(
                prompt=user_prompt,
                system_instruction=self.system_prompt,
                response_schema=IntentResult,
                temperature=0.1,
            )
            return IntentResult(**result)
        except Exception as e:
            logger.error(f"의도 분류 실패, D1으로 fallback: {e}")
            # fallback: 멘토 탐색으로 기본 분류
            return IntentResult(intent="D1", confidence=0.5)
