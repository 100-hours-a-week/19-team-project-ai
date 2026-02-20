"""Agent 실시간 채팅 라우터 — SSE 스트리밍 엔드포인트"""

from controllers.agent_controller import AgentController, get_agent_controller
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from schemas.agent import AgentReplyRequest
from schemas.common import ApiResponse

router = APIRouter(prefix="/agent", tags=["Agent"])


@router.post(
    "/sessions",
    response_model=ApiResponse[dict],
    summary="새 Agent 세션 생성",
    description="새로운 Agent 채팅 세션을 생성하고 session_id를 반환합니다.",
)
async def create_session(
    controller: AgentController = Depends(get_agent_controller),
) -> ApiResponse[dict]:
    """새 세션 생성"""
    from schemas.common import ResponseCode

    session = await controller.create_session()
    return ApiResponse(code=ResponseCode.OK, data=session)


@router.get(
    "/sessions",
    response_model=ApiResponse[list[dict]],
    summary="Agent 세션 목록 조회",
    description="현재 활성화된 Agent 채팅 세션 목록을 반환합니다.",
)
async def list_sessions(
    controller: AgentController = Depends(get_agent_controller),
) -> ApiResponse[list[dict]]:
    """세션 목록 조회"""
    from schemas.common import ResponseCode

    sessions = await controller.list_sessions()
    return ApiResponse(code=ResponseCode.OK, data=sessions)


@router.get(
    "/sessions/{session_id}",
    response_model=ApiResponse[dict],
    summary="Agent 세션 조회",
    description="특정 Agent 채팅 세션의 정보를 반환합니다.",
)
async def get_session(
    session_id: str,
    controller: AgentController = Depends(get_agent_controller),
) -> ApiResponse[dict]:
    """세션 조회"""
    from schemas.common import ResponseCode

    session = await controller.get_session(session_id)
    if not session:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.")
    return ApiResponse(code=ResponseCode.OK, data=session)


@router.post(
    "/reply",
    summary="Agent 답변 (SSE 스트리밍)",
    description=(
        "사용자 메시지를 받아 의도를 분류하고, D1(멘토 탐색)이면 "
        "조건 추출 → 벡터 검색 → 재정렬 → 카드+멘트를 SSE 스트리밍으로 반환합니다.\n\n"
        "**SSE 이벤트 종류:**\n"
        "- `session` — 세션 ID\n"
        "- `intent` — 의도 분류 결과\n"
        "- `conditions` — 추출된 조건\n"
        "- `cards` — 멘토 카드 목록\n"
        "- `text` — 자연어 멘트 (청크 단위)\n"
        "- `done` — 완료"
    ),
    response_class=StreamingResponse,
)
async def agent_reply(
    request: AgentReplyRequest,
    controller: AgentController = Depends(get_agent_controller),
):
    """Agent 답변 SSE 스트리밍"""
    return StreamingResponse(
        controller.stream_reply(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # nginx proxy buffering 비활성화
        },
    )
