"""Schemas for async search endpoints."""

from typing import TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.jobs import JobResponse

T = TypeVar("T")


class AsyncSearchRequest(BaseModel):
    """Payload for starting an async search."""

    query: str | None = Field(None, max_length=200)
    location: str | None = Field(None, max_length=200)
    remote_type: str | None = Field(None, max_length=32)
    job_type: str | None = Field(None, max_length=100)
    experience_min: int | None = Field(None, ge=0)
    experience_max: int | None = Field(None, ge=0)
    limit: int = Field(100, ge=1, le=500)


class AsyncSearchResponse(BaseModel):
    """Response when starting a new async search."""

    search_id: UUID
    status: str = "queued"


class AsyncSearchProgress(BaseModel):
    """Progress status of an async search."""

    search_id: UUID
    status: str
    current_stage: str
    progress: int = Field(..., ge=0, le=100)
    error_message: str | None = None

    model_config = ConfigDict(from_attributes=True)


class SearchResultItem(JobResponse):
    """A matched job resulting from a search."""

    rank: int
    match_score: float
    skills_score: float
    experience_score: float
    location_score: float
    freshness_score: float


class AsyncSearchResults[T](BaseModel):
    """Paginated search results."""

    search_id: UUID
    status: str
    items: list[T]
    total: int
    page: int
    page_size: int
    pages: int
