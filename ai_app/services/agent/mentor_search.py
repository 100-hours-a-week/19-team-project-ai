"""D1 멘토 탐색 파이프라인 — 조건 기반 벡터 검색 + 룰 재정렬 + SSE 스트리밍"""

import json
import logging
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from typing import Any

from adapters.llm_client import LLMClient, get_llm_client
from prompts import load_prompt
from schemas.agent import MentorCard, MentorConditions
from sqlalchemy import text
from sqlalchemy.engine import Connection

from services.agent.slot_filling import SlotFiller
from services.reco.embedder import ProfileEmbedder, get_embedder

logger = logging.getLogger(__name__)

# ============== 쿼리 빌드 ==============


def build_query_text(conditions: MentorConditions) -> str:
    """
    추출된 조건을 임베딩용 검색 쿼리 텍스트로 조합한다.

    예: "직무: 백엔드. 기술스택: Spring, MSA. 경력: 3년"
    """
    parts = []

    if conditions.job:
        parts.append(f"직무: {conditions.job}")
    if conditions.skills:
        parts.append(f"기술스택: {', '.join(conditions.skills)}")
    if conditions.experience_years is not None:
        parts.append(f"경력: {conditions.experience_years}년")
    if conditions.domain:
        parts.append(f"도메인: {conditions.domain}")
    if conditions.region:
        parts.append(f"지역: {conditions.region}")
    if conditions.company_type:
        parts.append(f"회사유형: {conditions.company_type}")
    if conditions.keywords:
        parts.append(f"키워드: {', '.join(conditions.keywords)}")

    query = ". ".join(parts) if parts else "멘토 추천"
    logger.info(f"검색 쿼리: {query}")
    return query


# ============== 벡터 검색 ==============

_VECTOR_SEARCH_QUERY = """
    SELECT
        u.id as user_id,
        u.nickname,
        u.introduction,
        ep.company_name,
        ep.verified,
        ep.rating_avg,
        ep.rating_count,
        ep.responded_request_count,
        ep.accepted_request_count,
        ep.rejected_request_count,
        ep.last_active_at,
        1 - (ep.embedding <=> CAST(:query_embedding AS vector)) as embedding_similarity,
        ARRAY_AGG(DISTINCT s.name) FILTER (WHERE s.name IS NOT NULL) as skills,
        ARRAY_AGG(DISTINCT j.name) FILTER (WHERE j.name IS NOT NULL) as jobs
    FROM expert_profiles ep
    JOIN users u ON ep.user_id = u.id
    LEFT JOIN user_skills us ON u.id = us.user_id
    LEFT JOIN skills s ON us.skill_id = s.id
    LEFT JOIN user_jobs uj ON u.id = uj.user_id
    LEFT JOIN jobs j ON uj.job_id = j.id
    WHERE ep.embedding IS NOT NULL
    GROUP BY u.id, u.nickname, u.introduction,
             ep.company_name, ep.verified, ep.rating_avg, ep.rating_count,
             ep.responded_request_count, ep.accepted_request_count,
             ep.rejected_request_count, ep.last_active_at, ep.embedding
    ORDER BY ep.embedding <=> CAST(:query_embedding AS vector)
    LIMIT :top_n
"""


def vector_search(
    query_embedding: list[float],
    conn: Connection,
    top_n: int = 50,
) -> list[dict[str, Any]]:
    """
    pgvector에서 멘토 후보 Top N 검색

    Args:
        query_embedding: 검색 쿼리 임베딩 벡터
        conn: SQLAlchemy DB 연결
        top_n: 검색 후보 수

    Returns:
        멘토 후보 리스트
    """
    result = conn.execute(
        text(_VECTOR_SEARCH_QUERY),
        {
            "query_embedding": str(query_embedding),
            "top_n": top_n,
        },
    )

    candidates = []
    for row in result:
        response_rate = 0.0
        if row.responded_request_count and row.responded_request_count > 0:
            response_rate = row.accepted_request_count / row.responded_request_count * 100

        candidates.append(
            {
                "user_id": row.user_id,
                "nickname": row.nickname,
                "introduction": row.introduction or "",
                "company_name": row.company_name,
                "verified": row.verified,
                "rating_avg": round(row.rating_avg, 1) if row.rating_avg else 0.0,
                "rating_count": row.rating_count or 0,
                "response_rate": round(response_rate, 1),
                "skills": row.skills or [],
                "jobs": row.jobs or [],
                "similarity_score": round(float(row.embedding_similarity), 4),
                "last_active_at": row.last_active_at,
            }
        )

    logger.info(f"벡터 검색 완료: {len(candidates)}명 후보")
    return candidates


# ============== 룰 기반 재정렬 ==============


def rule_rerank(
    candidates: list[dict],
    conditions: MentorConditions,
    top_k: int = 3,
) -> list[MentorCard]:
    """
    룰 기반 재정렬

    재정렬 규칙:
    1. 직무 일치 가중치 (+0.15)
    2. 기술스택 일치 가중치 (+0.05 × 일치 개수)
    3. 경력 차이 패널티 (차이 × -0.02, 최대 -0.1)
    4. 차이가 큰 경우 응답률 우선 보정
    5. 최근 활동 가중치 (7일 이내 +0.05)

    Args:
        candidates: 벡터 검색 결과 후보
        conditions: 사용자 요청 조건
        top_k: 최종 반환 수

    Returns:
        재정렬된 MentorCard 리스트
    """
    scored = []
    user_skills = set(s.lower() for s in conditions.skills) if conditions.skills else set()
    user_job = conditions.job.lower() if conditions.job else None

    for cand in candidates:
        score = cand["similarity_score"]
        filter_type = None

        # 1. 직무 일치 가중치
        mentor_jobs = set(j.lower() for j in cand.get("jobs", []))
        if user_job and user_job in mentor_jobs:
            score += 0.15
            filter_type = "job"

        # 2. 기술스택 일치 가중치
        mentor_skills = set(s.lower() for s in cand.get("skills", []))
        skill_overlap = len(user_skills & mentor_skills)
        if skill_overlap > 0:
            score += 0.05 * skill_overlap
            if filter_type is None:
                filter_type = "skill"

        # 3. 경력 차이 패널티 (멘토의 경력 정보 없으면 패스)
        # 참고: 현재 DB에 경력 연수 필드가 없으므로 이 로직은 추후 확장 가능

        # 4. 응답률 보정 (직무/스택 모두 불일치인 경우)
        if filter_type is None and cand["response_rate"] > 0:
            score += cand["response_rate"] / 1000  # 최대 +0.1
            filter_type = "response_rate"

        # 5. 최근 활동 가중치
        if cand.get("last_active_at"):
            try:
                last_active = cand["last_active_at"]
                if hasattr(last_active, "tzinfo") and last_active.tzinfo is None:
                    last_active = last_active.replace(tzinfo=timezone.utc)
                days_ago = (datetime.now(timezone.utc) - last_active).days
                if days_ago <= 7:
                    score += 0.05
            except Exception:
                pass

        scored.append(
            {
                **cand,
                "rerank_score": round(score, 4),
                "filter_type": filter_type,
            }
        )

    # 재정렬 점수 내림차순 정렬
    scored.sort(key=lambda x: x["rerank_score"], reverse=True)

    # Top K 선택 & MentorCard 변환
    cards = []
    for item in scored[:top_k]:
        cards.append(
            MentorCard(
                user_id=item["user_id"],
                nickname=item["nickname"],
                company_name=item.get("company_name"),
                verified=item.get("verified", False),
                rating_avg=item.get("rating_avg", 0.0),
                rating_count=item.get("rating_count", 0),
                response_rate=item.get("response_rate", 0.0),
                skills=item.get("skills", []),
                jobs=item.get("jobs", []),
                introduction=item.get("introduction", ""),
                similarity_score=item["similarity_score"],
                rerank_score=item["rerank_score"],
                filter_type=item.get("filter_type"),
            )
        )

    logger.info(f"재정렬 완료: {len(cards)}명 최종 선택")
    return cards


# ============== 추가 조건 안내 ==============


def check_need_more_conditions(conditions: MentorConditions) -> str | None:
    """
    조건이 넓으면 추가 안내 문구를 생성한다.

    Returns:
        추가 안내 문구 또는 None
    """
    missing = []

    if not conditions.job:
        missing.append("직무(백엔드, 프론트엔드 등)")
    if not conditions.skills:
        missing.append("기술스택(Spring, React 등)")
    if conditions.experience_years is None:
        missing.append("경력(3년차 이상 등)")
    if not conditions.domain:
        missing.append("도메인(핀테크, 이커머스 등)")

    if len(missing) >= 3:
        return f"💡 더 정확한 추천을 위해 다음 조건을 추가로 알려주시면 좋아요: {', '.join(missing[:3])}"
    elif len(missing) >= 2:
        return f"💡 {', '.join(missing)}을(를) 추가로 알려주시면 더 정확한 추천이 가능해요!"

    return None


# ============== 멘트 생성 ==============


async def compose_reply_text(
    conditions: MentorConditions,
    cards: list[MentorCard],
    need_more: str | None,
    llm: LLMClient | None = None,
) -> str:
    """
    멘토 카드 + 조건을 바탕으로 자연어 멘트를 생성한다.

    Args:
        conditions: 추출된 조건
        cards: 추천 멘토 카드
        need_more: 추가 조건 안내 문구 (없으면 None)
        llm: LLM 클라이언트

    Returns:
        자연어 멘트 문자열
    """
    llm = llm or get_llm_client()
    system_prompt = load_prompt("mentor_card_system")

    # 카드 데이터를 텍스트로 변환
    cards_text = json.dumps(
        [c.model_dump() for c in cards],
        ensure_ascii=False,
        indent=2,
    )

    conditions_text = json.dumps(
        conditions.model_dump(exclude_none=True),
        ensure_ascii=False,
    )

    user_prompt = f"""## 사용자 조건
{conditions_text}

## 추천 멘토 카드 ({len(cards)}명)
{cards_text}

## 추가 조건 필요 여부
{"있음: " + need_more if need_more else "없음 (조건 충분)"}

위 데이터를 참고하여 사용자에게 보여줄 추천 멘트를 작성하세요."""

    try:
        reply = await llm.generate(
            prompt=user_prompt,
            system_instruction=system_prompt,
            temperature=0.7,
            max_tokens=1024,
        )
        return reply.strip()
    except Exception as e:
        logger.error(f"멘트 생성 실패, 기본 멘트 반환: {e}")
        # fallback 멘트
        return _fallback_reply(conditions, cards, need_more)


def _fallback_reply(
    conditions: MentorConditions,
    cards: list[MentorCard],
    need_more: str | None,
) -> str:
    """LLM 실패 시 기본 멘트"""
    parts = []

    # 조건 요약
    cond_parts = []
    if conditions.job:
        cond_parts.append(conditions.job)
    if conditions.skills:
        cond_parts.append(", ".join(conditions.skills))
    if conditions.experience_years:
        cond_parts.append(f"{conditions.experience_years}년차")

    if cond_parts:
        parts.append(f"{'·'.join(cond_parts)} 조건으로 멘토를 찾았어요! 🎯\n")
    else:
        parts.append("멘토를 찾았어요! 🎯\n")

    # 카드 소개
    for i, card in enumerate(cards, 1):
        emoji = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"][i - 1] if i <= 5 else f"{i}."
        verified = " (✅ 인증)" if card.verified else ""
        company = f" — {card.company_name}" if card.company_name else ""
        skills_str = ", ".join(card.skills[:3]) if card.skills else ""
        parts.append(
            f"{emoji} **{card.nickname}**{company}{verified} | {skills_str} | 매칭 {int(card.rerank_score * 100)}%"
        )

    if need_more:
        parts.append(f"\n{need_more}")

    return "\n".join(parts)


# ============== D1 전체 파이프라인 (SSE 스트리밍) ==============


async def run_d1_pipeline(
    message: str,
    conn: Connection,
    top_k: int = 3,
    top_n: int = 50,
    llm: LLMClient | None = None,
    embedder: ProfileEmbedder | None = None,
) -> AsyncGenerator[dict, None]:
    """
    D1 조건 기반 멘토 탐색 파이프라인 (SSE 이벤트 생성기)

    흐름: 조건 추출 → 쿼리 빌드 → 임베딩 → 벡터 검색 → 룰 재정렬 → 카드 렌더 → 멘트 생성

    Yields:
        SSE 이벤트 dict: {"event": str, "data": dict}
    """
    llm = llm or get_llm_client()
    embedder = embedder or get_embedder()

    # 1. 조건 추출
    slot_filler = SlotFiller(llm=llm)
    conditions = await slot_filler.extract(message)

    yield {
        "event": "conditions",
        "data": conditions.model_dump(exclude_none=True),
    }

    # 2. 쿼리 빌드 & 임베딩 생성
    query_text = build_query_text(conditions)
    query_embedding = embedder.embed_text(query_text)
    embedding_list = query_embedding.tolist()

    # 3. 벡터 검색 Top N
    candidates = vector_search(embedding_list, conn, top_n=top_n)

    if not candidates:
        yield {
            "event": "text",
            "data": {"chunk": "조건에 맞는 멘토를 찾지 못했어요. 조건을 변경해서 다시 시도해보세요! 🙏"},
        }
        yield {"event": "done", "data": {}}
        return

    # 4. 룰 기반 재정렬 → Top K
    cards = rule_rerank(candidates, conditions, top_k=top_k)

    # 5. 카드 전송
    yield {
        "event": "cards",
        "data": {"cards": [c.model_dump() for c in cards]},
    }

    # 6. 추가 조건 필요 여부
    need_more = check_need_more_conditions(conditions)

    # 7. 자연어 멘트 생성 & 스트리밍
    reply_text = await compose_reply_text(conditions, cards, need_more, llm=llm)

    # 청크 단위로 스트리밍 (문장 단위)
    sentences = reply_text.split("\n")
    for sentence in sentences:
        if sentence.strip():
            yield {
                "event": "text",
                "data": {"chunk": sentence + "\n"},
            }

    # 8. 완료
    yield {"event": "done", "data": {}}
