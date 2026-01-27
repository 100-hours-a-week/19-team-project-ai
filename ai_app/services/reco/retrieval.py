"""멘토 검색 모듈 - 필터링 + 임베딩 유사도 기반 추천"""

import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from services.reco.embedder import ProfileEmbedder, get_embedder

logger = logging.getLogger(__name__)

# 필터링 fallback 임계값
MIN_CANDIDATES_FOR_JOB_FILTER = 5


class MentorRetriever:
    """멘토 검색 - 하이브리드 스코어 활용"""

    def __init__(
        self,
        conn: Connection,
        embedder: ProfileEmbedder | None = None,
    ):
        self.conn = conn
        self.embedder = embedder or get_embedder()

    def get_user_profile(self, user_id: int) -> dict | None:
        """사용자 프로필 정보 조회 (skills, jobs, introduction)"""
        query = text("""
            SELECT
                u.introduction,
                ARRAY_AGG(DISTINCT s.name) FILTER (WHERE s.name IS NOT NULL) as skills,
                ARRAY_AGG(DISTINCT j.name) FILTER (WHERE j.name IS NOT NULL) as jobs
            FROM users u
            LEFT JOIN user_skills us ON u.id = us.user_id
            LEFT JOIN skills s ON us.skill_id = s.id
            LEFT JOIN user_jobs uj ON u.id = uj.user_id
            LEFT JOIN jobs j ON uj.job_id = j.id
            WHERE u.id = :user_id
            GROUP BY u.id, u.introduction
        """)

        result = self.conn.execute(query, {"user_id": user_id}).fetchone()
        if not result:
            return None

        return {
            "introduction": result.introduction or "",
            "skills": result.skills or [],
            "jobs": result.jobs or [],
        }

    def get_user_profile_text(self, user_id: int) -> str | None:
        """사용자 프로필 텍스트 생성"""
        query = text("""
            SELECT
                u.introduction,
                ARRAY_AGG(DISTINCT s.name) FILTER (WHERE s.name IS NOT NULL) as skills,
                ARRAY_AGG(DISTINCT j.name) FILTER (WHERE j.name IS NOT NULL) as jobs
            FROM users u
            LEFT JOIN user_skills us ON u.id = us.user_id
            LEFT JOIN skills s ON us.skill_id = s.id
            LEFT JOIN user_jobs uj ON u.id = uj.user_id
            LEFT JOIN jobs j ON uj.job_id = j.id
            WHERE u.id = :user_id
            GROUP BY u.id, u.introduction
        """)

        result = self.conn.execute(query, {"user_id": user_id}).fetchone()
        if not result:
            return None

        introduction = result.introduction or ""
        skills = result.skills or []
        jobs = result.jobs or []

        parts = []
        if jobs:
            parts.append(f"직무: {', '.join(jobs)}")
        if skills:
            parts.append(f"기술스택: {', '.join(skills)}")
        if introduction:
            parts.append(f"자기소개: {introduction}")

        return ". ".join(parts) if parts else None

    def verify_mentor_ground_truth(
        self,
        mentor_user_id: int,
        top_k: int = 5,
    ) -> dict[str, Any]:
        """
        개별 멘토에 대한 Silver Ground Truth 검증

        멘토 프로필을 잡시커로 변환 → 추천 실행 → 자기 자신이 Top-K에 있는지 확인

        Returns:
            {"is_hit": bool, "rank": int | None}
        """
        # 멘토 프로필 텍스트 생성 (user_id 제외)
        profile = self.get_user_profile(mentor_user_id)
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

        # 임베딩 생성 및 추천 실행
        query_embedding = self.embedder.embed_text(jobseeker_text)
        embedding_list = query_embedding.tolist()

        reco_query = text("""
            SELECT ep.user_id
            FROM expert_profiles ep
            WHERE ep.embedding IS NOT NULL
            ORDER BY ep.embedding <=> CAST(:query_embedding AS vector)
            LIMIT :top_k
        """)

        result = self.conn.execute(
            reco_query,
            {"query_embedding": str(embedding_list), "top_k": top_k},
        )

        recommended_ids = [row.user_id for row in result]

        is_hit = mentor_user_id in recommended_ids
        rank = recommended_ids.index(mentor_user_id) + 1 if is_hit else None

        return {"is_hit": is_hit, "rank": rank}

    def recommend_mentors(
        self,
        user_id: int,
        top_k: int = 5,
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
        # 사용자 프로필 조회
        user_profile = self.get_user_profile(user_id)
        if not user_profile:
            logger.warning(f"User {user_id} not found")
            return []

        user_skills = set(user_profile["skills"])
        user_jobs = set(user_profile["jobs"])

        # 프로필 텍스트 생성 (임베딩용)
        profile_text = self.get_user_profile_text(user_id)
        if not profile_text:
            return []

        # 임베딩 생성
        user_embedding = self.embedder.embed_text(profile_text)
        embedding_list = user_embedding.tolist()

        # 후보 멘토 조회 (충분한 후보 확보)
        verified_filter = "AND ep.verified = true" if only_verified else ""
        candidate_limit = max(top_k * 10, 100)

        query = text(f"""
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
            WHERE ep.user_id != :user_id
                AND ep.embedding IS NOT NULL
                {verified_filter}
            GROUP BY u.id, u.nickname, u.introduction,
                     ep.company_name, ep.verified, ep.rating_avg, ep.rating_count,
                     ep.responded_request_count, ep.accepted_request_count,
                     ep.rejected_request_count, ep.last_active_at, ep.embedding
            ORDER BY ep.embedding <=> CAST(:query_embedding AS vector)
            LIMIT :candidate_limit
        """)

        result = self.conn.execute(
            query,
            {
                "query_embedding": str(embedding_list),
                "user_id": user_id,
                "candidate_limit": candidate_limit,
            },
        )

        # 후보 데이터 변환
        all_candidates = []
        for row in result:
            mentor_skills = set(row.skills or [])
            mentor_jobs = set(row.jobs or [])
            embed_score = float(row.embedding_similarity)

            response_rate = 0.0
            if row.responded_request_count and row.responded_request_count > 0:
                response_rate = row.accepted_request_count / row.responded_request_count * 100

            # 필터 조건 미리 계산
            job_matched = bool(user_jobs & mentor_jobs)
            skill_matched = bool(user_skills & mentor_skills)

            all_candidates.append(
                {
                    "user_id": row.user_id,
                    "nickname": row.nickname,
                    "company_name": row.company_name,
                    "verified": row.verified,
                    "rating_avg": round(row.rating_avg, 1) if row.rating_avg else 0.0,
                    "rating_count": row.rating_count or 0,
                    "response_rate": round(response_rate, 1),
                    "skills": row.skills or [],
                    "jobs": row.jobs or [],
                    "introduction": row.introduction or "",
                    "similarity_score": round(embed_score, 4),
                    "filter_type": None,  # 필터링 후 설정
                    "ground_truth": None,
                    "last_active_at": row.last_active_at.isoformat() if row.last_active_at else None,
                    "_job_matched": job_matched,
                    "_skill_matched": skill_matched,
                }
            )

        # 1차 필터링: 직무 일치
        job_filtered = [c for c in all_candidates if c["_job_matched"]]

        # 2차 필터링: 직무 결과가 5개 이하면 기술스택으로 확장
        if len(job_filtered) <= MIN_CANDIDATES_FOR_JOB_FILTER:
            # 기술스택 하나 이상 일치 (직무 일치 포함)
            skill_filtered = [c for c in all_candidates if c["_skill_matched"]]

            # 직무 일치 우선, 그 다음 기술스택 일치
            for c in job_filtered:
                c["filter_type"] = "job"
            for c in skill_filtered:
                if c["filter_type"] is None:
                    c["filter_type"] = "skill"

            # 직무 일치 먼저, 기술스택 일치 그 다음 (각각 임베딩 순 유지)
            filtered_candidates = job_filtered + [c for c in skill_filtered if c not in job_filtered]
        else:
            for c in job_filtered:
                c["filter_type"] = "job"
            filtered_candidates = job_filtered

        # Top-K 선택 (이미 임베딩 유사도 순으로 정렬됨)
        top_candidates = filtered_candidates[:top_k]

        # 내부 필터 플래그 제거
        for c in top_candidates:
            del c["_job_matched"]
            del c["_skill_matched"]

        # Ground Truth 검증 (옵션)
        if include_gt:
            for candidate in top_candidates:
                gt_result = self.verify_mentor_ground_truth(
                    mentor_user_id=candidate["user_id"],
                    top_k=top_k,
                )
                candidate["ground_truth"] = gt_result

        return top_candidates

    def search_by_text(
        self,
        query_text: str,
        top_k: int = 5,
        only_verified: bool = False,
    ) -> list[dict[str, Any]]:
        """
        텍스트 쿼리로 직접 멘토 검색

        Args:
            query_text: 검색 텍스트 (예: "백엔드 MSA 경험")
            top_k: 검색 개수
            only_verified: 인증된 멘토만 검색

        Returns:
            검색 결과 리스트
        """
        query_embedding = self.embedder.embed_text(query_text)
        embedding_list = query_embedding.tolist()

        verified_filter = "AND ep.verified = true" if only_verified else ""

        query = text(f"""
            SELECT
                u.id as user_id,
                u.nickname,
                u.introduction,
                ep.company_name,
                ep.verified,
                ep.rating_avg,
                1 - (ep.embedding <=> CAST(:query_embedding AS vector)) as similarity,
                ARRAY_AGG(DISTINCT s.name) FILTER (WHERE s.name IS NOT NULL) as skills
            FROM expert_profiles ep
            JOIN users u ON ep.user_id = u.id
            LEFT JOIN user_skills us ON u.id = us.user_id
            LEFT JOIN skills s ON us.skill_id = s.id
            WHERE ep.embedding IS NOT NULL
                {verified_filter}
            GROUP BY u.id, u.nickname, u.introduction,
                     ep.company_name, ep.verified, ep.rating_avg, ep.embedding
            ORDER BY ep.embedding <=> CAST(:query_embedding AS vector)
            LIMIT :top_k
        """)

        result = self.conn.execute(
            query,
            {"query_embedding": str(embedding_list), "top_k": top_k},
        )

        return [
            {
                "user_id": row.user_id,
                "nickname": row.nickname,
                "company_name": row.company_name,
                "verified": row.verified,
                "skills": row.skills or [],
                "introduction": row.introduction or "",
                "similarity_score": round(float(row.similarity), 4),
            }
            for row in result
        ]

    def update_expert_embedding(self, user_id: int) -> bool:
        """특정 멘토의 임베딩 업데이트"""
        profile_text = self.get_user_profile_text(user_id)
        if not profile_text:
            return False

        embedding = self.embedder.embed_text(profile_text)
        embedding_list = embedding.tolist()

        query = text("""
            UPDATE expert_profiles
            SET embedding = CAST(:embedding AS vector)
            WHERE user_id = :user_id
        """)

        self.conn.execute(
            query,
            {"embedding": str(embedding_list), "user_id": user_id},
        )
        self.conn.commit()

        logger.info(f"Updated embedding for expert {user_id}")
        return True

    def update_all_expert_embeddings(self) -> int:
        """모든 멘토 임베딩 일괄 업데이트"""
        query = text("""
            SELECT user_id FROM expert_profiles
        """)

        result = self.conn.execute(query)
        updated_count = 0

        for row in result:
            if self.update_expert_embedding(row.user_id):
                updated_count += 1

        logger.info(f"Updated {updated_count} expert embeddings")
        return updated_count

    def evaluate_silver_ground_truth(
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
        # 임베딩이 있는 모든 멘토 가져오기
        query = text("""
            SELECT
                ep.user_id,
                u.introduction,
                ARRAY_AGG(DISTINCT s.name) FILTER (WHERE s.name IS NOT NULL) as skills,
                ARRAY_AGG(DISTINCT j.name) FILTER (WHERE j.name IS NOT NULL) as jobs
            FROM expert_profiles ep
            JOIN users u ON ep.user_id = u.id
            LEFT JOIN user_skills us ON u.id = us.user_id
            LEFT JOIN skills s ON us.skill_id = s.id
            LEFT JOIN user_jobs uj ON u.id = uj.user_id
            LEFT JOIN jobs j ON uj.job_id = j.id
            WHERE ep.embedding IS NOT NULL
            GROUP BY ep.user_id, u.introduction
            ORDER BY ep.user_id
        """)

        result = self.conn.execute(query)
        mentors = list(result)

        if sample_size:
            mentors = mentors[:sample_size]

        if not mentors:
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

        for mentor in mentors:
            gt_user_id = mentor.user_id

            # 멘토 프로필을 잡시커 텍스트로 변환 (user_id 제외)
            parts = []
            if mentor.jobs:
                parts.append(f"직무: {', '.join(mentor.jobs)}")
            if mentor.skills:
                parts.append(f"기술스택: {', '.join(mentor.skills)}")
            if mentor.introduction:
                parts.append(f"자기소개: {mentor.introduction}")

            if not parts:
                continue

            jobseeker_text = ". ".join(parts)

            # 임베딩 생성 및 Top-10 추천 실행
            query_embedding = self.embedder.embed_text(jobseeker_text)
            embedding_list = query_embedding.tolist()

            reco_query = text("""
                SELECT
                    ep.user_id,
                    1 - (ep.embedding <=> CAST(:query_embedding AS vector)) as similarity
                FROM expert_profiles ep
                WHERE ep.embedding IS NOT NULL
                ORDER BY ep.embedding <=> CAST(:query_embedding AS vector)
                LIMIT 10
            """)

            reco_result = self.conn.execute(
                reco_query,
                {"query_embedding": str(embedding_list)},
            )

            recommended_ids = [row.user_id for row in reco_result]

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
