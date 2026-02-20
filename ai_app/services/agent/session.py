"""세션 관리 모듈 — 인메모리 세션 스토어 (추후 Redis 전환 가능)"""

import logging
import uuid
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class Session:
    """Agent 대화 세션"""

    def __init__(self, session_id: str | None = None):
        self.session_id = session_id or str(uuid.uuid4())
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.messages: list[dict] = []  # [{"role": "user"|"assistant", "content": "..."}]
        self.last_intent: str | None = None

    def add_user_message(self, message: str) -> None:
        self.messages.append({"role": "user", "content": message})

    def add_assistant_message(self, message: str) -> None:
        self.messages.append({"role": "assistant", "content": message})

    def get_history(self) -> list[dict]:
        """대화 이력 반환 (최근 20개까지)"""
        return self.messages[-20:]

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "created_at": self.created_at,
            "message_count": len(self.messages),
            "last_intent": self.last_intent,
        }


class SessionStore:
    """인메모리 세션 저장소 (추후 Redis 전환 가능)"""

    def __init__(self, max_sessions: int = 1000):
        self._sessions: dict[str, Session] = {}
        self._max_sessions = max_sessions

    def create(self) -> Session:
        """새 세션 생성"""
        # 최대 세션 수 초과 시 가장 오래된 세션 제거
        if len(self._sessions) >= self._max_sessions:
            oldest_key = next(iter(self._sessions))
            del self._sessions[oldest_key]
            logger.warning(f"세션 한도 초과. 가장 오래된 세션 {oldest_key} 제거")

        session = Session()
        self._sessions[session.session_id] = session
        logger.info(f"새 세션 생성: {session.session_id}")
        return session

    def get(self, session_id: str) -> Session | None:
        """세션 조회"""
        return self._sessions.get(session_id)

    def get_or_create(self, session_id: str | None) -> Session:
        """세션 조회 또는 생성"""
        if session_id:
            session = self.get(session_id)
            if session:
                return session
            logger.warning(f"세션 {session_id}을 찾을 수 없어 새 세션 생성")

        return self.create()

    def list_sessions(self) -> list[dict]:
        """모든 세션 목록"""
        return [s.to_dict() for s in self._sessions.values()]

    def delete(self, session_id: str) -> bool:
        """세션 삭제"""
        if session_id in self._sessions:
            del self._sessions[session_id]
            return True
        return False


# 싱글톤
_session_store: SessionStore | None = None


def get_session_store() -> SessionStore:
    """세션 스토어 싱글톤"""
    global _session_store
    if _session_store is None:
        _session_store = SessionStore()
    return _session_store
