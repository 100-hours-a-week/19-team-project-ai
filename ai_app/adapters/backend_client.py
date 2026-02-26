"""백엔드 API 클라이언트 — 임베딩 저장, 유저 프로필, 멘토 목록 조회"""

import logging
import os
from functools import lru_cache
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

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

        logger.info(f"✅ BackendAPIClient 초기화: root_url={self.root_url}")
        logger.info(f"🔑 INTERNAL_API_KEY 로드됨: len={len(self.api_key)}, header={self.api_key_header}")
        if self.api_key:
            logger.info(f"🔑 INTERNAL_API_KEY 확인 (앞뒤 3글자): {self.api_key[:3]}...{self.api_key[-3:]}")
        else:
            logger.warning("⚠️ INTERNAL_API_KEY가 로드되지 않았습니다!")

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
            async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
                resp = await client.get(url, headers=headers)
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
            if e.response.status_code == 401:
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
            async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()

            logger.debug(f"임베딩 저장 완료: user_id={user_id}")
            return True
        except Exception as e:
            logger.error(f"임베딩 저장 실패 ({user_id}): {e}")
            return False
    async def get_expert_details(self, user_id: int) -> Optional[dict[str, Any]]:
        """특정 전문가의 상세 정보 조회 (nickname, company_name 등)"""
        url = f"{self.v1_url}/experts/{user_id}"
        try:
            async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
                resp = await client.get(url)
                resp.raise_for_status()
            
            return resp.json().get("data")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            logger.error(f"전문가 상세 조회 실패 ({user_id}): {e}")
            return None
        except Exception as e:
            logger.error(f"전문가 상세 조회 오류 ({user_id}): {e}")
            return None

    # ---------- 멘토 목록 ----------

    async def get_experts_page(self, cursor: str | None = None, size: int = 100) -> tuple[list[dict[str, Any]], str | None, bool]:
        """멘토 목록 한 페이지 조회 (Pagination)"""
        url = f"{self.v1_url}/experts"
        params: dict[str, Any] = {"size": size}
        if cursor:
            params["cursor"] = cursor

        try:
            async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
                resp = await client.get(url, params=params)
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

    # ---------- 유저 존재 확인 ----------

    async def user_exists(self, user_id: int) -> bool:
        """유저 존재 여부 확인"""
        profile = await self.get_user_profile(user_id)
        return profile is not None


@lru_cache(maxsize=1)
def get_backend_client() -> BackendAPIClient:
    """BackendAPIClient 싱글톤"""
    return BackendAPIClient()
