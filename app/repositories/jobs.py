"""Database access for normalized global jobs."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import UUID

from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.jobs import GlobalJob
from app.jobs.normalization import NormalizedJob


class JobUpsertStatus(StrEnum):
    INSERTED = "inserted"
    UPDATED = "updated"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class JobUpsertResult:
    job: GlobalJob
    status: JobUpsertStatus


class GlobalJobRepository:
    async def upsert(self, session: AsyncSession, job: NormalizedJob) -> GlobalJob:
        """Compatibility wrapper returning the persisted job."""
        return (await self.upsert_with_outcome(session, job)).job

    async def upsert_with_outcome(
        self, session: AsyncSession, job: NormalizedJob
    ) -> JobUpsertResult:
        """Insert, refresh, or update one source-identified canonical job."""
        existing = await session.scalar(
            select(GlobalJob).where(
                GlobalJob.source == job.source, GlobalJob.external_job_id == job.external_job_id
            )
        )
        now = datetime.now(UTC)
        values = {
            "source": job.source,
            "external_job_id": job.external_job_id,
            "job_title": job.job_title,
            "normalized_title": job.normalized_title,
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
            "scraped_at": now,
            "last_seen_at": now,
            "is_active": True,
            "content_hash": job.content_hash,
        }
        if existing is None:
            existing = GlobalJob(**values)
            session.add(existing)
            status = JobUpsertStatus.INSERTED
        elif existing.content_hash == job.content_hash:
            existing.last_seen_at = now
            existing.scraped_at = now
            existing.is_active = True
            status = JobUpsertStatus.SKIPPED
        else:
            for key, value in values.items():
                setattr(existing, key, value)
            status = JobUpsertStatus.UPDATED
        await session.flush()
        return JobUpsertResult(existing, status)

    async def search(
        self,
        session: AsyncSession,
        *,
        query: str | None = None,
        role: str | None = None,
        location: str | None = None,
        remote: bool | None = None,
        employment_type: str | None = None,
        role_families: Sequence[str] | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[GlobalJob], int]:
        predicates: list[ColumnElement[bool]] = [GlobalJob.is_active.is_(True)]
        if query:
            predicates.append(
                or_(
                    GlobalJob.job_title.ilike(f"%{query}%"),
                    GlobalJob.company.ilike(f"%{query}%"),
                    GlobalJob.description.ilike(f"%{query}%"),
                )
            )
        if role:
            predicates.append(GlobalJob.role_family == role)
        if role_families:
            predicates.append(GlobalJob.role_family.in_(role_families))
        if location:
            predicates.append(GlobalJob.location.ilike(f"%{location}%"))
        if remote is not None:
            predicates.append(GlobalJob.remote.is_(remote))
        if employment_type:
            predicates.append(GlobalJob.employment_type.ilike(employment_type))
        statement = (
            select(GlobalJob)
            .where(*predicates)
            .order_by(
                GlobalJob.posted_at.desc().nullslast(), GlobalJob.last_seen_at.desc(), GlobalJob.id
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        rows = list(await session.scalars(statement))
        total = await session.scalar(select(func.count()).select_from(GlobalJob).where(*predicates))
        return rows, int(total or 0)

    async def by_id(self, session: AsyncSession, job_id: UUID) -> GlobalJob | None:
        return await session.get(GlobalJob, job_id)

    async def stats(self, session: AsyncSession) -> dict[str, object]:
        today = datetime.now(UTC) - timedelta(days=1)
        total = await session.scalar(select(func.count()).select_from(GlobalJob))
        active = await session.scalar(
            select(func.count()).select_from(GlobalJob).where(GlobalJob.is_active.is_(True))
        )
        recent = await session.scalar(
            select(func.count()).select_from(GlobalJob).where(GlobalJob.first_seen_at >= today)
        )
        by_source = dict(
            (row[0], row[1])
            for row in (
                await session.execute(
                    select(GlobalJob.source, func.count()).group_by(GlobalJob.source)
                )
            ).all()
        )
        by_role = dict(
            (row[0], row[1])
            for row in (
                await session.execute(
                    select(GlobalJob.role_family, func.count()).group_by(GlobalJob.role_family)
                )
            ).all()
        )
        return {
            "total_jobs": int(total or 0),
            "active_jobs": int(active or 0),
            "jobs_added_last_24_hours": int(recent or 0),
            "jobs_by_source": by_source,
            "jobs_by_role_family": by_role,
        }
