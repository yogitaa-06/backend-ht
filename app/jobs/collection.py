"""Source-neutral collection contracts and non-overlapping scheduling."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.jobs.normalization import RawSourceJob, normalize_job
from app.repositories.jobs import GlobalJobRepository

logger = logging.getLogger(__name__)


class JobSourceCollector:
    """Adapter contract implemented independently by Dice, LinkedIn, and Glassdoor."""

    source: str

    async def collect(self, target: str, *, max_jobs: int) -> Sequence[RawSourceJob]:
        raise NotImplementedError


@dataclass(frozen=True)
class CollectionResult:
    source: str
    target: str
    started_at: datetime
    finished_at: datetime
    discovered: int
    persisted: int
    failed: int


class CollectionCoordinator:
    """Normalize and upsert one source run behind a caller-provided lock."""

    def __init__(self, repository: GlobalJobRepository | None = None) -> None:
        self.repository = repository or GlobalJobRepository()
        self._locks: dict[str, asyncio.Lock] = {}

    async def run(
        self, session: AsyncSession, collector: JobSourceCollector, target: str, *, max_jobs: int
    ) -> CollectionResult:
        lock = self._locks.setdefault(collector.source, asyncio.Lock())
        if lock.locked():
            raise RuntimeError(f"collection already running for {collector.source}")
        started = datetime.now(UTC)
        async with lock:
            raw_jobs = await collector.collect(target, max_jobs=max_jobs)
            failed = 0
            persisted = 0
            for raw in raw_jobs:
                try:
                    await self.repository.upsert(session, normalize_job(raw))
                    persisted += 1
                except Exception:
                    failed += 1
                    logger.exception(
                        "job_collection_item_failed",
                        extra={"source": collector.source, "target": target},
                    )
            finished = datetime.now(UTC)
            logger.info(
                "job_collection_finished",
                extra={
                    "source": collector.source,
                    "target": target,
                    "started_at": started.isoformat(),
                    "finished_at": finished.isoformat(),
                    "jobs_discovered": len(raw_jobs),
                    "jobs_updated_or_created": persisted,
                    "failed_jobs": failed,
                    "duration_seconds": (finished - started).total_seconds(),
                },
            )
            return CollectionResult(
                collector.source, target, started, finished, len(raw_jobs), persisted, failed
            )


async def scheduled_collection_loop(
    task: Callable[[], Awaitable[None]], interval_seconds: int, *, stop: asyncio.Event
) -> None:
    """Run a platform collection task on a configurable interval."""
    while not stop.is_set():
        await task()
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval_seconds)
        except TimeoutError:
            continue
