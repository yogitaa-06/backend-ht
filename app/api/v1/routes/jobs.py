"""Stored canonical job search and candidate recommendations."""

from math import ceil
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_profile
from app.db.session import get_session
from app.domain.profiles import Profile
from app.jobs.service import JobService, get_job_service
from app.repositories.canonical_jobs import CanonicalJobRead
from app.schemas.jobs import JobPage, JobResponse

router = APIRouter(prefix="/jobs")

session_dep = Annotated[
    AsyncSession,
    Depends(get_session),
]

profile_dep = Annotated[
    Profile,
    Depends(get_current_profile),
]

service_dep = Annotated[
    JobService,
    Depends(get_job_service),
]


def _response(
    job: CanonicalJobRead,
    scores: dict[str, float] | None = None,
) -> JobResponse:
    """Convert a canonical repository result into the public API contract."""

    values = {
        "id": job.id,
        "source": job.source,
        "external_job_id": job.external_job_id,
        "job_title": job.job_title,
        "role_family": job.role_family,
        "company": job.company,
        "location": job.location,
        "job_url": job.job_url,
        "description": job.description,
        "salary_text": job.salary_text,
        "employment_type": job.employment_type,
        "remote": job.remote,
        "skills": job.skills,
        "posted_at": job.posted_at,
        "source_updated_at": job.source_updated_at,
        "first_seen_at": job.first_seen_at,
        "last_seen_at": job.last_seen_at,
        "scraped_at": job.scraped_at,
        "experience_min_years": job.experience_min_years,
        "experience_max_years": job.experience_max_years,
        "experience_text": job.experience_text,
    }

    return JobResponse(
        **values,
        **(scores or {}),
    )


def _page(
    items: list[JobResponse],
    page: int,
    page_size: int,
    total: int,
) -> JobPage:
    """Build the paginated public job response."""

    return JobPage(
        items=items,
        page=page,
        page_size=page_size,
        total=total,
        pages=ceil(total / page_size) if total else 0,
    )


@router.get(
    "",
    response_model=JobPage,
    tags=["jobs"],
)
async def search_jobs(
    _: profile_dep,
    session: session_dep,
    service: service_dep,
    query: Annotated[
        str | None,
        Query(max_length=200),
    ] = None,
    role: Annotated[
        str | None,
        Query(max_length=64),
    ] = None,
    location: Annotated[
        str | None,
        Query(max_length=200),
    ] = None,
    remote: bool | None = None,
    employment_type: Annotated[
        str | None,
        Query(max_length=100),
    ] = None,
    source: Annotated[
        str | None,
        Query(max_length=100),
    ] = None,
    page: Annotated[
        int,
        Query(ge=1),
    ] = 1,
    page_size: Annotated[
        int,
        Query(ge=1, le=100),
    ] = 50,
) -> JobPage:
    """Search the reusable canonical global-job pool.

    This endpoint only reads jobs already collected by background workers.
    User requests never trigger provider scraping.
    """

    rows, total = await service.search(
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

    return _page(
        [_response(row) for row in rows],
        page,
        page_size,
        total,
    )


@router.get(
    "/recommended",
    response_model=JobPage,
    tags=["jobs"],
)
async def recommended_jobs(
    profile: profile_dep,
    session: session_dep,
    service: service_dep,
    page: Annotated[
        int,
        Query(ge=1),
    ] = 1,
    page_size: Annotated[
        int,
        Query(ge=1, le=100),
    ] = 50,
) -> JobPage:
    """Return deterministic candidate recommendations from canonical jobs."""

    rows, total = await service.get_recommendations(
        session,
        owner_profile_id=profile.id,
        page=page,
        page_size=page_size,
    )

    return _page(
        [_response(job, scores) for job, scores in rows],
        page,
        page_size,
        total,
    )
