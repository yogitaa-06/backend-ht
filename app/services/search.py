"""Business logic for async job searches."""

import logging
from uuid import UUID

from arq.connections import ArqRedis
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.domain.search import JobSearch
from app.repositories.search import SearchRepository
from app.schemas.search import AsyncSearchRequest

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
            status="queued",
            current_stage="queued",
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
            search.status = "failed"
            search.current_stage = "queue_failed"
            search.error_message = "Failed to enqueue search task."
            await session.commit()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to enqueue search task.",
            ) from exc
        
        return search

    async def get_search_progress(
        self, session: AsyncSession, user_id: UUID, search_id: UUID
    ) -> JobSearch:
        """Get the progress of a user's search."""
        search = await self.repository.get_search(session, search_id, user_id)
        if not search:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Search not found",
            )
        return search


