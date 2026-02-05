"""멘토 검색 모듈 - 필터링 + 임베딩 유사도 기반 추천"""

import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection, Row

from services.reco.embedder import ProfileEmbedder, get_embedder

logger = logging.getLogger(__name__)

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

    # ========== 헬퍼 메서드 ==========

    def _build_mentor_candidates_query(
        self,
        only_verified: bool = False,
        exclude_user_id: int | None = None,
        include_jobs: bool = True,
    ) -> str:
        """멘토 후보 조회 SQL 쿼리 생성

        Args:
            only_verified: 인증된 멘토만 조회
            exclude_user_id: 제외할 사용자 ID
            include_jobs: 직무 정보 포함 여부

        Returns:
            SQL 쿼리 문자열
        """
        jobs_select = "ARRAY_AGG(DISTINCT j.name) FILTER (WHERE j.name IS NOT NULL) as jobs," if include_jobs else ""
        jobs_join = (
            """
            LEFT JOIN user_jobs uj ON u.id = uj.user_id
            LEFT JOIN jobs j ON uj.job_id = j.id"""
            if include_jobs
            else ""
        )

        where_clauses = ["ep.embedding IS NOT NULL"]
        if exclude_user_id is not None:
            where_clauses.append("ep.user_id != :user_id")
        if only_verified:
            where_clauses.append("ep.verified = true")

        where_clause = " AND ".join(where_clauses)

        return f"""
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
                {jobs_select}
            FROM expert_profiles ep
            JOIN users u ON ep.user_id = u.id
            LEFT JOIN user_skills us ON u.id = us.user_id
            LEFT JOIN skills s ON us.skill_id = s.id
            {jobs_join}
            WHERE {where_clause}
            GROUP BY u.id, u.nickname, u.introduction,
                     ep.company_name, ep.verified, ep.rating_avg, ep.rating_count,
                     ep.responded_request_count, ep.accepted_request_count,
                     ep.rejected_request_count, ep.last_active_at, ep.embedding
            ORDER BY ep.embedding <=> CAST(:query_embedding AS vector)
            LIMIT :candidate_limit
        """.replace("jobs,\n            FROM", "jobs\n            FROM")  # jobs가 없을 때 콤마 제거

    def _row_to_candidate(
        self,
        row: Row,
        user_skills: set[str],
        user_jobs: set[str],
    ) -> MentorCandidate:
        """DB Row를 MentorCandidate로 변환"""
        mentor_skills = set(row.skills or [])
        mentor_jobs = set(getattr(row, "jobs", None) or [])

        response_rate = 0.0
        if row.responded_request_count and row.responded_request_count > 0:
            response_rate = row.accepted_request_count / row.responded_request_count * 100

        return MentorCandidate(
            user_id=row.user_id,
            nickname=row.nickname,
            introduction=row.introduction or "",
            company_name=row.company_name,
            verified=row.verified,
            rating_avg=round(row.rating_avg, 1) if row.rating_avg else 0.0,
            rating_count=row.rating_count or 0,
            response_rate=round(response_rate, 1),
            skills=row.skills or [],
            jobs=getattr(row, "jobs", None) or [],
            similarity_score=round(float(row.embedding_similarity), 4),
            last_active_at=row.last_active_at.isoformat() if row.last_active_at else None,
            _job_matched=bool(user_jobs & mentor_jobs),
            _skill_matched=bool(user_skills & mentor_skills),
        )

    def _filter_candidates(
        self,
        candidates: list[MentorCandidate],
        top_k: int,
    ) -> list[MentorCandidate]:
        """후보 필터링 (직무 우선, 기술스택 fallback)

        Args:
            candidates: 전체 후보 리스트
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

        return filtered[:top_k]

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

        # 후보 멘토 조회
        candidate_limit = max(top_k * 10, 100)
        query_str = self._build_mentor_candidates_query(
            only_verified=only_verified,
            exclude_user_id=user_id,
            include_jobs=True,
        )

        result = self.conn.execute(
            text(query_str),
            {
                "query_embedding": str(embedding_list),
                "user_id": user_id,
                "candidate_limit": candidate_limit,
            },
        )

        # 후보 데이터 변환
        all_candidates = [self._row_to_candidate(row, user_skills, user_jobs) for row in result]

        # 필터링 및 Top-K 선택
        top_candidates = self._filter_candidates(all_candidates, top_k)

        # Ground Truth 검증 (옵션)
        if include_gt:
            for candidate in top_candidates:
                gt_result = self.verify_mentor_ground_truth(
                    mentor_user_id=candidate.user_id,
                    top_k=top_k,
                )
                candidate.ground_truth = gt_result

        # 딕셔너리로 변환하여 반환
        return [c.to_dict() for c in top_candidates]

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

        # 간단한 검색용 쿼리 (직무 정보 제외)
        where_clause = "ep.embedding IS NOT NULL"
        if only_verified:
            where_clause += " AND ep.verified = true"

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
            WHERE {where_clause}
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
        """특정 멘토의 임베딩 업데이트 (직접 DB에 저장)"""
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

    def compute_embedding(self, user_id: int) -> dict[str, Any] | None:
        """
        사용자 프로필 임베딩 계산

        Args:
            user_id: 사용자 ID

        Returns:
            {"user_id": int, "embedding": list[float]} or None
        """
        profile_text = self.get_user_profile_text(user_id)
        if not profile_text:
            logger.warning(f"User {user_id} has no profile text")
            return None

        embedding = self.embedder.embed_text(profile_text)
        embedding_list = embedding.tolist()

        logger.info(f"Computed embedding for user {user_id}, dim={len(embedding_list)}")

        return {
            "user_id": user_id,
            "embedding": embedding_list,
        }

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
