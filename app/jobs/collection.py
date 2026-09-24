"""Source-neutral job collection business orchestration."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.jobs.ingestion import CanonicalJobIngestionService
from app.jobs.normalization import NormalizedJob, RawSourceJob, normalize_job
from app.jobs.registry import JobSourceCollector
from app.jobs.targets import CollectionTarget
from app.repositories.jobs import (
    GlobalJobRepository,
    JobUpsertResult,
    JobUpsertStatus,
)

logger = logging.getLogger(__name__)


class LegacyJobPersistence(Protocol):
    async def get_existing_by_external_ids(
        self, session: AsyncSession, source: str, external_ids: Sequence[str]
    ) -> Mapping[str, ExistingLegacyJob]: ...

    async def touch_seen(
        self,
        session: AsyncSession,
        source: str,
        external_ids: Sequence[str],
        *,
        seen_at: datetime | None = None,
    ) -> int: ...

    async def upsert_with_outcome(
        self, session: AsyncSession, job: NormalizedJob
    ) -> JobUpsertResult: ...


class CanonicalIngestion(Protocol):
    async def ingest(self, session: AsyncSession, job: NormalizedJob) -> object: ...

    async def touch_seen(
        self, session: AsyncSession, *, source: str, source_job_ids: list[str]
    ) -> int: ...


class ExistingLegacyJob(Protocol):
    scraped_at: datetime


@dataclass(frozen=True)
class CoordinatorResult:
    """Truthful persistence statistics from one collector invocation."""

    started_at: datetime
    finished_at: datetime
    jobs_discovered: int
    jobs_normalized: int
    jobs_inserted: int
    jobs_updated: int
    jobs_skipped: int
    jobs_failed: int
    canonical_jobs_failed: int = 0
    details_fetched: int = 0
    details_skipped_recent: int = 0

    @property
    def duration_seconds(self) -> float:
        return (self.finished_at - self.started_at).total_seconds()


class CollectionCoordinator:
    """Collect, normalize, and persist jobs; queue and lock concerns live elsewhere."""

    def __init__(
        self,
        repository: LegacyJobPersistence | None = None,
        canonical_ingestion: CanonicalIngestion | None = None,
    ) -> None:
        self.repository = repository or GlobalJobRepository()
        self.canonical_ingestion = canonical_ingestion or CanonicalJobIngestionService()

    async def run(
        self,
        session: AsyncSession,
        collector: JobSourceCollector,
        target: CollectionTarget,
    ) -> CoordinatorResult:
        started = datetime.now(UTC)

        # Keep the pre-checkpoint contract usable for existing adapters while
        # new adapters can separate discovery from detail fetching.
        discover = getattr(collector, "discover", None)
        fetch_details = getattr(collector, "fetch_details", None)
        if discover is None or fetch_details is None:
            legacy_collect = getattr(collector, "collect", None)
            if legacy_collect is None:
                raise TypeError("collector does not support discovery or collection")
            raw_jobs = await legacy_collect(target)
            return await self._persist_raw_jobs(session, target, raw_jobs, started=started)

        candidates = tuple(await discover(target))
        unique_candidates = tuple(
            {candidate.external_job_id: candidate for candidate in candidates}.values()
        )
        existing = await self.repository.get_existing_by_external_ids(
            session,
            target.source.value,
            [candidate.external_job_id for candidate in unique_candidates],
        )
        refresh_before = datetime.now(UTC) - timedelta(hours=6)
        recent_ids = [
            candidate.external_job_id
            for candidate in unique_candidates
            if candidate.external_job_id in existing
            and existing[candidate.external_job_id].scraped_at >= refresh_before
        ]
        if recent_ids:
            await self.repository.touch_seen(session, target.source.value, recent_ids)
            await self.canonical_ingestion.touch_seen(
                session, source=target.source.value, source_job_ids=recent_ids
            )
        detail_candidates = tuple(
            candidate
            for candidate in unique_candidates
            if candidate.external_job_id not in recent_ids
        )
        raw_jobs = await fetch_details(target, detail_candidates)
        result = await self._persist_raw_jobs(
            session,
            target,
            raw_jobs,
            started=started,
        )
        return CoordinatorResult(
            **{
                **result.__dict__,
                "jobs_discovered": len(unique_candidates),
                "details_fetched": len(raw_jobs),
                "details_skipped_recent": len(recent_ids),
            }
        )

    async def _persist_raw_jobs(
        self,
        session: AsyncSession,
        target: CollectionTarget,
        raw_jobs: Sequence[RawSourceJob],
        *,
        started: datetime,
    ) -> CoordinatorResult:
        """Normalize and persist detail jobs using the existing upsert path."""
        normalized = inserted = updated = skipped = failed = canonical_failed = 0

        for raw in raw_jobs:
            try:
                if raw.source != target.source.value:
                    raise ValueError("collector returned a job for a different source")
                canonical = normalize_job(raw)
                normalized += 1
                async with session.begin_nested():
                    outcome = await self.repository.upsert_with_outcome(session, canonical)
                if outcome.status is JobUpsertStatus.INSERTED:
                    inserted += 1
                elif outcome.status is JobUpsertStatus.UPDATED:
                    updated += 1
                else:
                    skipped += 1
                try:
                    # Canonical writes use their own savepoint so a transition-path
                    # failure cannot discard the established global_jobs write.
                    async with session.begin_nested():
                        await self.canonical_ingestion.ingest(session, canonical)
                except Exception:
                    canonical_failed += 1
                    logger.exception(
                        "job_ingestion_failed",
                        extra={
                            "source": canonical.source,
                            "source_job_id": canonical.external_job_id,
                            "action": "canonical_dual_write",
                        },
                    )
            except Exception:
                failed += 1
                logger.exception(
                    "job_collection_item_failed",
                    extra={
                        "source": target.source.value,
                        "query": target.query,
                        "location": target.location,
                    },
                )

        return CoordinatorResult(
            started_at=started,
            finished_at=datetime.now(UTC),
            jobs_discovered=len(raw_jobs),
            jobs_normalized=normalized,
            jobs_inserted=inserted,
            jobs_updated=updated,
            jobs_skipped=skipped,
            jobs_failed=failed,
            canonical_jobs_failed=canonical_failed,
            details_fetched=len(raw_jobs),
        )
