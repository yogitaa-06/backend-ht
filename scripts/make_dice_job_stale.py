import asyncio

from sqlalchemy import text

from app.core.config import Settings
from app.db.session import Database

EXTERNAL_JOB_ID = "ce3f6f92-ed77-4a64-91d0-dedab5a990f5"


async def main() -> None:
    database = Database(Settings())

    try:
        async with database.sessions() as session:
            result = await session.execute(
                text(
                    """
                    UPDATE hireandtech.global_jobs
                    SET scraped_at = NOW() - INTERVAL '7 hours'
                    WHERE source = 'dice'
                      AND external_job_id = :external_job_id
                    RETURNING
                        id,
                        source,
                        external_job_id,
                        first_seen_at,
                        last_seen_at,
                        scraped_at
                    """
                ),
                {"external_job_id": EXTERNAL_JOB_ID},
            )

            row = result.mappings().one_or_none()

            if row is None:
                print("NO MATCHING JOB FOUND")
                await session.rollback()
                return

            await session.commit()

            print("UPDATED JOB")
            print("ID          :", row["id"])
            print("Source      :", row["source"])
            print("External ID :", row["external_job_id"])
            print("First Seen  :", row["first_seen_at"])
            print("Last Seen   :", row["last_seen_at"])
            print("Scraped At  :", row["scraped_at"])

    finally:
        await database.close()


if __name__ == "__main__":
    asyncio.run(main())
