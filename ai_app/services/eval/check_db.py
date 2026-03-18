import asyncio
import os
import sys

# 프로젝트 루트 경로를 참조할 수 있도록 sys.path 추가
_this_dir = os.path.dirname(os.path.abspath(__file__))
_ai_app_dir = os.path.abspath(os.path.join(_this_dir, "..", ".."))
if _ai_app_dir not in sys.path:
    sys.path.insert(0, _ai_app_dir)

import asyncpg  # noqa: E402

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


async def check():
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("DATABASE_URL 없음")
        return

    conn = await asyncpg.connect(db_url)
    try:
        # 1. 컬럼 확인
        cols = await conn.fetch(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_name = 'expert_profiles' ORDER BY ordinal_position"
        )
        print("=== expert_profiles 컬럼 ===")
        for c in cols:
            print(f"  {c['column_name']:30s} {c['data_type']}")

        # 2. 총 행 수
        total = await conn.fetchval("SELECT count(*) FROM expert_profiles")
        embedded = await conn.fetchval("SELECT count(*) FROM expert_profiles WHERE embedding IS NOT NULL")
        print(f"\n총 행: {total}, 임베딩 있는 행: {embedded}")

        # 3. 샘플 1건
        row = await conn.fetchrow("SELECT * FROM expert_profiles WHERE embedding IS NOT NULL LIMIT 1")
        if row:
            print("\n=== 샘플 1건 (컬럼: 값 타입) ===")
            for key in row.keys():
                val = row[key]
                val_preview = str(val)[:100] if val is not None else "NULL"
                print(f"  {key:30s} {type(val).__name__:10s} {val_preview}")
    finally:
        await conn.close()


asyncio.run(check())
