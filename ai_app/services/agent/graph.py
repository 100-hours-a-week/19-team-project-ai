"""Agent LangGraph — StateGraph 기반 파이프라인 오케스트레이션"""

import logging
import re
from typing import Annotated, TypedDict

from adapters.llm_client import get_llm_client
from langgraph.graph import END, StateGraph
from prompts import load_prompt
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
from services.repo.feedback_collector import get_feedback_collector
from services.repo.job_parser import parse_job_from_url

logger = logging.getLogger(__name__)


# ============== 상태 정의 ==============


def _append_events(left: list[dict], right: list[dict]) -> list[dict]:
    """events 필드를 누적(append)하는 리듀서용 함수"""
    return left + right


class AgentState(TypedDict):
    # ---- 기본 입력 및 세션 ----
    message: str
    history: list[dict] | None

    # ---- 의도 및 조건 ----
    intent_result: IntentResult | None
    conditions: MentorConditions | None

    # ---- D1 멘토 탐색 관련 ----
    candidates: list[dict] | None
    cards: list[MentorCard] | None
    reply_text: str | None
    need_more: bool | None
    top_k: int | None

    # ---- D3 RAG 관련 ----
    resume: str | None
    target_job: str | None
    job_link: str | None
    search_query: str | None
    feedback_context: list[dict] | None
    post_process_result: dict | None

    # ---- SSE 이벤트 누적 ----
    events: Annotated[list[dict], _append_events]


# ============== 노드 함수 ==============


async def classify_intent_node(state: AgentState) -> dict:
    """의도 분류 노드"""
    message = state.get("message", "").strip().lower()
    
    # 단순 인사말 처리 (LLM 스킵)
    cleaned_msg = re.sub(r'[^가-힣a-z]', '', message)
    if cleaned_msg in ["안녕", "안녕하세요", "반가워", "반가워요", "반갑습니다", "하이", "hello", "hi"]:
        intent_result = IntentResult(intent="GREETING", confidence=1.0)
        logger.info("의도 분류(하드코딩): GREETING")
        return {
            "intent_result": intent_result,
            "events": [{"event": "intent", "data": intent_result.model_dump()}],
        }

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


async def handle_greeting_node(state: AgentState) -> dict:
    """단순 인사 처리 노드"""
    reply = "안녕하세요! AI 멘토입니다. 어떤 도움이 필요하신가요?"
    return {
        "reply_text": reply,
        "events": [
            {"event": "text", "data": {"chunk": reply + "\n"}},
            {"event": "done", "data": {}}
        ]
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
    query_embedding = await embedder.embed_text(query_text)
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


async def organize_input_node(state: AgentState) -> dict:
    """[D3] 입력 정리 노드: 질문, 목표 직무, 이력서, 히스토리 통합"""
    logger.info("D3 입력 정리 중...")

    target_job = state.get("target_job") or "개발자"
    job_link = state.get("job_link")
    # 세션에서 이미 파싱된 데이터가 있을 수 있음 (AgentController에서 주입)
    parsed_job_data = state.get(
        "post_process_result"
    )  # 임시로 post_process_result 등에 저장하거나 AgentState 확장 필요

    resume_context = state.get("resume") or "대학교 4학년, 코딩 테스트 준비 중"

    events = []

    # 1. 이미 파싱된 데이터가 있는지 확인
    if parsed_job_data:
        logger.info("기존 세션에서 파싱된 공고 데이터를 활용합니다.")
        job_desc = f"\n[분석된 채용 공고 정보]\n- 주요 업무: {', '.join(parsed_job_data.get('responsibilities', []))}\n- 자격 요건: {', '.join(parsed_job_data.get('qualifications', []))}"
        resume_context += job_desc
    # 2. 파싱된 데이터는 없지만 링크는 있는 경우 (새로운 링크 등)
    elif job_link:
        events.append(
            {"event": "text", "data": {"chunk": f"제공해주신 공고 링크({job_link})를 분석하고 있어요... 🔗\n"}}
        )
        try:
            parsed = await parse_job_from_url(job_link)
            if parsed.get("success"):
                job_data = parsed["data"]
                job_desc = f"\n[분석된 채용 공고 정보]\n- 주요 업무: {', '.join(job_data.get('responsibilities', []))}\n- 자격 요건: {', '.join(job_data.get('qualifications', []))}"
                resume_context += job_desc
                logger.info(f"공고 파싱 성공: {job_link}")
                # 파싱 결과 저장 (이후 루프를 위해)
                parsed_job_data = job_data
            else:
                logger.warning(f"공고 파싱 실패: {parsed.get('error')}")
        except Exception as e:
            logger.error(f"공고 파싱 중 오류: {e}")

    events.append({"event": "text", "data": {"chunk": "사용자님의 상황과 목표를 바탕으로 분석을 시작할게요. 🔍\n"}})

    return {
        "target_job": target_job,
        "resume": resume_context,
        "post_process_result": parsed_job_data,  # 세션 업데이트를 위해 전달
        "events": events,
    }


async def generate_search_query_node(state: AgentState) -> dict:
    """[D3] 검색 질의 생성 노드: LLM을 이용해 검색 키워드 및 의도 파악"""
    llm = get_llm_client()

    prompt = f"""사용자 질문: {state["message"]}
목표 직무: {state.get("target_job")}
사용자 이력서 요약: {state.get("resume")}

위 정보를 바탕으로 현직자 피드백 데이터셋에서 검색할 핵심 키워드 3~5개만 콤마(,)로 구분하여 출력하세요. 다른 설명은 절대 하지 마세요."""

    try:
        query = await llm.generate(prompt=prompt, temperature=0.2)
        query = query.strip().replace("\n", " ")
    except Exception:
        query = f"{state['message']} {state.get('target_job', '')}"

    logger.info(f"D3 검색 질의 생성: {query}")
    return {
        "search_query": query,
        "events": [{"event": "text", "data": {"chunk": "현직자들의 조언을 검색하고 있어요... 🔍\n"}}],
    }


async def feedback_retrieval_node(state: AgentState) -> dict:
    """[D3] RAG 검색 노드: 피드백 데이터셋에서 유사 답변 벡터 검색"""
    collector = get_feedback_collector()

    search_query = state.get("search_query", state["message"])
    target_job = state.get("target_job", "")

    # 직무 태그 매핑 (한글 → DB 태그)
    job_tag_map = {
        "백엔드": "BE",
        "backend": "BE",
        "프론트엔드": "FE",
        "frontend": "FE",
        "프론트": "FE",
        "ai": "AI",
        "ml": "AI",
        "인공지능": "AI",
        "데이터": "DATA",
        "data": "DATA",
    }
    job_tag = job_tag_map.get(target_job.lower()) if target_job else None

    try:
        results = await collector.search_feedbacks(
            query_text=search_query,
            job_tag=job_tag,
            top_k=5,
        )

        if not results:
            # job_tag 필터 없이 재시도
            results = await collector.search_feedbacks(
                query_text=search_query,
                job_tag=None,
                top_k=5,
            )

        return {"feedback_context": results, "events": []}
    except Exception as e:
        logger.warning(f"피드백 검색 실패, 빈 컨텍스트로 진행: {e}")
        return {"feedback_context": [], "events": []}


async def compress_context_node(state: AgentState) -> dict:
    """[D3] 컨텍스트 정리 노드: 중복 제거 및 품질 기반 필터링"""
    context = state.get("feedback_context", [])
    if not context:
        return {"events": []}

    # 1. 유사도 낮은 결과 제거 (임계값 미만)
    min_similarity = 0.3
    filtered = [c for c in context if c.get("similarity_score", 1.0) >= min_similarity]

    # 2. 중복 답변 제거 (답변 텍스트가 80% 이상 겹치면 제거)
    deduplicated = []
    seen_answers: list[str] = []
    for item in filtered:
        answer = item.get("answer", "")
        is_duplicate = False
        for seen in seen_answers:
            # 간단한 중복 체크: 짧은 쪽 기준 포함 여부
            shorter, longer = (answer, seen) if len(answer) <= len(seen) else (seen, answer)
            if shorter and shorter in longer:
                is_duplicate = True
                break
        if not is_duplicate:
            deduplicated.append(item)
            seen_answers.append(answer)

    # 3. 품질 점수 기준 정렬
    deduplicated.sort(key=lambda x: (x.get("quality_score", 0), x.get("similarity_score", 0)), reverse=True)

    # 최대 5개
    final = deduplicated[:5]
    logger.info(f"컨텍스트 압축: {len(context)}건 → {len(final)}건")

    return {"feedback_context": final, "events": []}


async def generate_answer_node(state: AgentState) -> dict:
    """[D3] 답변 생성 노드: 페르소나와 정책에 따른 최종 답변 생성"""
    llm = get_llm_client()
    system_prompt = load_prompt("aimento_d3_system")

    context_text = "\n\n".join(
        [
            f"질문: {c['question']}\n답변: {c['answer']}\n(멘토 ID: {c.get('mentor_id', 'N/A')})"
            for c in state.get("feedback_context", [])
        ]
    )

    user_prompt = f"""## 사용자 질문
{state["message"]}

## 사용자 맥락
- 목표 직무: {state.get("target_job")}
- 이력서 요약: {state.get("resume")}

## 검색된 현직자 피드백 (Context)
{context_text}

## 지시사항
위 컨텍스트를 바탕으로 AI 멘토로서 답변을 작성하세요."""

    try:
        reply = await llm.generate(prompt=user_prompt, system_instruction=system_prompt, temperature=0.7)

        text_events = []
        for line in reply.split("\n"):
            if line.strip():
                text_events.append({"event": "text", "data": {"chunk": line + "\n"}})

        return {"reply_text": reply, "events": text_events}
    except Exception as e:
        logger.error(f"D3 답변 생성 실패: {e}")
        error_msg = "죄송합니다. 답변을 생성하는 중 오류가 발생했어요. 잠시 후 다시 시도해주세요."
        return {"reply_text": error_msg, "events": [{"event": "text", "data": {"chunk": error_msg + "\n"}}]}


async def post_process_node(state: AgentState) -> dict:
    """[D3] 후처리 노드: 일반론 검사 및 액션 아이템 확인"""
    reply = state.get("reply_text", "")

    # 간단한 품질 체크
    has_action_items = "액션 아이템" in reply or "실천" in reply or "-" in reply
    is_too_short = len(reply) < 50

    if is_too_short:
        logger.warning("답변이 너무 짧습니다. 재생성이 필요할 수 있습니다.")

    return {
        "post_process_result": {"has_action_items": has_action_items, "is_too_short": is_too_short},
        "events": [{"event": "done", "data": {}}],
    }


def route_by_intent(state: AgentState) -> str:
    """의도에 따라 다음 노드를 결정"""
    intent = state["intent_result"].intent
    if intent == "GREETING":
        return "handle_greeting"
    elif intent == "D1":
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
    graph.add_node("handle_greeting", handle_greeting_node)
    graph.add_node("extract_conditions", extract_conditions_node)
    graph.add_node("vector_search", vector_search_node)
    graph.add_node("rerank", rerank_node)
    graph.add_node("compose_reply", compose_reply_node)
    graph.add_node("handle_d2", handle_d2_node)
    graph.add_node("organize_input", organize_input_node)
    graph.add_node("generate_search_query", generate_search_query_node)
    graph.add_node("feedback_retrieval", feedback_retrieval_node)
    graph.add_node("compress_context", compress_context_node)
    graph.add_node("generate_answer", generate_answer_node)
    graph.add_node("post_process", post_process_node)

    # 엣지 연결
    graph.set_entry_point("classify_intent")
    graph.add_conditional_edges(
        "classify_intent",
        route_by_intent,
        {
            "handle_greeting": "handle_greeting",
            "extract_conditions": "extract_conditions",
            "handle_d2": "handle_d2",
            "handle_d3": "organize_input",  # D3 진입점 변경
        },
    )
    graph.add_edge("handle_greeting", END)
    graph.add_edge("extract_conditions", "vector_search")
    graph.add_edge("vector_search", "rerank")
    graph.add_edge("rerank", "compose_reply")
    graph.add_edge("compose_reply", END)
    graph.add_edge("handle_d2", END)

    # D3 파이프라인 연결
    graph.add_edge("organize_input", "generate_search_query")
    graph.add_edge("generate_search_query", "feedback_retrieval")
    graph.add_edge("feedback_retrieval", "compress_context")
    graph.add_edge("compress_context", "generate_answer")
    graph.add_edge("generate_answer", "post_process")
    graph.add_edge("post_process", END)

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
