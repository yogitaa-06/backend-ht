"""Stored canonical job search and candidate recommendations."""

from math import ceil
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_profile
from app.db.session import get_session
from app.domain.profiles import Profile
from app.domain.resumes import CandidateProfile
from app.jobs.matching import Candidate, is_eligible, rank_job
from app.jobs.normalization import ROLE_COMPATIBILITY, normalize_role
from app.repositories.canonical_jobs import (
    CanonicalJobRead,
    CanonicalJobRepository,
)
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

repository = CanonicalJobRepository()


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

    rows, total = await repository.search(
        session,
        query=query,
        role=role,
        location=location,
        remote=remote,
        employment_type=employment_type,
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

    candidate_profile = await session.scalar(
        select(CandidateProfile)
        .where(
            CandidateProfile.owner_profile_id
            == profile.id
        )
        .order_by(
            CandidateProfile.updated_at.desc()
        )
        .limit(1)
    )

    if candidate_profile is None:
        return _page(
            [],
            page,
            page_size,
            0,
        )

    candidate = Candidate(
        role=candidate_profile.current_title or "",
        years_experience=(
            candidate_profile.years_of_experience
        ),
        skills=frozenset(
            skill.casefold()
            for skill in candidate_profile.skills
        ),
        location=candidate_profile.location,
    )

    candidate_role = normalize_role(
        candidate.role
    )

    compatible_roles = tuple(
        ROLE_COMPATIBILITY.get(
            candidate_role,
            (candidate_role,),
        )
    )

    rows, _ = await repository.search(
        session,
        role_families=compatible_roles,
        page=1,
        page_size=500,
    )

    ranked = [
        (
            job,
            rank_job(candidate, job),
        )
        for job in rows
        if is_eligible(candidate, job)
    ]

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

    return _page(
        [
            _response(job, scores)
            for job, scores in selected
        ],
        page,
        page_size,
        total,
    )