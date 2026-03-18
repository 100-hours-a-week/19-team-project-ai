"""시드 데이터 로딩 — seeds_final.jsonl을 백엔드 API로 저장"""

import json
import logging
from pathlib import Path

from adapters.backend_client import get_backend_client

logger = logging.getLogger(__name__)

SEEDS_PATH = Path(__file__).resolve().parent.parent / "data" / "seeds_final.jsonl"

# 배치 저장 시 한 번에 보낼 건수
BATCH_SIZE = 10


async def load_seeds(seeds_path: str | None = None) -> int:
    """
    시드 JSONL 파일을 백엔드 API를 통해 expert_feedbacks 테이블에 저장

    Args:
        seeds_path: JSONL 파일 경로 (기본: ai_app/data/seeds_final.jsonl)

    Returns:
        삽입된 건수
    """
    path = Path(seeds_path) if seeds_path else SEEDS_PATH
    if not path.exists():
        logger.error(f"시드 파일을 찾을 수 없습니다: {path}")
        return 0

    # JSONL 파싱
    records = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))

    if not records:
        logger.warning("시드 데이터가 비어 있습니다.")
        return 0

    logger.info(f"시드 데이터 {len(records)}건 로딩 시작...")

    client = get_backend_client()
    total_inserted = 0

    # 배치 단위로 API 호출
    for i in range(0, len(records), BATCH_SIZE):
        batch = records[i : i + BATCH_SIZE]

        feedbacks = []
        for rec in batch:
            feedback = {
                "mentor_id": rec.get("mentor_id", 0),
                "question": rec["question"],
                "answer": rec["answer"],
                "job_tag": rec.get("job_tag", "common"),
                "question_type": rec.get("question_type", "career_advice"),
                "embedding_text": rec.get("embedding_text", ""),
                "source_type": rec.get("source_type", "seed"),
                "quality_score": rec.get("quality_score", 5),
            }
            # 임베딩이 있으면 포함
            if rec.get("embedding"):
                feedback["embedding"] = rec["embedding"]
            feedbacks.append(feedback)

        try:
            inserted = await client.save_feedbacks_batch(feedbacks)
            total_inserted += inserted
            logger.info(f"  배치 {i // BATCH_SIZE + 1}: {inserted}건 저장")
        except Exception as e:
            logger.error(f"  배치 {i // BATCH_SIZE + 1} 저장 실패: {e}")

    logger.info(f"시드 데이터 로딩 완료: {total_inserted}/{len(records)}건")
    return total_inserted
