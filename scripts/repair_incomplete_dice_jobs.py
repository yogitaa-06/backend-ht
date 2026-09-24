"""Explicit, bounded repair for incomplete canonical Dice jobs.

The default mode is read-only. Local repair replays trustworthy ``global_jobs``
fields through normalization and canonical ingestion. Live repair fetches detail
pages only for rows that cannot be improved from local legacy data.
"""

# ruff: noqa: S608 -- dynamic SQL is composed only from module-owned constants.

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select, text

from app.core.config import Settings
from app.db.session import Database
from app.domain.jobs import GlobalJob, JobSource
from app.jobs.collection import CollectionCoordinator
from app.jobs.ingestion import CanonicalJobIngestionService
from app.jobs.normalization import DiscoveredSourceJob, RawSourceJob, normalize_job
from app.jobs.sources.dice import DiceCollector
from app.jobs.targets import CollectionTarget


@dataclass(frozen=True)
class RepairCandidate:
    source_job_id: str
    title: str
    source_url: str | None


_INCOMPLETE_SQL = """
    j.company_id IS NULL
    OR nullif(btrim(j.location), '') IS NULL
    OR nullif(btrim(j.description), '') IS NULL
    OR nullif(btrim(j.employment_type), '') IS NULL
    OR j.posted_at IS NULL
"""

_LOCAL_IMPROVEMENT_SQL = """
    (j.company_id IS NULL AND nullif(btrim(g.company), '') IS NOT NULL)
    OR (nullif(btrim(j.location), '') IS NULL AND nullif(btrim(g.location), '') IS NOT NULL)
    OR (nullif(btrim(j.description), '') IS NULL AND nullif(btrim(g.description), '') IS NOT NULL)
    OR (
        nullif(btrim(j.employment_type), '') IS NULL
        AND nullif(btrim(g.employment_type), '') IS NOT NULL
    )
    OR (j.posted_at IS NULL AND g.posted_at IS NOT NULL)
"""

_REPORT_SQL = f"""
    SELECT
        count(*) AS total,
        count(*) FILTER (WHERE j.company_id IS NOT NULL) AS with_company,
        count(*) FILTER (WHERE j.company_id IS NULL) AS missing_company,
        count(*) FILTER (WHERE nullif(btrim(j.location), '') IS NOT NULL) AS with_location,
        count(*) FILTER (WHERE nullif(btrim(j.location), '') IS NULL) AS missing_location,
        count(*) FILTER (WHERE nullif(btrim(j.description), '') IS NOT NULL) AS with_description,
        count(*) FILTER (WHERE nullif(btrim(j.description), '') IS NULL) AS missing_description,
        count(*) FILTER (
            WHERE nullif(btrim(j.employment_type), '') IS NOT NULL
        ) AS with_employment_type,
        count(*) FILTER (
            WHERE nullif(btrim(j.employment_type), '') IS NULL
        ) AS missing_employment_type,
        count(*) FILTER (WHERE j.posted_at IS NOT NULL) AS with_posted_at,
        count(*) FILTER (WHERE j.posted_at IS NULL) AS missing_posted_at,
        count(*) FILTER (
            WHERE jsonb_array_length(coalesce(j.skills, '[]'::jsonb)) > 0
        ) AS with_skills,
        count(*) FILTER (
            WHERE jsonb_array_length(coalesce(j.skills, '[]'::jsonb)) = 0
        ) AS empty_skills,
        count(*) FILTER (WHERE nullif(btrim(js.source_url), '') IS NOT NULL) AS with_source_url,
        count(*) FILTER (WHERE nullif(btrim(js.source_url), '') IS NULL) AS missing_source_url,
        count(*) FILTER (WHERE js.raw_data ? 'legacy_global_job_id') AS migration_stubs,
        count(*) FILTER (
            WHERE js.raw_data <> '{{}}'::jsonb AND NOT js.raw_data ? 'legacy_global_job_id'
        ) AS detail_payloads,
        count(*) FILTER (
            WHERE js.raw_data <> '{{}}'::jsonb
              AND NOT js.raw_data ? 'legacy_global_job_id'
              AND ({_INCOMPLETE_SQL})
        ) AS incomplete_detail_payloads,
        count(*) FILTER (WHERE {_LOCAL_IMPROVEMENT_SQL}) AS locally_repairable,
        count(*) FILTER (
            WHERE ({_LOCAL_IMPROVEMENT_SQL}) AND js.content_hash = g.content_hash
        ) AS locally_repairable_same_hash,
        count(*) FILTER (
            WHERE ({_LOCAL_IMPROVEMENT_SQL}) AND js.content_hash <> g.content_hash
        ) AS locally_repairable_changed_hash,
        count(*) FILTER (
            WHERE ({_INCOMPLETE_SQL}) AND NOT ({_LOCAL_IMPROVEMENT_SQL})
        ) AS requiring_detail_fetch
    FROM hireandtech.jobs AS j
    JOIN hireandtech.job_sources AS js ON js.job_id = j.id
    LEFT JOIN hireandtech.global_jobs AS g
      ON g.source = js.source AND g.external_job_id = js.source_job_id
    WHERE js.source = 'dice'
"""

_LIVE_CANDIDATES_SQL = f"""
    SELECT js.source_job_id, j.title, js.source_url
    FROM hireandtech.job_sources AS js
    JOIN hireandtech.jobs AS j ON j.id = js.job_id
    LEFT JOIN hireandtech.global_jobs AS g
      ON g.source = js.source AND g.external_job_id = js.source_job_id
    WHERE js.source = 'dice'
      AND ({_INCOMPLETE_SQL})
      AND NOT ({_LOCAL_IMPROVEMENT_SQL})
    ORDER BY js.source_job_id
    LIMIT :limit
"""

_SAMPLE_COLUMNS = """
    js.source_job_id, j.id, j.title, c.name AS company, j.location,
    length(j.description) AS description_length, j.employment_type, j.posted_at,
    j.remote_type, j.skills, js.source_url, js.source_posted_at,
    js.first_seen_at, js.last_seen_at, js.scraped_at,
    (js.raw_data ? 'legacy_global_job_id') AS migration_stub,
    (js.raw_data <> '{}'::jsonb AND NOT js.raw_data ? 'legacy_global_job_id') AS detail_payload,
    g.company AS legacy_company, g.location AS legacy_location,
    length(g.description) AS legacy_description_length,
    g.employment_type AS legacy_employment_type, g.posted_at AS legacy_posted_at
"""

_SAMPLE_FROM = """
    FROM hireandtech.job_sources AS js
    JOIN hireandtech.jobs AS j ON j.id = js.job_id
    LEFT JOIN hireandtech.companies AS c ON c.id = j.company_id
    LEFT JOIN hireandtech.global_jobs AS g
      ON g.source = js.source AND g.external_job_id = js.source_job_id
"""


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group()
    action.add_argument(
        "--apply-local",
        action="store_true",
        help="Replay richer legacy rows through canonical ingestion without network access.",
    )
    action.add_argument(
        "--fetch-live",
        action="store_true",
        help="Fetch Dice details for rows that have no useful local legacy enrichment.",
    )
    parser.add_argument("--limit", type=int, default=5, help="Maximum rows to repair (default: 5).")
    parser.add_argument(
        "--samples", action="store_true", help="Print one complete and one incomplete trace row."
    )
    args = parser.parse_args()
    if args.limit < 1:
        parser.error("--limit must be at least 1")
    return args


async def _report(database: Database) -> None:
    async with database.sessions() as session:
        await session.execute(text("SET TRANSACTION READ ONLY"))
        row = (await session.execute(text(_REPORT_SQL))).mappings().one()
        for key, value in row.items():
            print(f"{key}: {value}")


async def _samples(database: Database) -> None:
    async with database.sessions() as session:
        await session.execute(text("SET TRANSACTION READ ONLY"))
        complete = (
            (
                await session.execute(
                    text(
                        f"""
                    SELECT {_SAMPLE_COLUMNS}
                    {_SAMPLE_FROM}
                    WHERE js.source = 'dice' AND j.company_id IS NOT NULL
                      AND nullif(btrim(j.description), '') IS NOT NULL
                    ORDER BY js.source_job_id LIMIT 1
                    """
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        incomplete = (
            (
                await session.execute(
                    text(
                        f"""
                    SELECT {_SAMPLE_COLUMNS}
                    {_SAMPLE_FROM}
                    WHERE js.source = 'dice' AND j.title = 'Senior Security Engineer'
                      AND j.company_id IS NULL
                    ORDER BY js.source_job_id LIMIT 1
                    """
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        named = await session.scalar(
            text(
                "SELECT count(*) FROM hireandtech.job_sources "
                "WHERE source = 'dice' AND source_job_id = :source_job_id"
            ),
            {"source_job_id": "e212edfb-4eb6-45d2-bd7b-7271a8730357"},
        )
        print(f"named_example_count: {named}")
        print(f"complete_sample: {dict(complete) if complete else None}")
        print(f"incomplete_sample: {dict(incomplete) if incomplete else None}")


async def _local_candidates(database: Database, limit: int) -> list[GlobalJob]:
    async with database.sessions() as session:
        external_ids = list(
            await session.scalars(
                text(
                    f"""
                    SELECT g.external_job_id
                    FROM hireandtech.global_jobs AS g
                    JOIN hireandtech.job_sources AS js
                      ON js.source = g.source AND js.source_job_id = g.external_job_id
                    JOIN hireandtech.jobs AS j ON j.id = js.job_id
                    WHERE js.source = 'dice'
                      AND ({_INCOMPLETE_SQL})
                      AND ({_LOCAL_IMPROVEMENT_SQL})
                    ORDER BY g.external_job_id
                    LIMIT :limit
                    """
                ),
                {"limit": limit},
            )
        )
        if not external_ids:
            return []
        return list(
            await session.scalars(
                select(GlobalJob)
                .where(
                    GlobalJob.source == JobSource.DICE.value,
                    GlobalJob.external_job_id.in_(external_ids),
                )
                .order_by(GlobalJob.external_job_id)
            )
        )


def _raw_from_legacy(job: GlobalJob) -> RawSourceJob:
    return RawSourceJob(
        source=str(job.source),
        external_job_id=job.external_job_id,
        title=job.job_title,
        company=job.company,
        location=job.location,
        url=job.job_url,
        description=job.description,
        salary_text=job.salary_text,
        employment_type=job.employment_type,
        remote=job.remote,
        posted_at=job.posted_at,
        skills=tuple(job.skills or []),
    )


async def _apply_local(database: Database, limit: int) -> int:
    candidates = await _local_candidates(database, limit)
    service = CanonicalJobIngestionService()
    repaired = 0
    async with database.sessions() as session, session.begin():
        for legacy in candidates:
            await service.ingest(session, normalize_job(_raw_from_legacy(legacy)))
            repaired += 1
    return repaired


async def _live_candidates(database: Database, limit: int) -> list[RepairCandidate]:
    async with database.sessions() as session:
        rows = await session.execute(text(_LIVE_CANDIDATES_SQL), {"limit": limit})
        return [RepairCandidate(**row) for row in rows.mappings()]


async def _fetch_live(database: Database, limit: int) -> tuple[int, int]:
    candidates = await _live_candidates(database, limit)
    target = CollectionTarget(source=JobSource.DICE, query="repair", max_jobs=limit)
    discovered = tuple(
        DiscoveredSourceJob(
            source=JobSource.DICE.value,
            external_job_id=item.source_job_id,
            title=item.title,
            url=item.source_url,
        )
        for item in candidates
    )
    raw_jobs = await DiceCollector().fetch_details(target, discovered)
    async with database.sessions() as session, session.begin():
        await CollectionCoordinator().persist_raw_jobs(
            session,
            target,
            raw_jobs,
            started=datetime.now(UTC),
        )
    return len(candidates), len(raw_jobs)


async def main() -> None:
    args = _arguments()
    database = Database(Settings())
    try:
        if args.apply_local:
            print(f"locally_repaired: {await _apply_local(database, args.limit)}")
        elif args.fetch_live:
            attempted, fetched = await _fetch_live(database, args.limit)
            print(f"detail_candidates: {attempted}")
            print(f"details_fetched_and_persisted: {fetched}")
        await _report(database)
        if args.samples:
            await _samples(database)
    finally:
        await database.close()


if __name__ == "__main__":
    asyncio.run(main())
