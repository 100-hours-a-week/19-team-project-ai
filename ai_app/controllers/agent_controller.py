"""Agent 컨트롤러 — LangGraph 기반 SSE 스트리밍 조율"""

import json
import logging
import os

from middleware.otel_lgtm_metrics import tracked_db_connection
from schemas.agent import AgentReplyRequest
from services.agent.graph import get_agent_graph
from services.agent.session import get_session_store

logger = logging.getLogger(__name__)


class AgentController:
    """Agent HTTP 레이어 조율자 (LangGraph 기반)"""

    def __init__(self, database_url: str | None = None):
        self.database_url = database_url or os.getenv(
            "DATABASE_URL",
            "postgresql://postgres:postgres@localhost:5432/devmentor",
        )
        self._engine = None

    @property
    def engine(self):
        if self._engine is None:
            from sqlalchemy import create_engine

            self._engine = create_engine(self.database_url)
        return self._engine

    def get_connection(self):
        return tracked_db_connection(self.engine)

    # ============== 세션 관리 ==============

    async def create_session(self) -> dict:
        """새 세션 생성"""
        store = get_session_store()
        session = store.create()
        return session.to_dict()

    async def list_sessions(self) -> list[dict]:
        """세션 목록 조회"""
        store = get_session_store()
        return store.list_sessions()

    async def get_session(self, session_id: str) -> dict | None:
        """세션 조회"""
        store = get_session_store()
        session = store.get(session_id)
        return session.to_dict() if session else None

    # ============== LangGraph 기반 스트리밍 ==============

    async def stream_reply(
        self,
        request: AgentReplyRequest,
    ):
        """
        Agent 답변 SSE 스트리밍 (LangGraph 기반)

        1. 세션 가져오기/생성
        2. LangGraph 실행 (의도분류 → D1/D2/D3 분기)
        3. 그래프 결과의 events를 SSE로 스트리밍

        Yields:
            SSE 형식 문자열 ("event: ...\ndata: ...\n\n")
        """
        store = get_session_store()
        session = store.get_or_create(request.session_id)

        # 세션에 사용자 메시지 추가
        session.add_user_message(request.message)

        # 세션 ID 전송
        yield _sse_format("session", {"session_id": session.session_id})

        # LangGraph 실행 (DB 연결 불필요)
        graph = get_agent_graph()

        with self.get_connection() as conn:
            result = await graph.ainvoke(
                {
                    "message": request.message,
                    "history": session.get_history(),
                    "top_k": request.top_k,
                    "conn": conn,
                    "events": [],
                }
            )

        # 의도 저장
        if result.get("intent_result"):
            session.last_intent = result["intent_result"].intent

        # SSE 이벤트 스트리밍
        reply_text = ""
        for event in result.get("events", []):
            yield _sse_format(event["event"], event["data"])

            # reply_text 누적 (세션 이력용)
            if event["event"] == "text":
                reply_text += event["data"].get("chunk", "")

        # 세션에 어시스턴트 응답 추가
        if reply_text:
            session.add_assistant_message(reply_text.strip())


def _sse_format(event: str, data: dict) -> str:
    """SSE 포맷 문자열 생성"""
    json_data = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {json_data}\n\n"


# 싱글톤
_controller: AgentController | None = None


def get_agent_controller() -> AgentController:
    """컨트롤러 싱글톤"""
    global _controller
    if _controller is None:
        _controller = AgentController()
    return _controller
