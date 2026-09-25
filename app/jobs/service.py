"""Orchestration of job search and candidate recommendations."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.jobs.matching import Candidate, is_eligible, rank_job
from app.jobs.normalization import ROLE_COMPATIBILITY, normalize_role
from app.repositories.canonical_jobs import (
    CanonicalJobRead,
    CanonicalJobRepository,
)
from app.repositories.resumes import CandidateProfileRepository


class JobService:
    """Business logic and orchestration for the jobs domain."""

    def __init__(
        self,
        job_repository: CanonicalJobRepository,
        candidate_repository: CandidateProfileRepository,
    ) -> None:
        """Initialize with required database repositories."""
        self._job_repository = job_repository
        self._candidate_repository = candidate_repository

    async def search(
        self,
        session: AsyncSession,
        *,
        query: str | None = None,
        role: str | None = None,
        location: str | None = None,
        remote: bool | None = None,
        employment_type: str | None = None,
        source: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[CanonicalJobRead], int]:
        """Search the reusable canonical global-job pool."""
        return await self._job_repository.search(
            session,
            query=query,
            role=role,
            location=location,
            remote=remote,
            employment_type=employment_type,
            source=source,
            page=page,
            page_size=page_size,
        )

    async def get_recommendations(
        self,
        session: AsyncSession,
        *,
        owner_profile_id: UUID,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[tuple[CanonicalJobRead, dict[str, float]]], int]:
        """Return deterministic candidate recommendations from canonical jobs."""
        candidate_profile = await self._candidate_repository.get_latest_owned(
            session,
            owner_profile_id=owner_profile_id,
        )

        if candidate_profile is None:
            return [], 0

        candidate = Candidate(
            role=candidate_profile.current_title or "",
            years_experience=candidate_profile.years_of_experience,
            skills=frozenset(skill.casefold() for skill in candidate_profile.skills),
            location=candidate_profile.location,
        )

        candidate_role = normalize_role(candidate.role)
        compatible_roles = tuple(
            ROLE_COMPATIBILITY.get(
                candidate_role,
                (candidate_role,),
            )
        )

        # Pull a broad chunk from the database for in-memory eligibility and ranking
        rows, _ = await self._job_repository.search(
            session,
            role_families=compatible_roles,
            page=1,
            page_size=500,
        )

        ranked = [(job, rank_job(candidate, job)) for job in rows if is_eligible(candidate, job)]

        ranked.sort(
            key=lambda item: (
                -item[1]["match_score"],
                item[0].id,
            )
        )

        total = len(ranked)
        start = (page - 1) * page_size
        end = page * page_size
        selected = ranked[start:end]

        return selected, total


def get_job_service() -> JobService:
    """Dependency provider for JobService."""
    return JobService(
        job_repository=CanonicalJobRepository(),
        candidate_repository=CandidateProfileRepository(),
    )
