"""Business logic for async job searches."""

import logging
from uuid import UUID

from arq.connections import ArqRedis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import InfrastructureError, NotFoundError
from app.domain.search import JobSearch
from app.jobs.types import SearchStatus
from app.schemas.search import AsyncSearchRequest
from app.search.repository import SearchRepository

logger = logging.getLogger(__name__)


class SearchService:
    """Service for managing the async search lifecycle."""

    def __init__(self, repository: SearchRepository, settings: Settings, redis: ArqRedis) -> None:
        self.repository = repository
        self.settings = settings
        self.redis = redis

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
