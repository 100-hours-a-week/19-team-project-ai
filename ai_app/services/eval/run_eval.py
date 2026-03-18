"""평가 실행 스크립트 — ai_app 폴더에서 직접 실행

사용법 (ai_app 폴더에서):
    # 1. 테스트셋 생성 (멘토 20명 기반)
    python services/eval/run_eval.py generate --sample-size 20

    # 2. 평가 실행
    python services/eval/run_eval.py evaluate

    # 3. 전체 (생성 + 평가)
    python services/eval/run_eval.py all --sample-size 20
"""

import argparse
import asyncio
import logging
import os
import sys

# ai_app 폴더를 sys.path에 추가
_this_dir = os.path.dirname(os.path.abspath(__file__))
_ai_app_dir = os.path.abspath(os.path.join(_this_dir, "..", ".."))
if _ai_app_dir not in sys.path:
    sys.path.insert(0, _ai_app_dir)

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)


async def cmd_generate(args):
    """테스트셋 생성"""
    from services.eval.testset_generator import TestsetGenerator

    generator = TestsetGenerator()
    path = await generator.generate_and_save(sample_size=args.sample_size)
    print(f"\n✅ 테스트셋 생성 완료: {path}")


async def cmd_evaluate(args):
    """평가 실행"""
    from services.eval.evaluator import D1Evaluator

    evaluator = D1Evaluator()
    report = await evaluator.evaluate(
        testset_path=args.testset,
        top_n=args.top_n,
        top_k=args.top_k,
    )

    path = await evaluator.save_report(report)
    _print_report(report)
    print(f"\n📄 상세 리포트: {path}")


async def cmd_all(args):
    """전체 실행: 생성 + 평가"""
    print("=" * 60)
    print("Phase 1: 테스트셋 생성")
    print("=" * 60)
    await cmd_generate(args)

    print("\n" + "=" * 60)
    print("Phase 2: 평가")
    print("=" * 60)
    await cmd_evaluate(args)


def _print_report(report: dict):
    """평가 결과 출력"""
    print("\n" + "=" * 60)
    print("📊 D1 멘토 추천 평가 결과")
    print("=" * 60)

    config = report.get("config", {})
    print(f"설정: top_n={config.get('top_n')}, top_k={config.get('top_k')}")
    print(f"Silver GT: {config.get('embedding_gt_count', 0)}건, 합성 질의: {config.get('query_gt_count', 0)}건")

    # Silver GT 결과
    emb = report.get("embedding_gt", {})
    emb_metrics = emb.get("metrics", {})
    if emb_metrics:
        print("\n--- 벡터 검색 (Silver GT) ---")
        print(f"  Hit@1:  {emb_metrics.get('hit_at_1', 0):.1f}%")
        print(f"  Hit@3:  {emb_metrics.get('hit_at_3', 0):.1f}%")
        print(f"  Hit@5:  {emb_metrics.get('hit_at_5', 0):.1f}%")
        print(f"  Hit@10: {emb_metrics.get('hit_at_10', 0):.1f}%")
        print(f"  MRR:    {emb_metrics.get('mrr', 0):.4f}")
        print(f"  레이턴시: {emb_metrics.get('avg_latency_ms', 0):.0f}ms")

    # E2E 결과
    qgt = report.get("query_gt", {})
    q_metrics = qgt.get("metrics", {})
    if q_metrics:
        print("\n--- E2E (합성 질의 → 슬롯필링 → 검색) ---")
        print(f"  Hit@1:  {q_metrics.get('hit_at_1', 0):.1f}%")
        print(f"  Hit@3:  {q_metrics.get('hit_at_3', 0):.1f}%")
        print(f"  Hit@5:  {q_metrics.get('hit_at_5', 0):.1f}%")
        print(f"  Hit@10: {q_metrics.get('hit_at_10', 0):.1f}%")
        print(f"  MRR:    {q_metrics.get('mrr', 0):.4f}")
        print(f"  레이턴시: {q_metrics.get('avg_latency_ms', 0):.0f}ms")

        # 난이도별
        by_diff = qgt.get("by_difficulty", {})
        if by_diff:
            print("\n  난이도별 Hit@3:")
            for diff in ["easy", "medium", "hard"]:
                if diff in by_diff:
                    d = by_diff[diff]
                    print(f"    {diff:8s}: {d.get('hit_at_3', 0):.1f}% (n={d.get('total', 0)})")

    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="D1 멘토 추천 평가 도구")
    subparsers = parser.add_subparsers(dest="command", help="실행할 명령")

    # generate
    gen_parser = subparsers.add_parser("generate", help="테스트셋 생성")
    gen_parser.add_argument("--sample-size", type=int, default=20, help="멘토 수 (기본: 20)")

    # evaluate
    eval_parser = subparsers.add_parser("evaluate", help="평가 실행")
    eval_parser.add_argument("--testset", type=str, default=None, help="테스트셋 경로")
    eval_parser.add_argument("--top-n", type=int, default=50, help="벡터 검색 후보 수")
    eval_parser.add_argument("--top-k", type=int, default=3, help="최종 추천 수")

    # all
    all_parser = subparsers.add_parser("all", help="전체 실행 (생성 + 평가)")
    all_parser.add_argument("--sample-size", type=int, default=20, help="멘토 수 (기본: 20)")
    all_parser.add_argument("--testset", type=str, default=None, help="테스트셋 경로")
    all_parser.add_argument("--top-n", type=int, default=50, help="벡터 검색 후보 수")
    all_parser.add_argument("--top-k", type=int, default=3, help="최종 추천 수")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    cmd_map = {
        "generate": cmd_generate,
        "evaluate": cmd_evaluate,
        "all": cmd_all,
    }

    asyncio.run(cmd_map[args.command](args))


if __name__ == "__main__":
    main()
