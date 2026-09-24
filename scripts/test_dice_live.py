"""Controlled live smoke test for the Dice collector."""

from __future__ import annotations

import asyncio

from app.domain.jobs import JobSource
from app.jobs.sources.dice import DiceCollector
from app.jobs.targets import CollectionTarget


async def main() -> None:
    target = CollectionTarget(
        source=JobSource.DICE,
        query="DevOps Engineer",
        location="United States",
        max_jobs=10,
    )

    collector = DiceCollector()

    print()
    print("Starting controlled Dice collection...")
    print(f"Query: {target.query}")
    print(f"Location: {target.location}")
    print(f"Maximum jobs: {target.max_jobs}")
    print()

    jobs = await collector.collect(target)

    print("=" * 100)
    print(f"JOBS RETURNED: {len(jobs)}")
    print("=" * 100)

    for index, job in enumerate(jobs, start=1):
        print()
        print(f"JOB #{index}")
        print("-" * 100)
        print(f"External ID : {job.external_job_id}")
        print(f"Title       : {job.title}")
        print(f"Company     : {job.company}")
        print(f"Location    : {job.location}")
        print(f"Posted At   : {job.posted_at}")
        print(f"Remote      : {job.remote}")
        print(f"Type        : {job.employment_type}")
        print(f"Skills      : {job.skills}")
        print(f"URL         : {job.url}")

    print()
    print("=" * 100)
    print("LIVE DICE TEST COMPLETE")
    print("=" * 100)


if __name__ == "__main__":
    asyncio.run(main())
