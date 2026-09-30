"""Business logic for async job searches."""

import logging
from uuid import UUID

from arq.connections import ArqRedis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import ConflictError, InfrastructureError, NotFoundError
from app.domain.search import JobSearch
from app.jobs.types import RemoteType, SearchStatus
from app.repositories.canonical_jobs import CanonicalJobRepository
from app.schemas.search import AsyncSearchRequest, SearchResultItem
from app.search.repository import SearchRepository

logger = logging.getLogger(__name__)


class SearchService:
    """Service for managing the async search lifecycle."""

    def __init__(
        self,
        repository: SearchRepository,
        settings: Settings,
        redis: ArqRedis,
        job_repository: CanonicalJobRepository | None = None,
    ) -> None:
        self.repository = repository
        self.settings = settings
        self.redis = redis
        self.job_repository = job_repository or CanonicalJobRepository()

    async def start_search(
        self, session: AsyncSession, user_id: UUID, request: AsyncSearchRequest
    ) -> JobSearch:
        """Create a search and enqueue it for background processing."""
        search = JobSearch(
            user_id=user_id,
            status=SearchStatus.QUEUED,
            current_stage=SearchStatus.QUEUED,
            query=request.query,
            location=request.location,
            remote_type=request.remote_type,
            job_type=request.job_type,
            experience_min=request.experience_min,
            experience_max=request.experience_max,
            requested_limit=request.limit,
        )
        logger.info(
            "job_search_created",
            extra={"search_id": str(search.id), "user_id": str(user_id)},
        )
        await self.repository.create_search(session, search)
        await session.commit()
        logger.info(
            "job_search_committed",
            extra={"search_id": str(search.id), "user_id": str(user_id)},
        )

        try:
            # Enqueue to ARQ
            await self.redis.enqueue_job(
                "run_job_search",
                search.id,
                _queue_name=self.settings.job_search_queue_name,
            )
            logger.info(
                "job_search_enqueued",
                extra={"search_id": str(search.id), "user_id": str(user_id)},
            )
        except Exception as exc:
            logger.exception(
                "job_search_enqueue_failed",
                extra={"search_id": str(search.id), "user_id": str(user_id)},
            )
            search.status = SearchStatus.FAILED
            search.current_stage = "queue_failed"
            search.error_message = "Failed to enqueue search task."
            await session.commit()
            raise InfrastructureError(
                "SEARCH_QUEUE_UNAVAILABLE",
                "The search could not be queued. Please try again later.",
            ) from exc

        return search

    async def get_search_progress(
        self, session: AsyncSession, user_id: UUID, search_id: UUID
    ) -> JobSearch:
        """Get the progress of a user's search."""
        search = await self.repository.get_search(session, search_id, user_id)
        if not search:
            raise NotFoundError("SEARCH_NOT_FOUND", "The requested search does not exist.")
        return search

    async def get_search_results(
        self, session: AsyncSession, user_id: UUID, search_id: UUID, page: int, page_size: int
    ) -> tuple[JobSearch, list[SearchResultItem], int]:
        """Get the paginated results of a completed search."""
        search = await self.repository.get_search(session, search_id, user_id)
        if not search:
            raise NotFoundError("SEARCH_NOT_FOUND", "The requested search does not exist.")

        if search.status != SearchStatus.COMPLETED:
            if search.status == SearchStatus.FAILED:
                raise ConflictError("SEARCH_FAILED", "The search failed and has no results.")
            else:
                raise ConflictError("SEARCH_NOT_COMPLETED", "The search is not yet completed.")

        results, total = await self.repository.get_results(session, search_id, page, page_size)

        items: list[SearchResultItem] = []
        for r in results:
            observation = await self.job_repository._presentation_source(session, r.job_id)
            if not observation:
                continue

            remote_val = None
            if r.job.remote_type == RemoteType.REMOTE:
                remote_val = True
            elif r.job.remote_type == RemoteType.ON_SITE:
                remote_val = False

            company_name = None
            if hasattr(r.job, "company") and r.job.company:
                company_name = r.job.company.name

            item = SearchResultItem(
                id=r.job_id,
                source=observation.source,
                external_job_id=observation.source_job_id,
                job_title=r.job.title,
                role_family=r.job.role_family,
                company=company_name,
                location=r.job.location,
                job_url=observation.source_url,
                description=r.job.description,
                salary_text=r.job.salary_text,
                employment_type=r.job.employment_type,
                remote=remote_val,
                skills=list(r.job.skills or []),
                posted_at=r.job.posted_at,
                source_updated_at=observation.source_updated_at,
                first_seen_at=observation.first_seen_at,
                last_seen_at=observation.last_seen_at,
                scraped_at=observation.scraped_at,
                experience_min_years=r.job.experience_min_years,
                experience_max_years=r.job.experience_max_years,
                experience_text=r.job.experience_text,
                salary_min=float(r.job.salary_min) if r.job.salary_min else None,
                salary_max=float(r.job.salary_max) if r.job.salary_max else None,
                salary_currency=r.job.salary_currency,
                salary_period=r.job.salary_period,
                remote_type=r.job.remote_type,
                rank=r.rank,
                match_score=r.match_score,
                skills_score=r.skills_score,
                experience_score=r.experience_score,
                location_score=r.location_score,
                freshness_score=r.freshness_score,
            )
            items.append(item)

        return search, items, total
