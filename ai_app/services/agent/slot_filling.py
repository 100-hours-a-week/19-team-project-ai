"""조건 추출 모듈 (Slot Filling) — 사용자 메시지에서 멘토 탐색 조건 추출"""

import logging

from adapters.llm_client import LLMClient, get_llm_client
from prompts import load_prompt
from schemas.agent import MentorConditions

logger = logging.getLogger(__name__)


class SlotFiller:
    """LLM 기반 조건 추출기"""

    def __init__(self, llm: LLMClient | None = None):
        self.llm = llm or get_llm_client()
        self._system_prompt: str | None = None

    @property
    def system_prompt(self) -> str:
        if self._system_prompt is None:
            self._system_prompt = load_prompt("slot_filling_system")
        return self._system_prompt

    async def extract(self, message: str) -> MentorConditions:
        """
        사용자 메시지에서 멘토 탐색 조건을 추출한다.

        Args:
            message: 사용자 메시지

        Returns:
            MentorConditions (추출된 조건 구조)
        """
        try:
            result = await self.llm.generate_json(
                prompt=f"사용자 메시지: {message}",
                system_instruction=self.system_prompt,
                response_schema=MentorConditions,
                temperature=0.1,
            )

            conditions = MentorConditions(**result)
            logger.info(
                f"조건 추출 완료: job={conditions.job}, exp={conditions.experience_years}, "
                f"skills={conditions.skills}, domain={conditions.domain}"
            )
            return conditions

        except Exception as e:
            logger.error(f"조건 추출 실패: {e}")
            # fallback: 메시지 전체를 키워드로
            return MentorConditions(keywords=[message])
