"""Source-independent orchestration for canonical job ingestion."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.jobs import CanonicalJob, Company, JobSourceObservation
from app.jobs.normalization import NormalizedJob
from app.repositories.canonical_jobs import CanonicalJobRepository

logger = logging.getLogger(__name__)


class IngestionAction(StrEnum):
    CREATED = "created"
    REOBSERVED = "reobserved"
    UPDATED = "updated"


@dataclass(frozen=True)
class IngestionResult:
    """Canonical identities and mutation outcome for one source listing."""

    company: Company | None
    job: CanonicalJob
    source: JobSourceObservation
    action: IngestionAction


class Clock(Protocol):
    def __call__(self) -> datetime: ...


class CanonicalJobIngestionService:
    """Resolve and persist normalized listings without source-specific logic.

    The caller owns the transaction. A failure therefore rolls back company,
    canonical job, and source observation together.
    """

    def __init__(
        self,
        repository: CanonicalJobRepository | None = None,
        *,
        clock: Clock | None = None,
    ) -> None:
        self.repository = repository or CanonicalJobRepository()
        self.clock = clock or (lambda: datetime.now(UTC))

    async def ingest(self, session: AsyncSession, job: NormalizedJob) -> IngestionResult:
        """Ingest one normalized listing with deterministic source deduplication."""
        observed_at = self.clock()
        await self.repository.lock_source_identity(
            session, source=job.source, source_job_id=job.external_job_id
        )
        existing_source = await self.repository.get_source(
            session, source=job.source, source_job_id=job.external_job_id
        )
        if existing_source is not None:
            content_changed = existing_source.content_hash != job.content_hash
            company, company_created = await self._resolve_company(session, job, True)
            await self.repository.refresh_source(
                session,
                existing_source,
                job,
                company=company,
                observed_at=observed_at,
                content_changed=content_changed,
            )
            canonical = await session.get(CanonicalJob, existing_source.job_id)
            if canonical is None:  # pragma: no cover - guarded by repository integrity check
                raise RuntimeError("canonical job disappeared during ingestion")
            if company is None and canonical.company_id is not None:
                company = await session.get(Company, canonical.company_id)
            action = IngestionAction.UPDATED if content_changed else IngestionAction.REOBSERVED
            self._log_result(
                action,
                job,
                canonical,
                company,
                company_created=company_created,
            )
            return IngestionResult(company, canonical, existing_source, action)

        company, company_created = await self._resolve_company(session, job, True)
        canonical = await self.repository.find_job_by_source_url(
            session, source=job.source, source_url=job.job_url
        )
        canonical_created = canonical is None
        if canonical is None:
            # A canonical hash is a candidate-search aid, not identity proof. Two
            # Dice IDs with matching text may still be separate requisitions.
            canonical = await self.repository.create_job(
                session, job, company=company, observed_at=observed_at
            )
        else:
            canonical.last_seen_at = observed_at
            canonical.is_active = True
        source = await self.repository.create_source(
            session, job, canonical_job=canonical, observed_at=observed_at
        )
        self._log_result(
            IngestionAction.CREATED,
            job,
            canonical,
            company,
            company_created=company_created,
            canonical_created=canonical_created,
        )
        return IngestionResult(company, canonical, source, IngestionAction.CREATED)

    async def touch_seen(
        self, session: AsyncSession, *, source: str, source_job_ids: list[str]
    ) -> int:
        """Record search-result discovery without changing scraped_at."""
        return await self.repository.touch_sources_seen(
            session,
            source=source,
            source_job_ids=tuple(dict.fromkeys(source_job_ids)),
            observed_at=self.clock(),
        )

    async def detail_fetched_by_source_id(
        self, session: AsyncSession, *, source: str, source_job_ids: list[str]
    ) -> Mapping[str, bool]:
        """Report which identities have a persisted source-detail payload."""
        return await self.repository.detail_fetched_by_source_id(
            session,
            source=source,
            source_job_ids=tuple(dict.fromkeys(source_job_ids)),
        )

    async def _resolve_company(
        self, session: AsyncSession, job: NormalizedJob, required: bool
    ) -> tuple[Company | None, bool]:
        if not required or job.company is None or job.normalized_company is None:
            return None, False
        return await self.repository.resolve_company(
            session, name=job.company, normalized_name=job.normalized_company
        )

    @staticmethod
    def _log_result(
        action: IngestionAction,
        source_job: NormalizedJob,
        canonical: CanonicalJob,
        company: Company | None,
        *,
        company_created: bool,
        canonical_created: bool = False,
    ) -> None:
        logger.info(
            "job_ingestion_completed",
            extra={
                "source": source_job.source,
                "source_job_id": source_job.external_job_id,
                "job_id": canonical.id,
                "company_id": company.id if company else None,
                "action": action.value,
                "company_resolution": "created" if company_created else "reused_or_unavailable",
                "canonicalization_result": "created" if canonical_created else "reused",
            },
        )
