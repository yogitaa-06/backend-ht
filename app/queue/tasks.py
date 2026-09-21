"""ARQ tasks for source-neutral global job collection."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any, Literal

from arq import Retry
from pydantic import ValidationError

from app.db.session import Database
from app.domain.jobs import JobSource
from app.jobs.collection import CollectionCoordinator, CoordinatorResult
from app.jobs.errors import (
    PermanentCollectionError,
    SourceUnavailableError,
    TemporaryCollectionError,
)
from app.jobs.locks import CollectionLockManager
from app.jobs.registry import CollectorRegistry
from app.jobs.targets import CollectionTarget

logger = logging.getLogger(__name__)
CollectionStatus = Literal["success", "partial", "failed", "skipped_locked", "source_unavailable"]


def _result(
    target: CollectionTarget,
    *,
    started_at: datetime,
    status: CollectionStatus,
    lock_acquired: bool,
    coordinator: CoordinatorResult | None = None,
) -> dict[str, object]:
    finished_at = coordinator.finished_at if coordinator else datetime.now(UTC)
    return {
        "source": target.source.value,
        "query": target.query,
        "location": target.location,
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "duration_seconds": (finished_at - started_at).total_seconds(),
        "jobs_discovered": coordinator.jobs_discovered if coordinator else 0,
        "jobs_normalized": coordinator.jobs_normalized if coordinator else 0,
        "jobs_inserted": coordinator.jobs_inserted if coordinator else 0,
        "jobs_updated": coordinator.jobs_updated if coordinator else 0,
        "jobs_skipped": coordinator.jobs_skipped if coordinator else 0,
        "jobs_failed": coordinator.jobs_failed if coordinator else 0,
        "lock_acquired": lock_acquired,
        "status": status,
    }


async def run_job_collection(
    ctx: dict[str, Any],
    source: str,
    query: str,
    location: str | None,
    max_jobs: int,
) -> dict[str, object]:
    """Validate and execute one globally configured collection target."""
    started_at = datetime.now(UTC)
    try:
        target = CollectionTarget(
            source=JobSource(source), query=query, location=location, max_jobs=max_jobs
        )
    except (ValueError, ValidationError):
        finished_at = datetime.now(UTC)
        logger.warning("job_collection_failed", extra={"source": source, "status": "failed"})
        return {
            "source": source,
            "query": query,
            "location": location,
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
            "duration_seconds": (finished_at - started_at).total_seconds(),
            "jobs_discovered": 0,
            "jobs_normalized": 0,
            "jobs_inserted": 0,
            "jobs_updated": 0,
            "jobs_skipped": 0,
            "jobs_failed": 0,
            "lock_acquired": False,
            "status": "failed",
        }

    registry: CollectorRegistry = ctx["collector_registry"]
    try:
        collector = registry.resolve(target.source)
    except SourceUnavailableError:
        logger.warning(
            "job_collection_source_unavailable",
            extra={"source": source, "query": query, "location": location},
        )
        return _result(
            target,
            started_at=started_at,
            status="source_unavailable",
            lock_acquired=False,
        )

    locks: CollectionLockManager = ctx["collection_locks"]
    lease = await locks.acquire(target.identity)
    if lease is None:
        logger.info(
            "job_collection_skipped_locked",
            extra={"source": source, "query": query, "location": location},
        )
        return _result(target, started_at=started_at, status="skipped_locked", lock_acquired=False)

    logger.info(
        "job_collection_started",
        extra={"source": source, "query": query, "location": location},
    )
    try:
        database: Database = ctx["database"]
        coordinator: CollectionCoordinator = ctx["collection_coordinator"]
        async with database.sessions() as session, session.begin():
            outcome = await coordinator.run(session, collector, target)
        status: CollectionStatus = "partial" if outcome.jobs_failed else "success"
        result = _result(
            target,
            started_at=started_at,
            status=status,
            lock_acquired=True,
            coordinator=outcome,
        )
        logger.info("job_collection_completed", extra=result)
        return result
    except TemporaryCollectionError as exc:
        logger.warning(
            "job_collection_failed",
            extra={
                "source": source,
                "query": query,
                "location": location,
                "status": "retrying",
                "retry_after_seconds": exc.retry_after_seconds,
            },
        )
        raise Retry(defer=exc.retry_after_seconds) from None
    except PermanentCollectionError:
        result = _result(target, started_at=started_at, status="failed", lock_acquired=True)
        logger.exception("job_collection_failed", extra=result)
        return result
    except Exception:
        result = _result(target, started_at=started_at, status="failed", lock_acquired=True)
        logger.exception("job_collection_failed", extra=result)
        return result
    finally:
        try:
            released = await asyncio.shield(lease.release())
            if not released:
                logger.warning(
                    "job_collection_lock_expired",
                    extra={"source": source, "query": query, "location": location},
                )
        except Exception:
            logger.exception(
                "job_collection_lock_release_failed",
                extra={"source": source, "query": query, "location": location},
            )
