"""Persistence and read primitives for canonical global jobs."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import ColumnElement, exists, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.jobs import CanonicalJob, Company, JobSourceObservation
from app.jobs.canonicalization import build_canonical_hash
from app.jobs.normalization import NormalizedJob


@dataclass(frozen=True)
class CanonicalJobRead:
    """API-facing representation of one canonical job.

    A canonical job may have multiple provider observations. This read model
    exposes one deterministic active source observation while preserving one
    result row per real-world job.
    """

    id: UUID
    source: str
    external_job_id: str
    job_title: str
    role_family: str
    company: str | None
    location: str | None
    job_url: str | None
    description: str | None
    salary_text: str | None
    employment_type: str | None
    remote: bool | None
    skills: list[str]
    posted_at: datetime | None
    source_updated_at: datetime | None
    first_seen_at: datetime
    scraped_at: datetime
    experience_min_years: int | None
    experience_max_years: int | None
    experience_text: str | None
    last_seen_at: datetime
    is_active: bool


class CanonicalJobRepository:
    """Persist and query the canonical global-job graph."""

    async def lock_source_identity(
        self,
        session: AsyncSession,
        *,
        source: str,
        source_job_id: str,
    ) -> None:
        """Serialize ingestion of one provider identity for this transaction.

        The unique constraint remains the final correctness boundary. The
        transaction-scoped advisory lock avoids creating temporary orphan jobs
        when cooperative workers discover the same source listing concurrently.
        """

        digest = hashlib.sha256(f"{source}\0{source_job_id}".encode()).digest()

        lock_key = int.from_bytes(
            digest[:8],
            byteorder="big",
            signed=True,
        )

        await session.execute(select(func.pg_advisory_xact_lock(lock_key)))

    async def get_source(
        self,
        session: AsyncSession,
        *,
        source: str,
        source_job_id: str,
    ) -> JobSourceObservation | None:
        """Return a source observation when present."""

        observation: JobSourceObservation | None = await session.scalar(
            select(JobSourceObservation).where(
                JobSourceObservation.source == source,
                JobSourceObservation.source_job_id == source_job_id,
            )
        )

        return observation

    async def touch_sources_seen(
        self,
        session: AsyncSession,
        *,
        source: str,
        source_job_ids: tuple[str, ...],
        observed_at: datetime,
    ) -> int:
        """Refresh discovery time without claiming details were scraped."""

        if not source_job_ids:
            return 0

        job_ids = select(JobSourceObservation.job_id).where(
            JobSourceObservation.source == source,
            JobSourceObservation.source_job_id.in_(source_job_ids),
        )

        await session.execute(
            update(CanonicalJob)
            .where(CanonicalJob.id.in_(job_ids))
            .values(
                last_seen_at=observed_at,
                is_active=True,
            )
        )

        result = await session.execute(
            update(JobSourceObservation)
            .where(
                JobSourceObservation.source == source,
                JobSourceObservation.source_job_id.in_(source_job_ids),
            )
            .values(
                last_seen_at=observed_at,
                is_active=True,
            )
        )

        return int(getattr(result, "rowcount", 0) or 0)

    async def detail_fetched_by_source_id(
        self,
        session: AsyncSession,
        *,
        source: str,
        source_job_ids: tuple[str, ...],
    ) -> dict[str, bool]:
        """Identify detail observations rather than migration-only stubs."""
        if not source_job_ids:
            return {}
        rows = await session.execute(
            select(
                JobSourceObservation.source_job_id,
                JobSourceObservation.raw_data,
            ).where(
                JobSourceObservation.source == source,
                JobSourceObservation.source_job_id.in_(source_job_ids),
            )
        )
        return {
            source_job_id: bool(raw_data) and "legacy_global_job_id" not in raw_data
            for source_job_id, raw_data in rows
        }

    async def resolve_company(
        self,
        session: AsyncSession,
        *,
        name: str,
        normalized_name: str,
    ) -> tuple[Company, bool]:
        """Create or reuse company on exact normalized-name match."""

        statement = (
            insert(Company)
            .values(
                name=name,
                normalized_name=normalized_name,
            )
            .on_conflict_do_nothing(index_elements=[Company.normalized_name])
            .returning(Company)
        )

        company = await session.scalar(statement)

        if company is not None:
            return company, True

        company = await session.scalar(
            select(Company).where(Company.normalized_name == normalized_name)
        )

        if company is None:  # pragma: no cover
            raise RuntimeError("company conflict did not resolve to an existing row")

        return company, False

    async def find_job_by_source_url(
        self,
        session: AsyncSession,
        *,
        source: str,
        source_url: str | None,
    ) -> CanonicalJob | None:
        """Reuse a canonical job only for exact same-provider URL."""

        if source_url is None:
            return None

        canonical: CanonicalJob | None = await session.scalar(
            select(CanonicalJob)
            .join(JobSourceObservation)
            .where(
                JobSourceObservation.source == source,
                JobSourceObservation.source_url == source_url,
            )
            .limit(1)
        )

        return canonical

    async def create_job(
        self,
        session: AsyncSession,
        job: NormalizedJob,
        *,
        company: Company | None,
        observed_at: datetime,
    ) -> CanonicalJob:
        """Create a canonical job from normalized source data."""

        canonical = CanonicalJob(
            company_id=company.id if company else None,
            title=job.job_title,
            normalized_title=job.normalized_title,
            description=job.description,
            location=job.location,
            normalized_location=job.normalized_location,
            employment_type=job.employment_type,
            remote_type=_remote_type(job.remote),
            skills=job.skills,
            experience_min_years=job.experience_min_years,
            experience_max_years=job.experience_max_years,
            experience_text=job.experience_text,
            role_family=job.role_family,
            salary_text=job.salary_text,
            posted_at=job.posted_at,
            source_updated_at=job.source_updated_at,
            first_seen_at=observed_at,
            last_seen_at=observed_at,
            is_active=True,
            canonical_hash=build_canonical_hash(job),
        )

        session.add(canonical)
        await session.flush()

        return canonical

    async def create_source(
        self,
        session: AsyncSession,
        job: NormalizedJob,
        *,
        canonical_job: CanonicalJob,
        observed_at: datetime,
    ) -> JobSourceObservation:
        """Create the provider observation for a canonical job."""

        source = JobSourceObservation(
            job_id=canonical_job.id,
            source=job.source,
            source_job_id=job.external_job_id,
            source_url=job.job_url,
            source_posted_at=job.posted_at,
            source_updated_at=job.source_updated_at,
            first_seen_at=observed_at,
            last_seen_at=observed_at,
            scraped_at=observed_at,
            content_hash=job.content_hash,
            is_active=True,
            raw_data=job.raw_data,
        )

        session.add(source)
        await session.flush()

        return source

    async def refresh_source(
        self,
        session: AsyncSession,
        source: JobSourceObservation,
        job: NormalizedJob,
        *,
        company: Company | None,
        observed_at: datetime,
        content_changed: bool,
    ) -> None:
        """Refresh observation and apply mutable content when changed."""

        source.last_seen_at = observed_at
        source.scraped_at = observed_at
        source.is_active = True

        canonical = await session.get(
            CanonicalJob,
            source.job_id,
        )

        if canonical is None:
            raise RuntimeError("source observation references a missing canonical job")

        canonical.last_seen_at = observed_at
        canonical.is_active = True

        source.source_url = _prefer_text(job.job_url, source.source_url)
        source.source_posted_at = job.posted_at or source.source_posted_at
        source.source_updated_at = job.source_updated_at or source.source_updated_at
        source.raw_data = job.raw_data or source.raw_data
        if content_changed:
            source.content_hash = job.content_hash

        canonical.company_id = company.id if company else canonical.company_id
        if job.job_title and not job.job_title.startswith("Unknown "):
            canonical.title = job.job_title
            canonical.normalized_title = job.normalized_title
        canonical.description = _prefer_text(job.description, canonical.description)
        if _has_text(job.location):
            canonical.location = job.location
            canonical.normalized_location = job.normalized_location
        canonical.employment_type = _prefer_text(job.employment_type, canonical.employment_type)
        canonical.remote_type = _remote_type(job.remote) or canonical.remote_type
        canonical.skills = job.skills or canonical.skills
        canonical.experience_min_years = (
            job.experience_min_years
            if job.experience_min_years is not None
            else canonical.experience_min_years
        )
        canonical.experience_max_years = (
            job.experience_max_years
            if job.experience_max_years is not None
            else canonical.experience_max_years
        )
        canonical.experience_text = _prefer_text(job.experience_text, canonical.experience_text)
        canonical.role_family = job.role_family
        canonical.salary_text = _prefer_text(job.salary_text, canonical.salary_text)

        canonical.posted_at = job.posted_at or canonical.posted_at

        canonical.source_updated_at = job.source_updated_at or canonical.source_updated_at

        if job.normalized_company and job.normalized_location and job.posted_at:
            canonical.canonical_hash = build_canonical_hash(job)

        await session.flush()

    async def search(
        self,
        session: AsyncSession,
        *,
        query: str | None = None,
        role: str | None = None,
        location: str | None = None,
        remote: bool | None = None,
        employment_type: str | None = None,
        source: str | None = None,
        role_families: Sequence[str] | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[CanonicalJobRead], int]:
        """Search canonical jobs without duplicating multi-source openings."""

        source_predicates: list[ColumnElement[bool]] = [
            JobSourceObservation.job_id == CanonicalJob.id,
            JobSourceObservation.is_active.is_(True),
        ]
        if source:
            source_predicates.append(JobSourceObservation.source == source)

        predicates: list[ColumnElement[bool]] = [
            CanonicalJob.is_active.is_(True),
            exists(select(JobSourceObservation.id).where(*source_predicates)),
        ]

        if query:
            pattern = f"%{query}%"

            predicates.append(
                or_(
                    CanonicalJob.title.ilike(pattern),
                    Company.name.ilike(pattern),
                    CanonicalJob.description.ilike(pattern),
                )
            )

        if role:
            predicates.append(CanonicalJob.role_family == role)

        if role_families:
            predicates.append(CanonicalJob.role_family.in_(role_families))

        if location:
            predicates.append(CanonicalJob.location.ilike(f"%{location}%"))

        if remote is not None:
            predicates.append(CanonicalJob.remote_type == ("remote" if remote else "on_site"))

        if employment_type:
            predicates.append(CanonicalJob.employment_type.ilike(employment_type))

        statement = (
            select(
                CanonicalJob,
                Company.name.label("company_name"),
            )
            .outerjoin(
                Company,
                Company.id == CanonicalJob.company_id,
            )
            .where(*predicates)
            .order_by(
                CanonicalJob.posted_at.desc().nullslast(),
                CanonicalJob.last_seen_at.desc(),
                CanonicalJob.id,
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        )

        result = await session.execute(statement)

        canonical_rows = result.all()

        total = await session.scalar(
            select(func.count())
            .select_from(CanonicalJob)
            .outerjoin(
                Company,
                Company.id == CanonicalJob.company_id,
            )
            .where(*predicates)
        )

        reads: list[CanonicalJobRead] = []

        for canonical, company_name in canonical_rows:
            observation = await self._presentation_source(
                session,
                canonical.id,
            )

            if observation is None:
                continue

            reads.append(
                CanonicalJobRead(
                    id=canonical.id,
                    source=str(observation.source),
                    external_job_id=observation.source_job_id,
                    job_title=canonical.title,
                    role_family=canonical.role_family,
                    company=company_name,
                    location=canonical.location,
                    job_url=observation.source_url,
                    description=canonical.description,
                    salary_text=canonical.salary_text,
                    employment_type=canonical.employment_type,
                    remote=_remote_bool(canonical.remote_type),
                    skills=list(canonical.skills or []),
                    posted_at=canonical.posted_at,
                    source_updated_at=observation.source_updated_at,
                    first_seen_at=observation.first_seen_at,
                    scraped_at=observation.scraped_at,
                    experience_min_years=(canonical.experience_min_years),
                    experience_max_years=(canonical.experience_max_years),
                    experience_text=(canonical.experience_text),
                    last_seen_at=observation.last_seen_at,
                    is_active=canonical.is_active,
                )
            )

        return reads, int(total or 0)

    async def _presentation_source(
        self,
        session: AsyncSession,
        job_id: UUID,
    ) -> JobSourceObservation | None:
        """Choose one deterministic active provider for API presentation."""

        observation: JobSourceObservation | None = await session.scalar(
            select(JobSourceObservation)
            .where(
                JobSourceObservation.job_id == job_id,
                JobSourceObservation.is_active.is_(True),
            )
            .order_by(
                JobSourceObservation.last_seen_at.desc(),
                JobSourceObservation.first_seen_at.asc(),
                JobSourceObservation.source.asc(),
                JobSourceObservation.source_job_id.asc(),
            )
            .limit(1)
        )
        return observation


def _remote_type(
    remote: bool | None,
) -> str | None:
    """Convert compatibility boolean into canonical remote type."""

    if remote is None:
        return None

    return "remote" if remote else "on_site"


def _remote_bool(
    remote_type: str | None,
) -> bool | None:
    """Convert canonical remote type into compatibility API boolean."""

    if remote_type is None:
        return None

    if remote_type == "remote":
        return True

    if remote_type == "on_site":
        return False

    return None


def _has_text(value: str | None) -> bool:
    return bool(value and value.strip())


def _prefer_text(incoming: str | None, existing: str | None) -> str | None:
    return incoming if _has_text(incoming) else existing
