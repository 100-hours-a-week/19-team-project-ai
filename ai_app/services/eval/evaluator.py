"""D1 멘토 추천 평가기 — 테스트셋 기반 E2E 평가

두 가지 평가 방식:
1. embedding_gt: 멘토 임베딩으로 직접 벡터 검색 → 자기 자신 검색 여부 (순수 검색 성능)
2. query_gt: 합성 질의 → 슬롯 필링 → 쿼리 빌드 → 벡터 검색 → 리랭킹 (E2E 성능)
"""

import json
import logging
import time
from pathlib import Path
from typing import Any, Optional

from adapters.db_client import VectorSearchClient, get_vector_search_client

from services.agent.mentor_search import build_query_text
from services.agent.slot_filling import SlotFiller
from services.reco.embedder import ProfileEmbedder, get_embedder

logger = logging.getLogger(__name__)

EVAL_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "eval"


class D1Evaluator:
    """D1 멘토 추천 파이프라인 평가"""

    def __init__(
        self,
        embedder: Optional[ProfileEmbedder] = None,
        vector_client: Optional[VectorSearchClient] = None,
    ):
        self.embedder = embedder or get_embedder()
        self.vector_client = vector_client or get_vector_search_client()
        self.slot_filler = SlotFiller()

    async def evaluate(
        self,
        testset_path: str | None = None,
        top_n: int = 50,
        top_k: int = 3,
    ) -> dict[str, Any]:
        """
        테스트셋 기반 평가 실행

        Args:
            testset_path: 테스트셋 JSONL 경로
            top_n: 벡터 검색 후보 수
            top_k: 최종 추천 수

        Returns:
            평가 결과 dict
        """
        path = Path(testset_path) if testset_path else EVAL_DIR / "testset_d1.jsonl"
        testset = self._load_testset(path)
        if not testset:
            return {"error": f"테스트셋 로드 실패: {path}"}

        # 임베딩 데이터 로드
        embeddings = self._load_embeddings()

        logger.info(f"평가 시작: {len(testset)}개 항목, top_n={top_n}, top_k={top_k}")

        embedding_results = []
        query_results = []

        for i, item in enumerate(testset):
            item_type = item.get("type", "query_gt")
            gt_id = item["gt_mentor_id"]

            if item_type == "embedding_gt":
                # Silver GT: 임베딩으로 직접 검색
                embedding = embeddings.get(str(gt_id))
                if not embedding:
                    continue

                result = await self._evaluate_embedding(
                    embedding=embedding,
                    gt_mentor_id=gt_id,
                    top_n=top_n,
                )
                embedding_results.append(result)
            else:
                # E2E: 질의 → 슬롯 필링 → 검색
                query = item.get("query", "")
                if not query:
                    continue

                logger.info(f"[{i + 1}/{len(testset)}] 평가: {query[:40]}...")
                result = await self._evaluate_query(
                    query=query,
                    gt_mentor_id=gt_id,
                    difficulty=item.get("difficulty", "medium"),
                    top_n=top_n,
                    top_k=top_k,
                )
                query_results.append(result)

        # 집계
        report = {
            "embedding_gt": self._aggregate(embedding_results, label="벡터검색(Silver GT)"),
            "query_gt": self._aggregate(query_results, label="E2E(합성질의)"),
            "config": {
                "testset_path": str(path),
                "embedding_gt_count": len(embedding_results),
                "query_gt_count": len(query_results),
                "top_n": top_n,
                "top_k": top_k,
            },
        }

        return report

    async def _evaluate_embedding(
        self,
        embedding: list[float],
        gt_mentor_id: int,
        top_n: int,
    ) -> dict[str, Any]:
        """Silver GT: 임베딩으로 직접 벡터 검색하여 자기 자신 검색 여부 확인"""
        start = time.time()

        try:
            candidates = await self.vector_client.search_similar_experts(
                query_embedding=embedding,
                top_n=top_n,
            )

            recommended_ids = [c["user_id"] for c in candidates]
            elapsed = (time.time() - start) * 1000

            rank = None
            if gt_mentor_id in recommended_ids:
                rank = recommended_ids.index(gt_mentor_id) + 1

            return {
                "gt_mentor_id": gt_mentor_id,
                "difficulty": "embedding",
                "rank": rank,
                "is_hit": rank is not None,
                "latency_ms": round(elapsed, 1),
            }
        except Exception as e:
            logger.error(f"임베딩 평가 실패 (user_id={gt_mentor_id}): {e}")
            return {
                "gt_mentor_id": gt_mentor_id,
                "difficulty": "embedding",
                "rank": None,
                "is_hit": False,
                "error": str(e),
                "latency_ms": 0,
            }

    async def _evaluate_query(
        self,
        query: str,
        gt_mentor_id: int,
        difficulty: str,
        top_n: int,
        top_k: int,
    ) -> dict[str, Any]:
        """E2E: 질의 → 슬롯 필링 → 쿼리 빌드 → 벡터 검색"""
        start = time.time()

        try:
            # Step 1: 슬롯 필링
            conditions = await self.slot_filler.extract(query)

            # Step 2: 쿼리 빌드 + 임베딩
            query_text = build_query_text(conditions)
            query_embedding = await self.embedder.embed_text(query_text)
            embedding_list = query_embedding.tolist()

            # Step 3: 벡터 검색 (DB 직접)
            candidates = await self.vector_client.search_similar_experts(
                query_embedding=embedding_list,
                top_n=top_n,
            )

            recommended_ids = [c["user_id"] for c in candidates]
            elapsed = (time.time() - start) * 1000

            rank = None
            if gt_mentor_id in recommended_ids:
                rank = recommended_ids.index(gt_mentor_id) + 1

            return {
                "query": query,
                "gt_mentor_id": gt_mentor_id,
                "difficulty": difficulty,
                "rank": rank,
                "is_hit": rank is not None,
                "conditions_extracted": conditions.model_dump(exclude_none=True),
                "latency_ms": round(elapsed, 1),
            }

        except Exception as e:
            elapsed = (time.time() - start) * 1000
            logger.error(f"E2E 평가 실패 (query={query[:30]}): {e}")
            return {
                "query": query,
                "gt_mentor_id": gt_mentor_id,
                "difficulty": difficulty,
                "rank": None,
                "is_hit": False,
                "error": str(e),
                "latency_ms": round(elapsed, 1),
            }

    def _aggregate(self, results: list[dict], label: str = "") -> dict[str, Any]:
        """결과 집계 — Hit@K, MRR, 난이도별"""
        valid = [r for r in results if "error" not in r]
        total = len(valid)

        if total == 0:
            return {"label": label, "metrics": {}, "total": 0, "details": results}

        hits = {1: 0, 3: 0, 5: 0, 10: 0}
        reciprocal_ranks = []

        for r in valid:
            rank = r.get("rank")
            if rank is not None:
                reciprocal_ranks.append(1.0 / rank)
                for k in hits:
                    if rank <= k:
                        hits[k] += 1
            else:
                reciprocal_ranks.append(0.0)

        metrics = {f"hit_at_{k}": round(hits[k] / total * 100, 2) for k in [1, 3, 5, 10]}
        metrics["mrr"] = round(sum(reciprocal_ranks) / total, 4)
        metrics["total"] = total
        metrics["avg_latency_ms"] = round(sum(r.get("latency_ms", 0) for r in valid) / total, 1)

        # 난이도별 (query_gt만)
        by_difficulty = {}
        for diff in ["easy", "medium", "hard"]:
            diff_results = [r for r in valid if r.get("difficulty") == diff]
            if not diff_results:
                continue
            diff_total = len(diff_results)
            diff_hits = sum(1 for r in diff_results if r.get("rank") and r["rank"] <= 3)
            diff_mrr_vals = [1.0 / r["rank"] if r.get("rank") else 0.0 for r in diff_results]
            by_difficulty[diff] = {
                "total": diff_total,
                "hit_at_3": round(diff_hits / diff_total * 100, 2),
                "mrr": round(sum(diff_mrr_vals) / diff_total, 4),
            }

        return {
            "label": label,
            "metrics": metrics,
            "by_difficulty": by_difficulty,
            "details": results,
        }

    def _load_testset(self, path: Path) -> list[dict]:
        """JSONL 테스트셋 로드"""
        if not path.exists():
            logger.error(f"테스트셋 파일 없음: {path}")
            return []

        records = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))

        logger.info(f"테스트셋 로드: {len(records)}건")
        return records

    def _load_embeddings(self) -> dict[str, list[float]]:
        """임베딩 파일 로드"""
        emb_path = EVAL_DIR / "testset_d1_embeddings.json"
        if not emb_path.exists():
            logger.warning(f"임베딩 파일 없음: {emb_path}")
            return {}

        with open(emb_path) as f:
            data = json.load(f)

        logger.info(f"임베딩 로드: {len(data)}건")
        return data

    async def save_report(
        self,
        report: dict[str, Any],
        output_path: str | None = None,
    ) -> str:
        """평가 리포트를 JSON 파일로 저장"""
        EVAL_DIR.mkdir(parents=True, exist_ok=True)
        path = Path(output_path) if output_path else EVAL_DIR / "eval_report_d1.json"

        with open(path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        logger.info(f"평가 리포트 저장: {path}")
        return str(path)
