"""Async search API endpoints."""

from typing import Annotated
from uuid import UUID

from arq.connections import ArqRedis
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_profile
from app.core.config import Settings, get_settings
from app.db.session import get_session
from app.domain.profiles import Profile
from app.queue.dependencies import get_redis
from app.schemas.search import AsyncSearchProgress, AsyncSearchRequest, AsyncSearchResponse
from app.search.repository import SearchRepository
from app.search.service import SearchService

router = APIRouter(prefix="/search")


def get_search_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    redis: Annotated[ArqRedis, Depends(get_redis)],
) -> SearchService:
    repository = SearchRepository()
    return SearchService(repository, settings, redis)


session_dep = Annotated[AsyncSession, Depends(get_session)]
profile_dep = Annotated[Profile, Depends(get_current_profile)]
service_dep = Annotated[SearchService, Depends(get_search_service)]


@router.post(
    "",
    response_model=AsyncSearchResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["search"],
)
async def start_search(
    request: AsyncSearchRequest,
    profile: profile_dep,
    session: session_dep,
    service: service_dep,
) -> AsyncSearchResponse:
    """
    Start an asynchronous job search.

    Validates parameters, creates a search tracking record, and enqueues a background
    task to perform matching and ranking without blocking the HTTP request.
    """
    search = await service.start_search(session, profile.id, request)

    return AsyncSearchResponse(
        search_id=search.id,
        status=search.status,
    )


@router.get(
    "/{search_id}/progress",
    response_model=AsyncSearchProgress,
    tags=["search"],
)
async def get_search_progress(
    search_id: UUID,
    profile: profile_dep,
    session: session_dep,
    service: service_dep,
) -> AsyncSearchProgress:
    """
    Retrieve the current progress and status of an asynchronous search.
    """
    search = await service.get_search_progress(session, profile.id, search_id)

    return AsyncSearchProgress(
        search_id=search.id,
        status=search.status,
        current_stage=search.current_stage,
        progress=search.progress,
        error_message=search.error_message,
    )
