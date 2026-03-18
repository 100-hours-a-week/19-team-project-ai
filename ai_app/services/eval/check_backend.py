"""백엔드 API 상태 확인 스크립트"""
import asyncio
import os
import sys

_this_dir = os.path.dirname(os.path.abspath(__file__))
_ai_app_dir = os.path.abspath(os.path.join(_this_dir, "..", ".."))
if _ai_app_dir not in sys.path:
    sys.path.insert(0, _ai_app_dir)

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import httpx


async def check():
    base_url = os.getenv("BACKEND_API_URL", "").rstrip("/")
    api_key = os.getenv("INTERNAL_API_KEY", "")
    api_key_header = os.getenv("INTERNAL_API_KEY_HEADER", "X-Internal-Api-Key")

    print(f"BACKEND_API_URL: {base_url}")
    print(f"API_KEY_HEADER: {api_key_header}")
    print(f"API_KEY 길이: {len(api_key)}")
    print()

    async with httpx.AsyncClient(timeout=10.0) as client:
        headers = {api_key_header: api_key}

        # 1. 멘토 목록 (v1)
        print("--- 1. GET /api/v1/experts (멘토 목록) ---")
        try:
            resp = await client.get(f"{base_url}/api/v1/experts", params={"size": 1})
            print(f"  Status: {resp.status_code}")
            if resp.status_code == 200:
                data = resp.json().get("data", {})
                experts = data.get("experts", [])
                if experts:
                    e = experts[0]
                    print(f"  샘플 멘토 키: {list(e.keys())}")
                    print(f"  user_id: {e.get('user_id') or e.get('id')}")
                else:
                    print(f"  응답 data 키: {list(data.keys())}")
            else:
                print(f"  응답: {resp.text[:200]}")
        except Exception as e:
            print(f"  실패: {e}")

        # 2. 멘토 상세 (v1)
        print("\n--- 2. GET /api/v1/experts/{id} (멘토 상세) ---")
        try:
            # 먼저 id를 가져와서
            resp = await client.get(f"{base_url}/api/v1/experts", params={"size": 1})
            if resp.status_code == 200:
                experts = resp.json().get("data", {}).get("experts", [])
                if experts:
                    uid = experts[0].get("user_id") or experts[0].get("id")
                    resp2 = await client.get(f"{base_url}/api/v1/experts/{uid}")
                    print(f"  Status: {resp2.status_code}")
                    if resp2.status_code == 200:
                        detail = resp2.json().get("data", {})
                        print(f"  키: {list(detail.keys())}")
                        print(f"  jobs: {detail.get('jobs', [])[:2]}")
                        print(f"  skills: {detail.get('skills', [])[:3]}")
                        intro = detail.get('introduction', '')
                        print(f"  introduction: {intro[:100]}..." if intro else "  introduction: (없음)")
                    else:
                        print(f"  응답: {resp2.text[:200]}")
        except Exception as e:
            print(f"  실패: {e}")

        # 3. 피드백 배치 저장 API (internal)
        print("\n--- 3. POST /api/internal/expert-feedbacks/batch (피드백 배치 저장) ---")
        try:
            resp = await client.post(
                f"{base_url}/api/internal/expert-feedbacks/batch",
                json={"feedbacks": []},
                headers=headers,
            )
            print(f"  Status: {resp.status_code}")
            print(f"  응답: {resp.text[:200]}")
        except Exception as e:
            print(f"  실패: {e}")

        # 4. 채팅 메시지 조회 (DB 직접)
        print("\n--- 4. DB 직접 조회: chat_messages (채팅 조회) ---")
        try:
            import asyncpg
            db_url = os.getenv("DATABASE_URL", "")
            pool = await asyncpg.create_pool(dsn=db_url, min_size=1, max_size=2)
            async with pool.acquire() as conn:
                count = await conn.fetchval("SELECT count(*) FROM chat_messages")
                room_count = await conn.fetchval("SELECT count(*) FROM chat_rooms WHERE status = 'CLOSED'")
            await pool.close()
            print(f"  chat_messages: {count}건")
            print(f"  종료된 채팅방: {room_count}건")
        except Exception as e:
            print(f"  실패: {e}")

        # 5. 피드백 개별 저장 (internal)
        print("\n--- 5. POST /api/internal/expert-feedbacks (피드백 개별 저장) ---")
        try:
            resp = await client.post(
                f"{base_url}/api/internal/expert-feedbacks",
                json={
                    "mentor_id": 0,
                    "question": "test",
                    "answer": "test",
                    "job_tag": "common",
                    "question_type": "career_advice",
                    "source_type": "seed",
                    "quality_score": 1,
                },
                headers=headers,
            )
            print(f"  Status: {resp.status_code}")
            print(f"  응답: {resp.text[:200]}")
        except Exception as e:
            print(f"  실패: {e}")


asyncio.run(check())
