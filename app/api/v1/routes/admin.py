"""Read-only administration APIs over the current application data model."""

from collections.abc import AsyncIterator
from math import ceil
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_admin
from app.core.config import Settings
from app.db.session import Database, get_session
from app.domain.jobs import GlobalJob
from app.domain.profiles import Profile
from app.domain.resumes import CandidateProfile, Resume, ResumeStatus
from app.domain.security import SecurityAuditEvent
from app.queue.health import check_queue_health
from app.repositories.admin import AdminRepository
from app.repositories.jobs import GlobalJobRepository
from app.schemas.admin import (
    AdminResumeDetail,
    AdminResumePage,
    AdminResumeResponse,
    AdminSettingsResponse,
    AdminUserPage,
    AdminUserResponse,
    AnalyticsResponse,
    DashboardResponse,
    JobStatsResponse,
    MetricAvailability,
    SystemStatusResponse,
)

router = APIRouter(prefix="/admin")
admin = Annotated[Profile, Depends(require_admin)]
session_dep = Annotated[AsyncSession, Depends(get_session)]
repo = AdminRepository()
jobs_repo = GlobalJobRepository()


async def get_optional_admin_session(request: Request) -> AsyncIterator[AsyncSession | None]:
    """Keep the legacy capability response when local DB services are absent."""
    database = getattr(request.app.state, "database", None)
    if not isinstance(database, Database):
        yield None
        return
    async with database.sessions() as session:
        yield session


def _page(page: int, page_size: int, total: int) -> dict[str, int]:
    return {
        "page": page,
        "page_size": page_size,
        "total": total,
        "pages": ceil(total / page_size) if total else 0,
    }


def _unavailable(reason: str) -> MetricAvailability:
    return MetricAvailability(status="unavailable", reason=reason)


@router.get("/dashboard", response_model=DashboardResponse, tags=["Admin"])
async def dashboard(_: admin, session: session_dep) -> DashboardResponse:
    return DashboardResponse(
        users=await repo.user_counts(session),
        resumes=await repo.resume_counts(session),
        security={
            "audit_events": int(
                await session.scalar(select(func.count()).select_from(SecurityAuditEvent)) or 0
            )
        },
        jobs=_unavailable("GlobalJob is not present in the current backend."),
        auto_search=_unavailable("Auto Search is not present in the current backend."),
        ai=_unavailable("AI usage records are not present in the current backend."),
        system={
            "api": MetricAvailability(status="healthy"),
            "database": MetricAvailability(status="healthy"),
        },
    )


@router.get("/users", response_model=AdminUserPage, tags=["Admin"])
async def users(
    _: admin,
    session: session_dep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
    search: Annotated[str | None, Query(max_length=320)] = None,
) -> AdminUserPage:
    rows, total = await repo.users_page(session, page=page, page_size=page_size, query=search)
    items = []
    for user in rows:
        count = await session.scalar(
            select(func.count())
            .select_from(Resume)
            .where(Resume.owner_profile_id == user.id, Resume.status != ResumeStatus.DELETED)
        )
        active = await session.scalar(
            select(Resume.id)
            .where(Resume.owner_profile_id == user.id, Resume.status != ResumeStatus.DELETED)
            .order_by(Resume.created_at.desc())
            .limit(1)
        )
        parsed = await session.scalar(
            select(func.count())
            .select_from(CandidateProfile)
            .where(CandidateProfile.owner_profile_id == user.id)
        )
        items.append(
            AdminUserResponse(
                id=user.id,
                email=user.email,
                is_admin=user.role.value == "admin",
                is_active=user.is_active,
                created_at=user.created_at,
                resume_count=int(count or 0),
                active_resume_id=active,
                candidate_profile_available=bool(parsed),
            )
        )
    return AdminUserPage(items=items, **_page(page, page_size, total))


@router.get("/users/{user_id}", response_model=AdminUserResponse, tags=["Admin"])
async def user_detail(user_id: UUID, _: admin, session: session_dep) -> AdminUserResponse:
    user = await session.get(Profile, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    count = await session.scalar(
        select(func.count())
        .select_from(Resume)
        .where(Resume.owner_profile_id == user.id, Resume.status != ResumeStatus.DELETED)
    )
    active = await session.scalar(
        select(Resume.id)
        .where(Resume.owner_profile_id == user.id, Resume.status != ResumeStatus.DELETED)
        .order_by(Resume.created_at.desc())
        .limit(1)
    )
    parsed = await session.scalar(
        select(func.count())
        .select_from(CandidateProfile)
        .where(CandidateProfile.owner_profile_id == user.id)
    )
    return AdminUserResponse(
        id=user.id,
        email=user.email,
        is_admin=user.role.value == "admin",
        is_active=user.is_active,
        created_at=user.created_at,
        resume_count=int(count or 0),
        active_resume_id=active,
        candidate_profile_available=bool(parsed),
    )


def _resume_response(row: tuple[Resume, Profile, CandidateProfile | None]) -> AdminResumeResponse:
    resume, user, candidate = row
    return AdminResumeResponse(
        id=resume.id,
        user_id=user.id,
        user_email=user.email,
        filename=resume.original_filename,
        uploaded_at=resume.created_at,
        active=resume.status != ResumeStatus.DELETED,
        status=resume.status,
        parser_version=resume.parser_version,
        candidate_profile_available=candidate is not None,
    )


@router.get("/resumes", response_model=AdminResumePage, tags=["Admin"])
async def resumes(
    _: admin,
    session: session_dep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> AdminResumePage:
    rows, total = await repo.resumes_page(session, page=page, page_size=page_size)
    return AdminResumePage(
        items=[_resume_response(row) for row in rows], **_page(page, page_size, total)
    )


@router.get("/resumes/{resume_id}", response_model=AdminResumeDetail, tags=["Admin"])
async def resume_detail(resume_id: UUID, _: admin, session: session_dep) -> AdminResumeDetail:
    row = await repo.resume(session, resume_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Resume not found")
    candidate = row[2]
    base = _resume_response(row).model_dump()
    return AdminResumeDetail(
        **base,
        full_name=candidate.full_name if candidate else None,
        location=candidate.location if candidate else None,
        current_title=candidate.current_title if candidate else None,
        skills=candidate.skills if candidate else [],
        experience=candidate.employment_history if candidate else [],
        education=candidate.education if candidate else [],
    )


@router.get("/jobs/stats", response_model=JobStatsResponse, tags=["Admin"])
async def job_stats(
    _: admin,
    session: Annotated[AsyncSession | None, Depends(get_optional_admin_session)],
) -> JobStatsResponse:
    if session is None:
        return JobStatsResponse(status="unavailable", reason="Database is not configured")
    stats = await jobs_repo.stats(session)
    return JobStatsResponse(status="healthy", **stats)


@router.get("/jobs", tags=["Admin"])
async def jobs(
    _: admin,
    session: Annotated[AsyncSession | None, Depends(get_optional_admin_session)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
    search: Annotated[str | None, Query(max_length=200)] = None,
    source: Annotated[str | None, Query(max_length=32)] = None,
    role: Annotated[str | None, Query(max_length=64)] = None,
    location: Annotated[str | None, Query(max_length=200)] = None,
) -> dict[str, object]:
    if session is None:
        raise HTTPException(status_code=501, detail="GlobalJob administration requires a database")
    rows, total = await jobs_repo.search(
        session, query=search, role=role, location=location, page=page, page_size=page_size
    )
    if source is not None:
        rows = [row for row in rows if row.source == source]
    return {
        "items": [row.__dict__ for row in rows],
        "page": page,
        "page_size": page_size,
        "total": total,
    }


@router.get("/jobs/{job_id}", response_model=None, tags=["Admin"])
async def job_detail(
    job_id: UUID,
    _: admin,
    session: Annotated[AsyncSession | None, Depends(get_optional_admin_session)],
) -> GlobalJob:
    if session is None:
        raise HTTPException(status_code=501, detail="GlobalJob administration requires a database")
    job = await jobs_repo.by_id(session, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.get("/auto-searches", tags=["Admin"])
async def auto_searches(_: admin) -> None:
    raise HTTPException(status_code=501, detail="Auto Search is not implemented in this backend.")


@router.get("/ai-costs", tags=["Admin"])
async def ai_costs(_: admin) -> None:
    raise HTTPException(
        status_code=501,
        detail="AI usage accounting is not implemented in this backend.",
    )


@router.get("/analytics/overview", response_model=AnalyticsResponse, tags=["Admin"])
async def analytics(_: admin, session: session_dep) -> AnalyticsResponse:
    return AnalyticsResponse(
        users_over_time=[],
        resume_uploads_over_time=[],
        jobs=_unavailable("GlobalJob is not present in the current backend."),
        auto_search=_unavailable("Auto Search is not present in the current backend."),
        ai=_unavailable("AI usage records are not present in the current backend."),
    )


@router.get("/system/status", response_model=SystemStatusResponse, tags=["Admin"])
async def system_status(_: admin, session: session_dep, request: Request) -> SystemStatusResponse:
    try:
        await session.execute(select(1))
        database = MetricAvailability(status="healthy")
    except Exception:
        database = MetricAvailability(status="unavailable")
    application_settings = getattr(request.app.state, "settings", None)
    queue_health = (
        await check_queue_health(application_settings)
        if isinstance(application_settings, Settings)
        else None
    )
    redis = (
        MetricAvailability(status=queue_health.redis, reason=queue_health.reason)
        if queue_health
        else MetricAvailability(status="unknown", reason="Settings are unavailable")
    )
    workers = (
        MetricAvailability(status=queue_health.worker, reason=queue_health.reason)
        if queue_health
        else MetricAvailability(status="unknown", reason="Settings are unavailable")
    )
    if not isinstance(application_settings, Settings):
        collection = MetricAvailability(status="unknown", reason="Settings are unavailable")
    elif not application_settings.job_collection_enabled:
        collection = MetricAvailability(status="disabled")
    elif queue_health and queue_health.worker == "healthy":
        collection = MetricAvailability(status="healthy")
    else:
        collection = MetricAvailability(
            status="unknown", reason="No healthy worker heartbeat was found"
        )
    return SystemStatusResponse(
        api=MetricAvailability(status="healthy"),
        database=database,
        redis=redis,
        workers=workers,
        job_collection=collection,
        scrapers={},
    )


@router.get("/settings", response_model=AdminSettingsResponse, tags=["Admin"])
async def settings(_: admin) -> AdminSettingsResponse:
    return AdminSettingsResponse(
        configurable={},
        read_only={"environment": "application configuration is deployment-managed"},
    )
