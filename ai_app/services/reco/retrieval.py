"""멘토 검색 모듈 - 필터링 + 임베딩 유사도 기반 추천"""

import logging
from dataclasses import dataclass
from typing import Any

from adapters.backend_client import BackendAPIClient, get_backend_client
from adapters.db_client import VectorSearchClient, get_vector_search_client
from opentelemetry import trace

from services.reco.embedder import ProfileEmbedder, get_embedder

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

# 필터링 fallback 임계값
MIN_CANDIDATES_FOR_JOB_FILTER = 5


@dataclass
class MentorCandidate:
    """멘토 후보 데이터"""

    user_id: int
    nickname: str
    introduction: str
    company_name: str | None
    verified: bool
    rating_avg: float
    rating_count: int
    response_rate: float
    skills: list[str]
    jobs: list[str]
    similarity_score: float
    last_active_at: str | None
    filter_type: str | None = None
    ground_truth: dict | None = None
    # 내부 필터링용
    _job_matched: bool = False
    _skill_matched: bool = False

    def to_dict(self, include_internal: bool = False) -> dict[str, Any]:
        """딕셔너리로 변환"""
        result = {
            "user_id": self.user_id,
            "nickname": self.nickname,
            "company_name": self.company_name,
            "verified": self.verified,
            "rating_avg": self.rating_avg,
            "rating_count": self.rating_count,
            "response_rate": self.response_rate,
            "skills": self.skills,
            "jobs": self.jobs,
            "introduction": self.introduction,
            "similarity_score": self.similarity_score,
            "filter_type": self.filter_type,
            "ground_truth": self.ground_truth,
            "last_active_at": self.last_active_at,
        }
        if include_internal:
            result["_job_matched"] = self._job_matched
            result["_skill_matched"] = self._skill_matched
        return result


class MentorRetriever:
    """멘토 검색 - 하이브리드 스코어 활용"""

    def __init__(
        self,
        backend_client: BackendAPIClient | None = None,
        embedder: ProfileEmbedder | None = None,
        vector_search_client: VectorSearchClient | None = None,
    ):
        self.backend_client = backend_client or get_backend_client()
        self.embedder = embedder or get_embedder()
        self.vector_search_client = vector_search_client or get_vector_search_client()

    async def get_user_profile(self, user_id: int) -> dict | None:
        """사용자 프로필 정보 조회 (skills, jobs, introduction)"""
        return await self.backend_client.get_user_profile(user_id)

    async def get_user_profile_text(self, user_id: int) -> str | None:
        """사용자 프로필 텍스트 생성"""
        profile = await self.backend_client.get_user_profile(user_id)
        return self._build_profile_text(profile)

    def _build_profile_text(self, profile: dict[str, Any] | None) -> str | None:
        """프로필 데이터를 검색용 텍스트로 변환"""
        if not profile:
            return None

        # skills, jobs 데이터 정제 (딕셔너리 형태 등 처리)
        skills = self._to_set(profile.get("skills", []))
        jobs = self._to_set(profile.get("jobs", []))
        introduction = profile.get("introduction", "")

        parts = []
        if jobs:
            parts.append(f"직무: {', '.join(jobs)}")
        if skills:
            parts.append(f"기술스택: {', '.join(skills)}")
        if introduction:
            parts.append(f"자기소개: {introduction}")

        return ". ".join(parts) if parts else None

    def _to_set(self, items: Any) -> set[str]:
        """리스트 내부의 딕셔너리나 문자열을 문자열 집합으로 변환"""
        if not items:
            return set()
        result = set()
        for item in items:
            if isinstance(item, dict):
                # 딕셔너리인 경우 "name" 필드가 있으면 사용, 없으면 전체를 문자열로 변환
                name = item.get("name") or item.get("job_name") or item.get("skill_name")
                result.add(str(name) if name else str(item))
            else:
                result.add(str(item))
        return result

    # ========== 헬퍼 메서드 ==========

    def _candidate_to_mentor(
        self,
        cand: dict[str, Any],
        user_skills: set[str],
        user_jobs: set[str],
    ) -> MentorCandidate:
        """API 응답 dict를 MentorCandidate로 변환"""
        # 필드 매핑 (백엔드 API 버전에 따른 차이 보정)
        user_id = cand.get("user_id") or cand.get("id")
        if user_id is None:
            logger.warning(f"멘토 데이터에 user_id가 없습니다: {cand}")
            user_id = 0

        mentor_skills = self._to_set(cand.get("skills", []))
        mentor_jobs = self._to_set(cand.get("jobs", []))

        # 평점 및 응답률 처리 (기본값 및 안전한 반올림)
        rating_avg = cand.get("rating_avg")
        if rating_avg is None:
            rating_avg = cand.get("rating_count_avg", 0.0)  # 백엔드 필드명 가능성 대응

        response_rate = 0.0
        responded = cand.get("responded_request_count", 0)
        accepted = cand.get("accepted_request_count", 0)
        if responded and responded > 0:
            response_rate = (accepted / responded) * 100

        last_active = cand.get("last_active_at")
        if last_active and hasattr(last_active, "isoformat"):
            last_active = last_active.isoformat()

        return MentorCandidate(
            user_id=int(user_id),
            nickname=cand.get("nickname") or cand.get("name") or "이름 없음",
            introduction=cand.get("introduction", ""),
            company_name=cand.get("company_name") or cand.get("organization"),
            verified=cand.get("verified", False),
            rating_avg=round(float(rating_avg), 1),
            rating_count=cand.get("rating_count", 0),
            response_rate=round(float(response_rate), 1),
            skills=list(mentor_skills),
            jobs=list(mentor_jobs),
            similarity_score=round(float(cand.get("similarity_score", 0.0)), 4),
            last_active_at=last_active if isinstance(last_active, str) else None,
            _job_matched=bool(user_jobs & mentor_jobs),
            _skill_matched=bool(user_skills & mentor_skills),
        )

    def _filter_candidates(
        self,
        candidates: list[MentorCandidate],
        top_k: int,
    ) -> list[MentorCandidate]:
        """후보 필터링 (직무 우선, 기술스택 fallback, 응답률 fallback)

        Args:
            candidates: 전체 후보 리스트 (임베딩 유사도순으로 정렬됨)
            top_k: 반환할 최대 개수

        Returns:
            필터링된 후보 리스트
        """
        # 1차 필터링: 직무 일치
        job_filtered = [c for c in candidates if c._job_matched]

        # 2차 필터링: 직무 결과가 5개 이하면 기술스택으로 확장
        if len(job_filtered) <= MIN_CANDIDATES_FOR_JOB_FILTER:
            skill_filtered = [c for c in candidates if c._skill_matched]

            # 직무 일치 우선
            for c in job_filtered:
                c.filter_type = "job"
            for c in skill_filtered:
                if c.filter_type is None:
                    c.filter_type = "skill"

            # 직무 일치 먼저, 기술스택 일치 그 다음
            job_filtered_set = set(c.user_id for c in job_filtered)
            filtered = job_filtered + [c for c in skill_filtered if c.user_id not in job_filtered_set]
        else:
            for c in job_filtered:
                c.filter_type = "job"
            filtered = job_filtered

        # 3차 필터링: 결과가 부족할 경우 응답률 높은 순으로 확장 (Fallback)
        if len(filtered) < top_k:
            filtered_set = set(c.user_id for c in filtered)

            # 이미 포함된 멘토 제외한 나머지를 응답률 순으로 정렬
            fallback_candidates = [c for c in candidates if c.user_id not in filtered_set]

            # 응답률(response_rate) 내림차순, 그다음 유사도 순
            fallback_candidates.sort(key=lambda x: (x.response_rate, x.similarity_score), reverse=True)

            for c in fallback_candidates:
                c.filter_type = "response_rate"
                filtered.append(c)
                if len(filtered) >= top_k:
                    break

        return filtered[:top_k]

    async def verify_mentor_ground_truth(
        self,
        mentor_user_id: int,
        top_k: int = 3,
    ) -> dict[str, Any]:
        """
        개별 멘토에 대한 Silver Ground Truth 검증

        멘토 프로필을 잡시커로 변환 → 추천 실행 → 자기 자신이 Top-K에 있는지 확인

        Returns:
            {"is_hit": bool, "rank": int | None}
        """
        # 멘토 상세 정보 조회 (현직자 API 사용)
        profile = await self.backend_client.get_expert_details(mentor_user_id)
        if not profile:
            return {"is_hit": False, "rank": None}

        parts = []
        if profile["jobs"]:
            parts.append(f"직무: {', '.join(profile['jobs'])}")
        if profile["skills"]:
            parts.append(f"기술스택: {', '.join(profile['skills'])}")
        if profile["introduction"]:
            parts.append(f"자기소개: {profile['introduction']}")

        if not parts:
            return {"is_hit": False, "rank": None}

        jobseeker_text = ". ".join(parts)

        # 임베딩 생성 및 검색
        query_embedding = self.embedder.embed_text(jobseeker_text)
        embedding_list = query_embedding.tolist()

        candidates = await self.vector_search_client.search_similar_experts(
            query_embedding=embedding_list,
            top_n=top_k,
        )

        recommended_ids = [c["user_id"] for c in candidates]

        is_hit = mentor_user_id in recommended_ids
        rank = recommended_ids.index(mentor_user_id) + 1 if is_hit else None

        return {"is_hit": is_hit, "rank": rank}

    async def recommend_mentors(
        self,
        user_id: int,
        top_k: int = 3,
        only_verified: bool = False,
        include_gt: bool = False,
    ) -> list[dict[str, Any]]:
        """
        필터링 + 임베딩 유사도 기반 멘토 추천

        1차: 직무 일치 필터링
        2차: 직무 일치 결과가 5개 이하면 기술스택 하나 이상 일치로 확장
        정렬: 임베딩 유사도

        Args:
            user_id: 추천 대상 사용자 ID
            top_k: 추천할 멘토 수
            only_verified: 인증된 멘토만 추천할지 여부
            include_gt: 각 멘토에 대한 Ground Truth 검증 포함 여부

        Returns:
            추천 결과 리스트 (멘토 정보 + 임베딩 유사도)
        """
        # 1) 사용자 프로필 조회
        try:
            with tracer.start_as_current_span("get_user_profile"):
                user_profile = await self.get_user_profile(user_id)
        except Exception as e:
            logger.warning(f"유저 프로필 조회 실패 (user_id={user_id}): {e} → fallback 전환")
            return []

        if not user_profile:
            logger.warning(f"User {user_id} not found")
            return []

        user_skills = self._to_set(user_profile.get("skills", []))
        user_jobs = self._to_set(user_profile.get("jobs", []))
        introduction = user_profile.get("introduction", "")

        # 2) 프로필 텍스트 생성 (임베딩용)
        profile_text = await self.get_user_profile_text(user_id)
        if not profile_text:
            logger.warning(
                f"User {user_id} has insufficient profile data "
                f"(jobs: {len(user_jobs)}, skills: {len(user_skills)}, intro: {bool(introduction)})"
            )
            return []

        # 3) 임베딩 생성
        with tracer.start_as_current_span("embed_user_profile"):
            user_embedding = self.embedder.embed_text(profile_text, is_query=True)
            embedding_list = user_embedding.tolist()

        # 4) 벡터 유사도 검색 (직접 DB)
        candidate_limit = max(top_k * 5, 30)

        with tracer.start_as_current_span("vector_search_db"):
            search_results = await self.vector_search_client.search_similar_experts(
                query_embedding=embedding_list,
                top_n=candidate_limit,
                exclude_user_id=user_id,
            )

        # [추가] 검색 결과가 전혀 없는 경우, DB 임베딩 상태 확인
        if not search_results:
            status = await self.vector_search_client.get_embedding_status()
            if status["total_count"] > 0 and status["embedded_count"] < status["total_count"]:
                missing = status["total_count"] - status["embedded_count"]
                logger.warning(
                    f"🚨 DB에 전문가 {status['total_count']}명 중 {missing}명의 임베딩이 누락되었습니다. 자동 업데이트가 필요합니다."
                )
                # 이 정보는 상위 컨트롤러에서 사용하여 Background Task를 트리거할 수 있음
                # 하지만 retrieval 수준에서는 로깅과 결과 없음 반환에 집중
            elif status["total_count"] == 0:
                logger.warning("🚨 DB에 전문가 데이터가 전혀 없습니다.")

        # 5) 검색 결과에 멘토 상세 정보 결합 (병렬로 상위 후보들의 정보만 가져옴)
        import asyncio

        experts_map = {}
        semaphore = asyncio.Semaphore(10)  # 10개 병렬

        async def _fetch_expert(uid):
            async with semaphore:
                details = await self.backend_client.get_expert_details(uid)
                return uid, details

        fetch_tasks = [_fetch_expert(sr["user_id"]) for sr in search_results]

        with tracer.start_as_current_span("fetch_expert_details_batch"):
            try:
                fetch_results = await asyncio.gather(*fetch_tasks)
                experts_map = {uid: details for uid, details in fetch_results if details}
            except Exception as e:
                logger.warning(f"멘토 상세 정보 취합 실패: {e}")

        raw_candidates = []
        for sr in search_results:
            uid = sr["user_id"]
            expert_data = experts_map.get(uid, {})
            raw_candidates.append(
                {
                    **expert_data,
                    "user_id": uid,
                    "similarity_score": sr["similarity_score"],
                }
            )

        # 6) 후보 데이터 변환
        all_candidates = [self._candidate_to_mentor(c, user_skills, user_jobs) for c in raw_candidates]

        # 7) 필터링 및 Top-K 선택
        top_candidates = self._filter_candidates(all_candidates, top_k)

        # Ground Truth 검증 (옵션)
        if include_gt:
            for candidate in top_candidates:
                gt_result = await self.verify_mentor_ground_truth(
                    mentor_user_id=candidate.user_id,
                    top_k=top_k,
                )
                candidate.ground_truth = gt_result

        # 딕셔너리로 변환하여 반환
        return [c.to_dict() for c in top_candidates]

    async def fallback_by_response_rate(
        self,
        top_k: int = 3,
    ) -> list[dict[str, Any]]:
        """
        Fallback: 유사도 추천 실패 시 응답률 높은 순으로 멘토 반환

        유저 프로필 조회 불가(401 등) 또는 벡터 검색 결과가 없을 때 사용
        GET /api/v1/experts 로 전체 멘토 목록을 가져와서 응답률 순으로 정렬
        """
        try:
            raw_experts = await self.backend_client.get_experts()

            if not raw_experts:
                logger.warning("Fallback: 멘토 후보가 없습니다")
                return []

            # MentorCandidate로 변환 (유저 스킬/잡 없이)
            candidates = []
            for c in raw_experts:
                try:
                    candidates.append(self._candidate_to_mentor(c, user_skills=set(), user_jobs=set()))
                except Exception as e:
                    logger.warning(f"멘토 변환 실패 (user_id={c.get('user_id')}): {e}")
                    continue

            # 응답률 내림차순 → 평점 내림차순 정렬
            candidates.sort(
                key=lambda x: (x.response_rate, x.rating_avg),
                reverse=True,
            )

            for c in candidates:
                c.filter_type = "fallback_response_rate"

            top = candidates[:top_k]
            logger.info(
                f"Fallback 완료: 응답률 기반 {len(top)}명 추천 "
                f"(top response_rate={top[0].response_rate if top else 0}%)"
            )
            return [c.to_dict() for c in top]

        except Exception as e:
            logger.error(f"Fallback 실패: {e}")
            return []

    async def recommend_experts(
        self,
        query_text: str,
        top_k: int = 5,
        only_verified: bool = False,
    ) -> list[dict[str, Any]]:
        """
        텍스트 쿼리로 직접 멘토 검색 (로컬 DB 기반)
        """
        query_embedding = self.embedder.embed_text(query_text, is_query=True)
        embedding_list = query_embedding.tolist()

        # 로컬 DB에서 유사도 검색 수행
        experts = await self.vector_search_client.search_similar_experts(
            query_embedding=embedding_list,
            top_n=top_k,
        )

        return [
            {
                "user_id": e["user_id"],
                "nickname": f"Mentor {e['user_id']}",
                "similarity_score": round(float(e["similarity_score"]), 4),
            }
            for e in experts
        ]

    async def update_expert_embedding(self, user_id: int) -> bool:
        """특정 멘토의 임베딩 업데이트 (백엔드 API를 통해 저장)"""
        # 멘토 상세 정보 조회 (현직자 API 사용)
        expert_details = await self.backend_client.get_expert_details(user_id)
        if not expert_details:
            logger.warning(f"Mentor {user_id} not found to embed")
            return False

        profile_text = self._build_profile_text(expert_details)
        if not profile_text:
            logger.warning(f"Mentor {user_id} has no profile data to embed")
            return False

        embedding = self.embedder.embed_text(profile_text, is_query=False)
        embedding_list = embedding.tolist()

        # 백엔드 API를 통해 저장 (백엔드에서 DB 업데이트 처리)
        try:
            success = await self.backend_client.save_embedding(user_id, embedding_list)
            if success:
                logger.info(f"Updated embedding for mentor {user_id} via backend API")
            return success
        except Exception as e:
            logger.error(f"Failed to save embedding to backend for user {user_id}: {e}")
            return False

    async def compute_embedding(self, user_id: int) -> dict[str, Any] | None:
        """
        사용자 프로필 임베딩 계산

        Args:
            user_id: 사용자 ID

        Returns:
            {"user_id": int, "embedding": list[float]} or None
        """
        profile_text = await self.get_user_profile_text(user_id)
        if not profile_text:
            logger.warning(f"User {user_id} has no profile text")
            return None

        embedding = self.embedder.embed_text(profile_text, is_query=False)
        embedding_list = embedding.tolist()

        logger.debug(f"Computed embedding for user {user_id}, dim={len(embedding_list)}")

        return {
            "user_id": user_id,
            "embedding": embedding_list,
        }

    async def update_all_expert_embeddings(self) -> int:
        """
        모든 멘토 임베딩 일괄 업데이트 (Batch 처리 최적화)
        - 1단계: 백엔드 API에서 멘토 목록을 페이지 단위(Pagination)로 가져옴
        - 2단계: 가져온 페이지 내의 모든 프로필 텍스트를 한꺼번에 임베딩 (embed_texts)
        - 3단계: 백엔드 API를 통해 일괄 업데이트 요청
        """
        import asyncio

        logger.info("🚀 시작: 멘토 임베딩 일괄 업데이트 (Batch 모드)")

        updated_total = 0
        cursor = None
        page_num = 1

        try:
            while True:
                # 진행 상황 출력 (10페이지마다)
                if page_num % 10 == 0 or page_num == 1:
                    logger.info(f"⏳ {page_num}페이지 진행 중... (현재까지 누적 업데이트: {updated_total}명)")

                # 1. 백엔드에서 전문가 목록 한 페이지만 가져오기 (배치 사이즈 증대)
                experts, cursor, has_more = await self.backend_client.get_experts_page(cursor=cursor, size=500)
                if not experts:
                    break

                # 2. 임베딩할 텍스트 리스트 준비
                valid_experts = []
                texts_to_embed = []
                for expert in experts:
                    user_id = expert.get("user_id")
                    if not user_id:
                        continue

                    profile_text = self._build_profile_text(expert)
                    if profile_text:
                        valid_experts.append(expert)
                        texts_to_embed.append(profile_text)

                if texts_to_embed:
                    # 3. 일괄 임베딩 생성 (Batch Embedding)
                    embeddings = self.embedder.embed_texts(texts_to_embed)

                    # 4. 로컬 DB 및 백엔드 저장 (병렬 처리)
                    semaphore = asyncio.Semaphore(10)

                    async def _save_task(expert_data, embedding_arr):
                        async with semaphore:
                            uid = expert_data["user_id"]
                            emb_list = embedding_arr.tolist()
                            try:
                                # 백엔드 API를 통해 저장 요청 (백엔드가 DB 업데이트 담당)
                                return await self.backend_client.save_embedding(uid, emb_list)
                            except Exception:
                                return False

                    save_tasks = [_save_task(valid_experts[i], embeddings[i]) for i in range(len(valid_experts))]

                    results = await asyncio.gather(*save_tasks)
                    page_updated = sum(1 for r in results if r)
                    updated_total += page_updated

                    logger.info(f"📦 페이지 {page_num} 완료: {page_updated}명 업데이트 (누적: {updated_total}명)")

                if not has_more:
                    break
                page_num += 1

            logger.info(f"✅ 일괄 업데이트 최종 완료: 총 {updated_total}명")
            return updated_total

        except Exception as e:
            logger.error(f"❌ 일괄 업데이트 중 심각한 오류 발생: {e}")
            return updated_total

    async def evaluate_silver_ground_truth(
        self,
        sample_size: int | None = None,
    ) -> dict[str, Any]:
        """
        Silver Ground Truth 평가

        멘토 프로필을 잡시커 프로필로 변환하여 추천 결과에
        원본 멘토가 포함되는지 검증

        평가 지표:
        - Hit Rate @ K (K=1,3,5,10): Top-K에 정답 포함 비율
        - MRR (Mean Reciprocal Rank): 정답 순위의 역수 평균

        Args:
            sample_size: 평가할 샘플 수 (None이면 전체)

        Returns:
            평가 결과 (hit_at_1/3/5/10, mrr, total, details)
        """
        # 전체 멘토 ID 가져오기
        expert_ids = await self.backend_client.get_expert_ids()

        # 실시간 요청 시 부하 방지를 위해 기본 샘플 사이즈 제한
        if sample_size is None:
            sample_size = 5

        if sample_size:
            expert_ids = expert_ids[:sample_size]

        if not expert_ids:
            return {
                "hit_at_1": 0.0,
                "hit_at_3": 0.0,
                "hit_at_5": 0.0,
                "hit_at_10": 0.0,
                "mrr": 0.0,
                "total": 0,
                "details": [],
            }

        # 각 K값에 대한 Hit 카운트
        hits = {1: 0, 3: 0, 5: 0, 10: 0}
        reciprocal_ranks = []
        details = []

        for gt_user_id in expert_ids:
            # 멘토 상세 정보 조회 (현직자 API 사용)
            profile = await self.backend_client.get_expert_details(gt_user_id)
            if not profile:
                continue

            parts = []
            if profile["jobs"]:
                parts.append(f"직무: {', '.join(profile['jobs'])}")
            if profile["skills"]:
                parts.append(f"기술스택: {', '.join(profile['skills'])}")
            if profile["introduction"]:
                parts.append(f"자기소개: {profile['introduction']}")

            if not parts:
                continue

            jobseeker_text = ". ".join(parts)

            # 임베딩 생성 및 Top-10 검색
            query_embedding = self.embedder.embed_text(jobseeker_text)
            embedding_list = query_embedding.tolist()

            candidates = await self.vector_search_client.search_similar_experts(
                query_embedding=embedding_list,
                top_n=10,
            )

            recommended_ids = [c["user_id"] for c in candidates]

            # Hit 판정 및 순위 확인
            if gt_user_id in recommended_ids:
                rank = recommended_ids.index(gt_user_id) + 1
                reciprocal_ranks.append(1.0 / rank)

                # 각 K에 대해 Hit 카운트
                for k in [1, 3, 5, 10]:
                    if rank <= k:
                        hits[k] += 1
            else:
                rank = None
                reciprocal_ranks.append(0.0)

            details.append(
                {
                    "gt_user_id": gt_user_id,
                    "is_hit": rank is not None,
                    "rank": rank,
                    "recommended_ids": recommended_ids,
                }
            )

        total = len(reciprocal_ranks)

        # Hit Rate @ K 계산
        hit_at_1 = (hits[1] / total * 100) if total > 0 else 0.0
        hit_at_3 = (hits[3] / total * 100) if total > 0 else 0.0
        hit_at_5 = (hits[5] / total * 100) if total > 0 else 0.0
        hit_at_10 = (hits[10] / total * 100) if total > 0 else 0.0

        # MRR 계산
        mrr = sum(reciprocal_ranks) / total if total > 0 else 0.0

        return {
            "hit_at_1": round(hit_at_1, 2),
            "hit_at_3": round(hit_at_3, 2),
            "hit_at_5": round(hit_at_5, 2),
            "hit_at_10": round(hit_at_10, 2),
            "mrr": round(mrr, 4),
            "total": total,
            "details": details,
        }
