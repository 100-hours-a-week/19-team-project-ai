"""Agent 컨트롤러 — D1 멘토 탐색 SSE 스트리밍 조율"""

import json
import logging
import os
from collections.abc import AsyncGenerator

from schemas.agent import AgentReplyRequest
from services.agent.intent_router import IntentRouter
from services.agent.mentor_search import run_d1_pipeline
from services.agent.session import Session, get_session_store
from sqlalchemy import create_engine
from sqlalchemy.engine import Connection

logger = logging.getLogger(__name__)


class AgentController:
    """Agent HTTP 레이어 조율자"""

    def __init__(self, database_url: str | None = None):
        self.database_url = database_url or os.getenv(
            "DATABASE_URL",
            "postgresql://postgres:postgres@localhost:5432/devmentor",
        )
        self._engine = None
        self._intent_router = IntentRouter()

    @property
    def engine(self):
        if self._engine is None:
            self._engine = create_engine(self.database_url)
        return self._engine

    def get_connection(self) -> Connection:
        return self.engine.connect()

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

    # ============== D1 멘토 탐색 스트리밍 ==============

    async def stream_reply(
        self,
        request: AgentReplyRequest,
    ) -> AsyncGenerator[str, None]:
        """
        Agent 답변 SSE 스트리밍

        1. 세션 가져오기/생성
        2. 의도 분류
        3. D1이면 멘토 탐색 파이프라인 실행
        4. SSE 이벤트 생성

        Yields:
            SSE 형식 문자열 ("event: ...\ndata: ...\n\n")
        """
        store = get_session_store()
        session = store.get_or_create(request.session_id)

        # 세션에 사용자 메시지 추가
        session.add_user_message(request.message)

        # 세션 ID 전송
        yield _sse_format("session", {"session_id": session.session_id})

        # 의도 분류
        intent_result = await self._intent_router.classify(
            message=request.message,
            history=session.get_history(),
        )
        session.last_intent = intent_result.intent

        yield _sse_format("intent", intent_result.model_dump())

        # 의도별 분기
        if intent_result.intent == "D1":
            # D1: 멘토 탐색
            reply_text = ""
            with self.get_connection() as conn:
                async for event in run_d1_pipeline(
                    message=request.message,
                    conn=conn,
                    top_k=request.top_k,
                ):
                    yield _sse_format(event["event"], event["data"])

                    # reply_text 누적 (세션 이력용)
                    if event["event"] == "text":
                        reply_text += event["data"].get("chunk", "")

            # 세션에 어시스턴트 응답 추가
            if reply_text:
                session.add_assistant_message(reply_text.strip())

        elif intent_result.intent == "D2":
            # D2: 질문 개선 (미구현)
            msg = "질문 개선 기능은 준비 중이에요! 🚧 멘토 탐색을 원하시면 조건을 말씀해주세요."
            yield _sse_format("text", {"chunk": msg})
            yield _sse_format("done", {})
            session.add_assistant_message(msg)

        elif intent_result.intent == "D3":
            # D3: AI멘토 대화 (미구현)
            msg = "AI 멘토 대화 기능은 준비 중이에요! 🚧 멘토 탐색을 원하시면 조건을 말씀해주세요."
            yield _sse_format("text", {"chunk": msg})
            yield _sse_format("done", {})
            session.add_assistant_message(msg)


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
