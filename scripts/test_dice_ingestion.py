"""Controlled live Dice -> PostgreSQL ingestion smoke test.

This script intentionally:
- uses one Dice query,
- limits collection to five jobs,
- uses the production CollectionCoordinator,
- writes to the configured HIREANDTECH_DATABASE_URL,
- commits the transaction,
- prints persistence statistics,
- reads the resulting Dice rows from the canonical graph.

Do not use this as a scheduler or production worker entry point.
"""

from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.core.config import Settings
from app.db.session import Database
from app.domain.jobs import CanonicalJob, Company, JobSource, JobSourceObservation
from app.jobs.collection import CollectionCoordinator
from app.jobs.sources.dice import DiceCollector
from app.jobs.targets import CollectionTarget


async def main() -> None:
    settings = Settings()

    database = Database(settings)

    target = CollectionTarget(
        source=JobSource.DICE,
        query="DevOps Engineer",
        location="United States",
        max_jobs=5,
    )

    collector = DiceCollector()
    coordinator = CollectionCoordinator()

    print()
    print("=" * 100)
    print("CONTROLLED DICE DATABASE INGESTION")
    print("=" * 100)
    print(f"Query        : {target.query}")
    print(f"Location     : {target.location}")
    print(f"Maximum jobs : {target.max_jobs}")
    print()

    try:
        async with database.sessions() as session:
            result = await coordinator.run(
                session,
                collector,
                target,
            )

            await session.commit()

            print("=" * 100)
            print("COLLECTION RESULT")
            print("=" * 100)
            print(f"Discovered : {result.jobs_discovered}")
            print(f"Normalized : {result.jobs_normalized}")
            print(f"Inserted   : {result.jobs_inserted}")
            print(f"Updated    : {result.jobs_updated}")
            print(f"Skipped    : {result.jobs_skipped}")
            print(f"Failed     : {result.jobs_failed}")
            print(f"Canon fail : {result.canonical_jobs_failed}")
            print(f"Duration   : {result.duration_seconds:.2f} seconds")
            print()

        async with database.sessions() as session:
            statement = (
                select(JobSourceObservation, CanonicalJob, Company)
                .join(CanonicalJob, CanonicalJob.id == JobSourceObservation.job_id)
                .outerjoin(Company, Company.id == CanonicalJob.company_id)
                .where(JobSourceObservation.source == JobSource.DICE.value)
                .order_by(
                    CanonicalJob.posted_at.desc().nullslast(),
                    CanonicalJob.id,
                )
                .limit(10)
            )

            jobs = list((await session.execute(statement)).tuples())

            print("=" * 100)
            print("DICE ROWS CURRENTLY IN THE CANONICAL GRAPH")
            print("=" * 100)
            print(f"Rows shown: {len(jobs)}")

            for index, (source, job, company) in enumerate(
                jobs,
                start=1,
            ):
                print()
                print(f"JOB #{index}")
                print("-" * 100)
                print(f"DB ID          : {job.id}")
                print(f"External ID    : {source.source_job_id}")
                print(f"Title          : {job.title}")
                print(f"Normalized     : {job.normalized_title}")
                print(f"Role Family    : {job.role_family}")
                print(f"Company        : {company.name if company else None}")
                print(f"Location       : {job.location}")
                print(f"Remote Type    : {job.remote_type}")
                print(f"Employment     : {job.employment_type}")
                print(f"Posted At      : {job.posted_at}")
                print(f"First Seen     : {source.first_seen_at}")
                print(f"Last Seen      : {source.last_seen_at}")
                print(f"Scraped At     : {source.scraped_at}")
                print(f"Experience Min : {job.experience_min_years}")
                print(f"Experience Max : {job.experience_max_years}")
                print(f"Experience Text: {job.experience_text}")
                print(f"URL            : {source.source_url}")

            print()
            print("=" * 100)
            print("INGESTION TEST COMPLETE")
            print("=" * 100)

    finally:
        await database.close()


if __name__ == "__main__":
    asyncio.run(main())
