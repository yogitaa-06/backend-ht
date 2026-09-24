"""Enqueue one controlled Dice collection job for ARQ validation."""

from __future__ import annotations

import asyncio

from app.core.config import Settings
from app.queue.client import create_queue_pool


async def main() -> None:
    settings = Settings()
    redis = await create_queue_pool(settings)

    try:
        job = await redis.enqueue_job(
            "run_job_collection",
            "dice",
            "DevOps Engineer",
            "United States",
            5,
            _queue_name=settings.job_collection_queue_name,
        )

        if job is None:
            print("JOB NOT ENQUEUED")
            return

        print("JOB ENQUEUED")
        print("Job ID :", job.job_id)
        print("Queue  :", settings.job_collection_queue_name)

        result = await job.result(timeout=60)

        print()
        print("JOB RESULT")
        print(result)

    finally:
        await redis.aclose(close_connection_pool=True)


if __name__ == "__main__":
    asyncio.run(main())
