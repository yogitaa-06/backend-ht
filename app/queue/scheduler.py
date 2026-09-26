"""ARQ scheduler that enqueues due platform collection targets."""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from arq.connections import ArqRedis

from app.core.config import Settings
from app.domain.jobs import JobSource
from app.domain.profiles import Profile
from app.domain.resumes import CandidateProfile, Resume, ResumeStatus
from app.db.session import Database
from app.jobs.registry import CollectorRegistry
from app.jobs.targets import CollectionTarget
from sqlalchemy import select

logger = logging.getLogger(__name__)


def source_interval_minutes(settings: Settings, source: JobSource) -> int:
    """Resolve source cadence from one typed configuration boundary."""
    return {
        JobSource.DICE: settings.dice_collection_interval_minutes,
        JobSource.LINKEDIN: settings.linkedin_collection_interval_minutes,
        JobSource.GLASSDOOR: settings.glassdoor_collection_interval_minutes,
        JobSource.HIRINGCAFE: settings.hiringcafe_collection_interval_minutes,
    }[source]


def enabled_targets(settings: Settings) -> tuple[CollectionTarget, ...]:
    """Remove disabled and exact duplicate network searches."""
    unique: dict[str, CollectionTarget] = {}
    for target in settings.job_collection_targets:
        if target.enabled:
            unique.setdefault(target.identity, target)
    return tuple(unique.values())


async def schedule_due_collections(ctx: dict[str, Any]) -> dict[str, int | str]:
    """Atomically claim due sources and isolate failures per target."""
    settings: Settings = ctx["settings"]
    if not settings.job_collection_enabled:
        return {"status": "disabled", "enqueued": 0, "failed": 0, "unavailable": 0}

    redis: ArqRedis = ctx["redis"]
    registry: CollectorRegistry = ctx["collector_registry"]
    database: Database | None = ctx.get("database")
    
    # 1. Build dynamic targets from active user resumes
    dynamic_targets: list[CollectionTarget] = []
    
    if database is not None:
        async with database.sessions() as session:
            profiles_result = await session.execute(
                select(CandidateProfile)
                .join(Resume, CandidateProfile.resume_id == Resume.id)
                .where(Resume.deleted_at.is_(None), Resume.status == ResumeStatus.PARSED)
            )
            for profile in profiles_result.scalars():
                query_sources = [JobSource.DICE, JobSource.LINKEDIN, JobSource.GLASSDOOR, JobSource.HIRINGCAFE]
                
                # Priority 1: Current Title
                if profile.current_title:
                    for src in query_sources:
                        dynamic_targets.append(
                            CollectionTarget(
                                source=src,
                                query=profile.current_title,
                                location=profile.location or "United States"
                            )
                        )
                
                # Priority 2: Top Skills (if they have them)
                if profile.skills:
                    top_skills = " ".join(profile.skills[:3])
                    if top_skills:
                        for src in query_sources:
                            dynamic_targets.append(
                                CollectionTarget(
                                    source=src,
                                    query=top_skills,
                                    location=profile.location or "United States"
                                )
                            )
    else:
        dynamic_targets.extend(enabled_targets(settings))
    
    # 2. Combine and deduplicate
    unique_targets: dict[str, CollectionTarget] = {}
        
    # Add dynamic targets
    for target in dynamic_targets:
        if target.enabled:
            unique_targets.setdefault(target.identity, target)
            
    # Fallback to enabled_targets or software engineer @ United States if NO targets were generated
    if not unique_targets:
        fallback = enabled_targets(settings)
        if fallback:
            for t in fallback:
                unique_targets.setdefault(t.identity, t)
        else:
            for src in [JobSource.DICE, JobSource.LINKEDIN, JobSource.GLASSDOOR, JobSource.HIRINGCAFE]:
                t = CollectionTarget(
                    source=src,
                    query="software engineer",
                    location="United States"
                )
                unique_targets.setdefault(t.identity, t)
            
    # Limit to MAX_QUERIES = 100 per source
    grouped: dict[JobSource, list[CollectionTarget]] = defaultdict(list)
    for target in unique_targets.values():
        if len(grouped[target.source]) < 100:
            grouped[target.source].append(target)

    enqueued = failed = unavailable = 0
    now = datetime.now(UTC)
    for source, targets in grouped.items():
        if not registry.is_registered(source):
            unavailable += len(targets)
            logger.warning(
                "job_collection_source_unavailable",
                extra={"source": source.value, "target_count": len(targets)},
            )
            continue

        interval_seconds = source_interval_minutes(settings, source) * 60
        due_key = f"{settings.job_collection_redis_namespace}:scheduler:{source.value}"
        claimed = await redis.set(due_key, now.isoformat(), nx=True, ex=interval_seconds)
        if not claimed:
            continue
        window = int(now.timestamp()) // interval_seconds
        for target in targets:
            try:
                job = await redis.enqueue_job(
                    "run_job_collection",
                    target.source.value,
                    target.query,
                    target.location,
                    min(target.max_jobs, settings.job_collection_max_jobs_per_target),
                    _job_id=f"collection:{target.identity}:{window}",
                    _queue_name=settings.job_collection_queue_name,
                )
                if job is not None:
                    enqueued += 1
                    logger.info(
                        "job_collection_enqueued",
                        extra={
                            "source": target.source.value,
                            "query": target.query,
                            "location": target.location,
                        },
                    )
            except Exception:
                failed += 1
                logger.exception(
                    "job_collection_enqueue_failed",
                    extra={
                        "source": target.source.value,
                        "query": target.query,
                        "location": target.location,
                    },
                )
    return {
        "status": "completed",
        "enqueued": enqueued,
        "failed": failed,
        "unavailable": unavailable,
    }
