"""Manual ingestion CLI."""

import argparse
import asyncio
import logging

from app.core.config import Settings
from app.core.logging import configure_logging
from app.db.session import Database
from app.domain.jobs import JobSource
from app.jobs.collection import CollectionCoordinator
from app.jobs.registry import build_collector_registry
from app.jobs.targets import CollectionTarget


async def main() -> None:
    parser = argparse.ArgumentParser(description="Manual Job Ingestion")
    parser.add_argument(
        "--source",
        type=str,
        choices=["dice", "linkedin", "glassdoor", "hiringcafe"],
        help="Source to scrape",
    )
    parser.add_argument("--all", action="store_true", help="Scrape all sources")
    parser.add_argument("--query", type=str, default="Software Engineer", help="Job search query")
    parser.add_argument("--location", type=str, default="United States", help="Job search location")
    parser.add_argument("--max-jobs", type=int, default=5, help="Maximum jobs to fetch per source")
    args = parser.parse_args()

    settings = Settings()
    configure_logging(settings.log_level)
    database = Database(settings)

    if not await database.check_connection():
        print("Database is unavailable")
        return

    registry = build_collector_registry()
    coordinator = CollectionCoordinator()

    sources_to_run: list[JobSource] = []
    if args.all:
        sources_to_run = [
            JobSource.DICE,
            JobSource.LINKEDIN,
            JobSource.GLASSDOOR,
            JobSource.HIRINGCAFE,
        ]
    elif args.source:
        sources_to_run = [JobSource(args.source)]
    else:
        print("Please provide --source or --all")
        return

    for source in sources_to_run:
        target = CollectionTarget(
            source=source, query=args.query, location=args.location, max_jobs=args.max_jobs
        )
        print(f"\n--- Running collection for {source.value} ---")
        collector = registry.resolve(source)
        try:
            async with database.sessions() as session, session.begin():
                outcome = await coordinator.run(session, collector, target)
            print(f"Discovered: {outcome.jobs_discovered}")
            print(f"Recently Seen (Already in DB, refreshed): {outcome.details_skipped_recent}")
            print(f"Details Fetched: {outcome.details_fetched}")
            print(f"Normalized: {outcome.jobs_normalized}")
            print(f"Inserted (New): {outcome.jobs_inserted}")
            print(f"Updated: {outcome.jobs_updated}")
            print(f"Skipped (Deduplicated): {outcome.jobs_skipped}")
            print(f"Failed details: {outcome.jobs_failed}")
            print(f"Canonical failures: {outcome.canonical_jobs_failed}")
        except Exception as e:
            print(f"Error collecting {source.value}: {e}")
            logging.exception(e)

    await database.close()


if __name__ == "__main__":
    asyncio.run(main())
