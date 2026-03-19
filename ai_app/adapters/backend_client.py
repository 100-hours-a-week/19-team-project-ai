"""백엔드 API 클라이언트 — 임베딩 저장, 유저 프로필, 멘토 목록 조회"""

import logging
import os
import traceback
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

import httpx
from opentelemetry import trace

from adapters.db_client import get_vector_search_client

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

# 기본 타임아웃 (초) - 서버 행 방지를 위해 기존 30초에서 10초로 단축
DEFAULT_TIMEOUT = 10.0


class BackendAPIClient:
    """백엔드 REST API 호출 어댑터"""

    def __init__(self, base_url: Optional[str] = None):
        raw_url = base_url or os.getenv("BACKEND_API_URL", "http://localhost:8080/")
        # 후행 슬래시 제거
        self.root_url = raw_url.strip().rstrip("/")
        # 기존 v1 경로 (하위 호환성 유지)
        self.v1_url = f"{self.root_url}/api/v1"
        # 내부 관리용 경로
        self.internal_url = f"{self.root_url}/api/internal"

        self.api_key = os.getenv("INTERNAL_API_KEY", "")
        self.api_key_header = os.getenv("INTERNAL_API_KEY_HEADER", "X-Internal-Api-Key")

        # Persistent client
        self.client = httpx.AsyncClient(timeout=DEFAULT_TIMEOUT)

        logger.info(f"✅ BackendAPIClient 초기화: root_url={self.root_url}")
        logger.info(f"🔑 INTERNAL_API_KEY 로드됨: len={len(self.api_key)}, header={self.api_key_header}")
        if self.api_key:
            logger.info(f"🔑 INTERNAL_API_KEY 확인 (앞뒤 3글자): {self.api_key[:3]}...{self.api_key[-3:]}")
        else:
            logger.warning("⚠️ INTERNAL_API_KEY가 로드되지 않았습니다!")

    async def aclose(self):
        """클라이언트 종료"""
        await self.client.aclose()

    def _get_internal_headers(self) -> dict[str, str]:
        """내부 API 호출을 위한 인증 헤더"""
        return {self.api_key_header: self.api_key}

    # ---------- 유저 프로필 ----------

    async def get_user_profile(self, user_id: int) -> Optional[dict]:
        """
        잡시커(일반 유저) 프로필 조회

        Returns:
            {"introduction": str, "skills": [str], "jobs": [str]} 또는 None
        """
        url = f"{self.internal_url}/users/{user_id}"
        headers = self._get_internal_headers()
        try:
            with tracer.start_as_current_span("backend_get_user_profile"):
                resp = await self.client.get(url, headers=headers)
                resp.raise_for_status()

            data = resp.json().get("data", {})
            return {
                "introduction": data.get("introduction", ""),
                "skills": data.get("skills", []),
                "jobs": data.get("jobs", []),
            }
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            if e.response.status_code == 403:
                # 403 Forbidden은 보통 '탈퇴한 사용자(USER_DELETED)'인 경우 발생함
                try:
                    error_data = e.response.json()
                    if error_data.get("code") == "USER_DELETED":
                        logger.warning(f"⚠️ 탈퇴한 사용자 프로필 조회 ({user_id}): {error_data.get('message')}")
                        return None
                except Exception:
                    pass
                logger.error(f"❌ 권한 오류 (403): 접근 권한이 없거나 금지된 요청입니다. URL: {url}")
            elif e.response.status_code == 401:
                logger.error(f"❌ 인증 오류 (401): API 키가 올바르지 않거나 만료되었습니다. URL: {url}")
            else:
                logger.error(f"유저 프로필 조회 실패 ({user_id}): {e}")
            raise
        except Exception as e:
            logger.error(f"유저 프로필 조회 오류 ({user_id}): {e}")
            raise

    # ---------- 임베딩 저장 ----------

    async def save_embedding(self, user_id: int, embedding: List[float]) -> bool:
        """멘토 임베딩을 백엔드에 저장 (POST /api/v1/experts/embeddings)"""
        url = f"{self.internal_url}/experts/embeddings"
        payload = {"user_id": user_id, "embedding": embedding}
        headers = self._get_internal_headers()

        try:
            resp = await self.client.post(url, json=payload, headers=headers)
            resp.raise_for_status()

            logger.debug(f"임베딩 저장 완료: user_id={user_id}")
            return True
        except Exception as e:
            logger.error(f"임베딩 저장 실패 ({user_id}): {e}")
            return False

    async def get_expert_details(self, user_id: int) -> Optional[dict[str, Any]]:
        """특정 현직자의 상세 정보 조회 (nickname, company_name 등)"""
        url = f"{self.v1_url}/experts/{user_id}"
        try:
            with tracer.start_as_current_span("backend_get_expert_details"):
                resp = await self.client.get(url)
                resp.raise_for_status()  # Ensure non-2xx responses raise an error
                if resp.status_code == 200:
                    data = resp.json().get("data", {})
                    # user_id 필드가 없고 id만 있는 경우 보정
                    if data and "user_id" not in data and "id" in data:
                        data["user_id"] = data["id"]
                    return data
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            logger.error(f"현직자 상세 조회 실패 ({user_id}): {e}")
            return None
        except Exception as e:
            logger.error(f"현직자 상세 조회 오류 ({user_id}): {e}")
            logger.error(traceback.format_exc())
            return None

    # ---------- 멘토 목록 ----------

    async def get_experts_page(
        self, cursor: Optional[str] = None, size: int = 100
    ) -> Tuple[List[Dict[str, Any]], Optional[str], bool]:
        """멘토 목록 한 페이지 조회 (Pagination)"""
        url = f"{self.v1_url}/experts"
        params: dict[str, Any] = {"size": size}
        if cursor:
            params["cursor"] = cursor

        try:
            resp = await self.client.get(url, params=params)
            resp.raise_for_status()

            data = resp.json().get("data", {})
            experts = data.get("experts", [])
            next_cursor = data.get("next_cursor")
            has_more = data.get("has_more", False)

            return experts, next_cursor, has_more
        except Exception as e:
            logger.error(f"멘토 페이지 조회 실패 (cursor={cursor}): {e}")
            raise

    async def get_experts(self) -> list[dict[str, Any]]:
        """전체 멘토 목록 조회 (전체 데이터 포함 - 소규모용)"""
        all_experts: list[dict[str, Any]] = []
        cursor: str | None = None

        try:
            while True:
                experts, cursor, has_more = await self.get_experts_page(cursor)
                all_experts.extend(experts)
                if not has_more:
                    break

            logger.info(f"전체 멘토 {len(all_experts)}명 조회 완료")
            return all_experts
        except Exception:
            raise

    async def get_expert_ids(self) -> list[int]:
        """전체 멘토 user_id 목록 조회"""
        experts = await self.get_experts()
        return [e["user_id"] for e in experts]

    async def search_experts(
        self,
        query_embedding: list[float],
        top_n: int = 50,
    ) -> list[dict[str, Any]]:
        """
        벡터 검색을 수행하고 멘토 상세 정보를 결합하여 반환한다.
        """
        # 1. 벡터 검색 (ID와 점수 가져오기)
        v_client = get_vector_search_client()
        search_results = await v_client.search_similar_experts(
            query_embedding=query_embedding,
            top_n=top_n,
        )

        if not search_results:
            return []

        # 2. 상세 정보 결합 (병렬 처리 - 서버 부하 방지를 위해 3개로 제한)
        import asyncio

        semaphore = asyncio.Semaphore(3)

        async def _fetch_details(uid, score):
            async with semaphore:
                details = await self.get_expert_details(uid)
                if details:
                    return {**details, "similarity_score": score}
                return None

        tasks = [_fetch_details(sr["user_id"], sr["similarity_score"]) for sr in search_results]
        results = await asyncio.gather(*tasks)

        # None (조회 실패) 제거
        return [r for r in results if r]

    # ---------- 피드백 저장 ----------

    async def save_feedbacks_batch(self, feedbacks: List[Dict[str, Any]]) -> int:
        """
        피드백 일괄 저장

        Args:
            feedbacks: 피드백 dict 리스트

        Returns:
            저장된 건수
        """
        url = f"{self.internal_url}/expert-feedbacks/batch"
        payload = {"feedbacks": feedbacks}
        headers = self._get_internal_headers()

        try:
            resp = await self.client.post(url, json=payload, headers=headers)
            resp.raise_for_status()

            data = resp.json().get("data", {})
            inserted = data.get("inserted_count", 0)
            logger.info(f"피드백 일괄 저장 완료: {inserted}건")
            return inserted
        except Exception as e:
            logger.error(f"피드백 일괄 저장 실패: {e}")
            raise

    # ---------- 유저 존재 확인 ----------

    async def user_exists(self, user_id: int) -> bool:
        """유저 존재 여부 확인"""
        try:
            profile = await self.get_user_profile(user_id)
            return profile is not None
        except Exception as e:
            logger.warning(f"유저 존재 여부 확인 실패 ({user_id}): {e}")
            return True  # 에러 시 존재한다고 가정 (추천 로직 진행)


@lru_cache(maxsize=1)
def get_backend_client() -> BackendAPIClient:
    """BackendAPIClient 싱글톤"""
    return BackendAPIClient()
