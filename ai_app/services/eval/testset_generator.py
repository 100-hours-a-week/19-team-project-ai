"""테스트셋 생성 — DB 기반 Silver Ground Truth

expert_profiles 테이블에 jobs/skills/introduction이 없으므로,
멘토의 임베딩을 쿼리로 사용하여 자기 자신이 Top-K에 나오는지 평가하는
Silver Ground Truth 방식을 사용한다.

추가로, company_name 기반 합성 질의도 생성하여
슬롯 필링 → 쿼리 빌드 → 벡터 검색 E2E 파이프라인도 평가한다.
"""

import json
import logging
from pathlib import Path
from typing import Any, Optional

from adapters.db_client import get_pool
from adapters.llm_client import LLMClient, get_llm_client

logger = logging.getLogger(__name__)

TESTSET_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "eval"

# 합성 질의 생성용 프롬프트 (company_name 기반)
GENERATE_QUERY_PROMPT = """당신은 멘토링 플랫폼 사용자의 검색 질의를 생성하는 역할입니다.

아래 멘토 정보를 보고, 이 멘토를 찾을 법한 **자연스러운 사용자 질의**를 3개 생성하세요.

## 규칙
1. 실제 사용자가 채팅으로 입력할 법한 자연스러운 문장으로 작성
2. 난이도를 다양하게:
   - easy: 회사명이나 구체적 조건 명시 (예: "카카오에서 일하는 멘토 찾아줘")
   - medium: 간접적 표현 (예: "대기업에서 개발하시는 분")
   - hard: 추상적 표현 (예: "실무 경험 많은 시니어 개발자")
3. 한국어로 작성
4. 멘토의 company_name 정보를 참고하되, 반드시 포함하지 않아도 됨

## 멘토 정보
- user_id: {user_id}
- 회사: {company_name}
- 인증 여부: {verified}
- 평균 평점: {rating_avg}
- 응답 수: {responded_count}

## 출력 형식 (JSON 배열)
[
  {{"query": "사용자 질의", "difficulty": "easy"}},
  {{"query": "사용자 질의", "difficulty": "medium"}},
  {{"query": "사용자 질의", "difficulty": "hard"}}
]"""


class TestsetGenerator:
    """테스트셋 생성기 — DB 직접 조회 (백엔드 API 불필요)"""

    def __init__(self, llm: Optional[LLMClient] = None):
        self.llm = llm or get_llm_client()

    async def generate_testset(
        self,
        sample_size: int = 20,
    ) -> list[dict[str, Any]]:
        """
        DB에서 멘토 프로필을 조회하여 테스트셋 생성

        두 종류의 테스트 데이터:
        1. embedding_gt: 멘토 임베딩으로 검색 → 자기 자신 검색 여부 (Silver GT)
        2. query_gt: LLM 합성 질의 → 해당 멘토 검색 여부 (E2E)
        """
        pool = await get_pool()

        async with pool.acquire() as conn:
            # 임베딩 있는 멘토 중 랜덤 샘플링 (활동 데이터가 충분한 멘토 우선)
            rows = await conn.fetch(
                """
                SELECT user_id, company_name, verified, rating_avg,
                       rating_count, responded_request_count, embedding
                FROM expert_profiles
                WHERE embedding IS NOT NULL
                  AND responded_request_count > 0
                ORDER BY RANDOM()
                LIMIT $1
                """,
                sample_size,
            )

        if not rows:
            logger.error("멘토 프로필 조회 실패: 결과 없음")
            return []

        logger.info(f"테스트셋 생성 시작: {len(rows)}명 멘토")

        testset = []
        for i, row in enumerate(rows):
            user_id = row["user_id"]
            company = row["company_name"] or ""
            verified = row["verified"] or False
            rating_avg = row["rating_avg"] or 0.0
            responded = row["responded_request_count"] or 0

            # 임베딩 파싱
            embedding_str = row["embedding"]
            if isinstance(embedding_str, str):
                embedding = [float(x) for x in embedding_str.strip("[]").split(",")]
            else:
                embedding = list(embedding_str)

            # 1. Silver GT 데이터 (임베딩 직접 사용)
            testset.append(
                {
                    "type": "embedding_gt",
                    "query": None,  # 임베딩으로 직접 검색
                    "embedding": embedding,
                    "difficulty": "embedding",
                    "gt_mentor_id": user_id,
                    "gt_mentor_profile": {
                        "company_name": company,
                        "verified": verified,
                        "rating_avg": rating_avg,
                    },
                }
            )

            # 2. LLM 합성 질의 (E2E 평가)
            logger.info(f"[{i + 1}/{len(rows)}] 멘토 {user_id} 질의 생성 중...")
            queries = await self._generate_queries(
                user_id=user_id,
                company_name=company,
                verified=verified,
                rating_avg=rating_avg,
                responded_count=responded,
            )

            for q in queries:
                testset.append(
                    {
                        "type": "query_gt",
                        "query": q["query"],
                        "embedding": None,
                        "difficulty": q.get("difficulty", "medium"),
                        "gt_mentor_id": user_id,
                        "gt_mentor_profile": {
                            "company_name": company,
                            "verified": verified,
                            "rating_avg": rating_avg,
                        },
                    }
                )

        logger.info(f"테스트셋 생성 완료: {len(testset)}개 ({len(rows)} embedding + {len(testset) - len(rows)} query)")
        return testset

    async def generate_and_save(
        self,
        sample_size: int = 20,
        output_path: str | None = None,
    ) -> str:
        """테스트셋 생성 후 JSONL 파일로 저장"""
        testset = await self.generate_testset(sample_size=sample_size)

        if not testset:
            raise RuntimeError("테스트셋 생성 실패: 결과 없음")

        TESTSET_DIR.mkdir(parents=True, exist_ok=True)
        path = Path(output_path) if output_path else TESTSET_DIR / "testset_d1.jsonl"

        with open(path, "w", encoding="utf-8") as f:
            for item in testset:
                # embedding은 용량이 크므로 별도 저장
                save_item = {k: v for k, v in item.items() if k != "embedding"}
                if item.get("embedding"):
                    save_item["has_embedding"] = True
                f.write(json.dumps(save_item, ensure_ascii=False) + "\n")

        # 임베딩은 별도 파일로 저장
        emb_items = [item for item in testset if item.get("embedding")]
        if emb_items:
            emb_path = TESTSET_DIR / "testset_d1_embeddings.json"
            emb_data = {str(item["gt_mentor_id"]): item["embedding"] for item in emb_items}
            with open(emb_path, "w") as f:
                json.dump(emb_data, f)
            logger.info(f"임베딩 저장: {emb_path} ({len(emb_data)}건)")

        logger.info(f"테스트셋 저장: {path} ({len(testset)}건)")
        return str(path)

    async def _generate_queries(
        self,
        user_id: int,
        company_name: str,
        verified: bool,
        rating_avg: float,
        responded_count: int,
    ) -> list[dict]:
        """LLM으로 멘토 정보 기반 합성 질의 생성"""
        prompt = GENERATE_QUERY_PROMPT.format(
            user_id=user_id,
            company_name=company_name or "비공개",
            verified="인증됨" if verified else "미인증",
            rating_avg=f"{rating_avg:.1f}",
            responded_count=responded_count,
        )

        try:
            result = await self.llm.generate_json(
                prompt=prompt,
                temperature=0.7,
                prefer_api_key=True,
            )
            if isinstance(result, list):
                return result
            return []
        except Exception as e:
            logger.error(f"질의 생성 실패 (user_id={user_id}): {e}")
            return []
