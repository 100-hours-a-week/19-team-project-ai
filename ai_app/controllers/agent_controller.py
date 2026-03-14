"""Agent 컨트롤러 — LangGraph 기반 SSE 스트리밍 조율"""

import json
import logging
import os

from middleware.otel_lgtm_metrics import tracked_db_connection
from schemas.agent import AgentReplyRequest, AgentSessionCreateRequest
from services.agent.graph import get_agent_graph
from services.agent.session import get_session_store
from services.repo.job_parser import parse_job_from_url

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

    async def create_session(self, request: AgentSessionCreateRequest | None = None) -> dict:
        """새 세션 생성 및 초기 공고 파싱"""
        store = get_session_store()
        session = store.create()

        if request:
            session.job_link = request.job_link

            # 공고 링크가 있으면 즉시 파싱
            if request.job_link:
                logger.info(f"세션 생성 시 공고 파싱 시작: {request.job_link}")
                try:
                    parsed = await parse_job_from_url(request.job_link)
                    if parsed.get("success"):
                        session.parsed_job_data = parsed["data"]
                except Exception as e:
                    logger.error(f"초기 공고 파싱 실패: {e}")

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

        # Langfuse Callback Handler 설정 (환경 변수 기반 자동 구성)
        from langfuse.langchain import CallbackHandler

        langfuse_handler = CallbackHandler()

        # 2. LangGraph 실행 (astream 사용)
        graph = get_agent_graph()
        config = {"callbacks": [langfuse_handler]}
        inputs = {
            "message": request.message,
            "target_job": session.target_job,
            "job_link": session.job_link,
            "history": session.get_history(),
            "top_k": request.top_k,
            "post_process_result": session.parsed_job_data,
            "events": [],
        }

        reply_text = ""
        # 2. LangGraph 실행 (astream 사용)
        async for chunk in graph.astream(inputs, config=config, stream_mode="updates"):
            # 각 노드의 출력을 events 필드에서 추출
            for node_name, node_output in chunk.items():
                if "events" in node_output:
                    for event in node_output["events"]:
                        yield _sse_format(event["event"], event["data"])

                        # reply_text 누적 (세션 이력용)
                        if event["event"] == "text":
                            reply_text += event["data"].get("chunk", "")

                # 의도 저장 (classify_intent 노드인 경우)
                if node_name == "classify_intent" and "intent_result" in node_output:
                    session.last_intent = node_output["intent_result"].intent

                # 파싱 데이터 업데이트 (organize_input_node 또는 post_process_node 등에서 갱신 시)
                if "post_process_result" in node_output and node_output["post_process_result"]:
                    session.parsed_job_data = node_output["post_process_result"]

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
