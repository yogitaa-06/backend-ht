"""Source-neutral job collection business orchestration."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.jobs.normalization import normalize_job
from app.jobs.registry import JobSourceCollector
from app.jobs.targets import CollectionTarget
from app.repositories.jobs import GlobalJobRepository, JobUpsertStatus

logger = logging.getLogger(__name__)


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

    @property
    def duration_seconds(self) -> float:
        return (self.finished_at - self.started_at).total_seconds()


class CollectionCoordinator:
    """Collect, normalize, and persist jobs; queue and lock concerns live elsewhere."""

    def __init__(self, repository: GlobalJobRepository | None = None) -> None:
        self.repository = repository or GlobalJobRepository()

    async def run(
        self,
        session: AsyncSession,
        collector: JobSourceCollector,
        target: CollectionTarget,
    ) -> CoordinatorResult:
        started = datetime.now(UTC)
        raw_jobs = await collector.collect(target)
        normalized = inserted = updated = skipped = failed = 0

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
        )
