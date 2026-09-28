"""Business logic for async job searches."""

from uuid import UUID

from arq.connections import ArqRedis
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.domain.search import JobSearch
from app.repositories.search import SearchRepository
from app.schemas.search import AsyncSearchRequest


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
        await self.repository.create_search(session, search)
        
        # Enqueue to ARQ
        await self.redis.enqueue_job(
            "run_job_search",
            search.id,
            _queue_name=self.settings.job_search_queue_name,
        )
        
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


def get_search_service(
    session: AsyncSession, settings: Settings, redis: ArqRedis
) -> SearchService:
    """Dependency provider (concept). Actually, FastAPI dependencies should be configured properly."""
    pass
