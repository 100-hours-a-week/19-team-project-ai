"""Agent LangGraph — StateGraph 기반 파이프라인 오케스트레이션"""

import logging
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, StateGraph
from schemas.agent import IntentResult, MentorCard, MentorConditions

from services.agent.intent_router import IntentRouter
from services.agent.mentor_search import (
    build_query_text,
    check_need_more_conditions,
    compose_reply_text,
    rule_rerank,
    vector_search,
)
from services.agent.slot_filling import SlotFiller
from services.reco.embedder import get_embedder

logger = logging.getLogger(__name__)


# ============== 상태 정의 ==============


def _append_events(left: list[dict], right: list[dict]) -> list[dict]:
    """events 필드를 누적(append)하는 리듀서"""
    return left + right


class AgentState(TypedDict, total=False):
    """그래프 전체에서 공유되는 상태"""

    # ---- 입력 ----
    message: str
    history: list[dict]
    top_k: int

    # ---- 중간 결과 ----
    intent_result: IntentResult
    conditions: MentorConditions
    candidates: list[dict[str, Any]]
    cards: list[MentorCard]
    reply_text: str
    need_more: str | None

    # ---- SSE 이벤트 누적 ----
    events: Annotated[list[dict], _append_events]


# ============== 노드 함수 ==============


async def classify_intent_node(state: AgentState) -> dict:
    """의도 분류 노드"""
    router = IntentRouter()
    intent_result = await router.classify(
        message=state["message"],
        history=state.get("history"),
    )
    logger.info(f"의도 분류: {intent_result.intent} (confidence={intent_result.confidence})")

    return {
        "intent_result": intent_result,
        "events": [{"event": "intent", "data": intent_result.model_dump()}],
    }


async def extract_conditions_node(state: AgentState) -> dict:
    """조건 추출(Slot Filling) 노드"""
    filler = SlotFiller()
    conditions = await filler.extract(state["message"])

    return {
        "conditions": conditions,
        "events": [{"event": "conditions", "data": conditions.model_dump(exclude_none=True)}],
    }


async def vector_search_node(state: AgentState) -> dict:
    """벡터 검색 노드"""
    conditions = state["conditions"]

    # 쿼리 빌드 & 임베딩
    query_text = build_query_text(conditions)
    embedder = get_embedder()
    query_embedding = embedder.embed_text(query_text)
    embedding_list = query_embedding.tolist()

    # 백엔드 API 경유 벡터 검색
    candidates = await vector_search(embedding_list, top_n=50)

    if not candidates:
        return {
            "candidates": [],
            "cards": [],
            "events": [
                {
                    "event": "text",
                    "data": {"chunk": "조건에 맞는 멘토를 찾지 못했어요. 조건을 변경해서 다시 시도해보세요! 🙏"},
                },
                {"event": "done", "data": {}},
            ],
        }

    return {"candidates": candidates, "events": []}


async def rerank_node(state: AgentState) -> dict:
    """룰 기반 재정렬 노드"""
    # 후보가 없으면 스킵 (vector_search_node에서 이미 done 이벤트 발생)
    if not state.get("candidates"):
        return {"cards": [], "events": []}

    cards = rule_rerank(
        state["candidates"],
        state["conditions"],
        top_k=state.get("top_k", 3),
    )

    return {
        "cards": cards,
        "events": [{"event": "cards", "data": {"cards": [c.model_dump() for c in cards]}}],
    }


async def compose_reply_node(state: AgentState) -> dict:
    """자연어 멘트 생성 노드"""
    cards = state.get("cards", [])
    if not cards:
        return {"reply_text": "", "events": []}

    conditions = state["conditions"]
    need_more = check_need_more_conditions(conditions)
    reply_text = await compose_reply_text(conditions, cards, need_more)

    # 문장 단위로 SSE 청크 생성
    text_events = []
    for sentence in reply_text.split("\n"):
        if sentence.strip():
            text_events.append({"event": "text", "data": {"chunk": sentence + "\n"}})

    text_events.append({"event": "done", "data": {}})

    return {
        "reply_text": reply_text,
        "need_more": need_more,
        "events": text_events,
    }


async def handle_d2_node(state: AgentState) -> dict:
    """D2 질문 개선 노드 (미구현)"""
    msg = "질문 개선 기능은 준비 중이에요! 🚧 멘토 탐색을 원하시면 조건을 말씀해주세요."
    return {
        "reply_text": msg,
        "events": [
            {"event": "text", "data": {"chunk": msg}},
            {"event": "done", "data": {}},
        ],
    }


async def handle_d3_node(state: AgentState) -> dict:
    """D3 AI멘토 대화 노드 (미구현)"""
    msg = "AI 멘토 대화 기능은 준비 중이에요! 🚧 멘토 탐색을 원하시면 조건을 말씀해주세요."
    return {
        "reply_text": msg,
        "events": [
            {"event": "text", "data": {"chunk": msg}},
            {"event": "done", "data": {}},
        ],
    }


# ============== 조건부 라우팅 ==============


def route_by_intent(state: AgentState) -> str:
    """의도에 따라 다음 노드를 결정"""
    intent = state["intent_result"].intent
    if intent == "D1":
        return "extract_conditions"
    elif intent == "D2":
        return "handle_d2"
    else:
        return "handle_d3"


# ============== 그래프 빌드 ==============


def build_agent_graph() -> StateGraph:
    """Agent StateGraph를 구성하고 컴파일한다."""
    graph = StateGraph(AgentState)

    # 노드 등록
    graph.add_node("classify_intent", classify_intent_node)
    graph.add_node("extract_conditions", extract_conditions_node)
    graph.add_node("vector_search", vector_search_node)
    graph.add_node("rerank", rerank_node)
    graph.add_node("compose_reply", compose_reply_node)
    graph.add_node("handle_d2", handle_d2_node)
    graph.add_node("handle_d3", handle_d3_node)

    # 엣지 연결
    graph.set_entry_point("classify_intent")
    graph.add_conditional_edges(
        "classify_intent",
        route_by_intent,
        {
            "extract_conditions": "extract_conditions",
            "handle_d2": "handle_d2",
            "handle_d3": "handle_d3",
        },
    )
    graph.add_edge("extract_conditions", "vector_search")
    graph.add_edge("vector_search", "rerank")
    graph.add_edge("rerank", "compose_reply")
    graph.add_edge("compose_reply", END)
    graph.add_edge("handle_d2", END)
    graph.add_edge("handle_d3", END)

    return graph.compile()


# 싱글톤
_compiled_graph = None


def get_agent_graph():
    """컴파일된 그래프 싱글톤"""
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_agent_graph()
        logger.info("✅ Agent LangGraph 컴파일 완료")
    return _compiled_graph
