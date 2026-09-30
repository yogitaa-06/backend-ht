"""Background execution lifecycle for user-specific searches."""

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.domain.search import JobSearchResult
from app.jobs.matching.eligibility import is_eligible
from app.jobs.matching.models import Candidate
from app.jobs.matching.ranking import rank_matches
from app.jobs.matching.scoring import score_job
from app.jobs.types import RemoteType, SearchStatus
from app.repositories.canonical_jobs import CanonicalJobRepository
from app.resumes.repository import CandidateProfileRepository
from app.search.repository import SearchRepository

logger = logging.getLogger(__name__)


class SearchExecutionService:
    """Own search state transitions independently from the ARQ entrypoint."""

    def __init__(
        self,
        repository: SearchRepository | None = None,
        job_repository: CanonicalJobRepository | None = None,
        profile_repository: CandidateProfileRepository | None = None,
        settings: Settings | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository or SearchRepository()
        self._job_repository = job_repository or CanonicalJobRepository()
        self._profile_repository = profile_repository or CandidateProfileRepository()
        self._settings = settings or Settings()
        self._clock = clock or (lambda: datetime.now(UTC))

    async def execute(self, session: AsyncSession, search_id: UUID) -> None:
        search = await self._repository.get_search_for_worker(session, search_id)
        if search is None:
            logger.warning("job_search_missing", extra={"search_id": str(search_id)})
            return
        if search.status in {SearchStatus.COMPLETED, SearchStatus.FAILED}:
            logger.info(
                "job_search_terminal_state_skipped",
                extra={"search_id": str(search_id), "status": str(search.status)},
            )
            return

        started_at = self._clock()
        search.status = SearchStatus.PROCESSING
        search.current_stage = "loading_profile"
        search.started_at = search.started_at or started_at
        await session.flush()

        try:
            profile = await self._profile_repository.get_latest_owned(
                session, owner_profile_id=search.user_id
            )
            if not profile:
                search.status = SearchStatus.FAILED
                search.current_stage = "loading_profile_failed"
                search.error_message = "No candidate profile found. Please upload a resume first."
                search.completed_at = self._clock()
                await session.commit()
                return

            candidate = Candidate(
                role=search.query or profile.current_title or search.job_type or "Unknown",
                years_experience=profile.years_of_experience,
                skills=frozenset(profile.skills),
                location=profile.location,
                remote_preferred=True if search.remote_type == RemoteType.REMOTE else None,
            )

            search.current_stage = "retrieving_candidates"
            search.progress = 10
            await session.flush()

            remote_val = None
            if search.remote_type == RemoteType.REMOTE:
                remote_val = True
            elif search.remote_type == RemoteType.ON_SITE:
                remote_val = False

            canonical_reads, _ = await self._job_repository.search(
                session,
                query=search.query,
                location=search.location,
                remote=remote_val,
                employment_type=search.job_type,
                page=1,
                page_size=self._settings.search_candidate_limit,
            )

            search.current_stage = "filtering"
            search.progress = 40
            await session.flush()

            eligible_candidates = []
            for job in canonical_reads:
                if is_eligible(candidate, job):
                    eligible_candidates.append(job)

            search.current_stage = "matching"
            search.progress = 60
            await session.flush()

            scored_matches = []
            for job in eligible_candidates:
                score = score_job(candidate, job, now=started_at)
                scored_matches.append((job, score))

            search.current_stage = "ranking"
            search.progress = 80
            await session.flush()

            ranked_matches = rank_matches(scored_matches)
            top_matches = ranked_matches[: search.requested_limit]

            search.current_stage = "saving_results"
            search.progress = 90
            await session.flush()

            results = []
            for rank, (matched_job, score) in enumerate(top_matches, start=1):
                results.append(
                    JobSearchResult(
                        search_id=search.id,
                        job_id=matched_job.id,
                        rank=rank,
                        match_score=score.overall_score,
                        skills_score=score.skills_score,
                        experience_score=score.experience_score,
                        location_score=score.location_score,
                        freshness_score=score.freshness_score,
                    )
                )

            await self._repository.clear_results(session, search.id)
            await self._repository.save_results(session, results)

            search.status = SearchStatus.COMPLETED
            search.current_stage = "completed"
            search.progress = 100
            search.completed_at = self._clock()
            await session.commit()

            logger.info(
                "job_search_completed",
                extra={
                    "search_id": str(search_id),
                    "user_id": str(search.user_id),
                    "candidates_retrieved": len(canonical_reads),
                    "eligible_count": len(eligible_candidates),
                    "results_count": len(results),
                    "duration_ms": int(
                        (search.completed_at - search.started_at).total_seconds() * 1000
                    ),
                },
            )

        except Exception:
            await session.rollback()
            search = await self._repository.get_search_for_worker(session, search_id)
            if search is None:
                return
            logger.exception(
                "job_search_failed",
                extra={"search_id": str(search_id)},
            )
            search.status = SearchStatus.FAILED
            search.current_stage = "failed"
            search.error_message = "An unexpected error occurred during search execution."
            search.completed_at = self._clock()
            await session.commit()
