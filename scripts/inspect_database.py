import asyncio

from sqlalchemy import text

from app.core.config import Settings
from app.db.session import Database


async def main() -> None:
    settings = Settings()
    database = Database(settings)

    try:
        async with database.sessions() as session:
            connection_info = (
                (
                    await session.execute(
                        text(
                            """
                        SELECT
                            current_database() AS database_name,
                            current_user AS database_user,
                            current_schema() AS current_schema,
                            current_setting('search_path') AS search_path,
                            inet_server_addr()::text AS server_address,
                            inet_server_port() AS server_port
                        """
                        )
                    )
                )
                .mappings()
                .one()
            )

            print("DATABASE CONNECTION")
            print("-------------------")
            print("Database :", connection_info["database_name"])
            print("User     :", connection_info["database_user"])
            print("Schema   :", connection_info["current_schema"])
            print("Path     :", connection_info["search_path"])
            print("Server   :", connection_info["server_address"])
            print("Port     :", connection_info["server_port"])

            tables = (
                await session.execute(
                    text(
                        """
                        SELECT
                            table_schema,
                            table_name
                        FROM information_schema.tables
                        WHERE table_name = 'global_jobs'
                        ORDER BY table_schema
                        """
                    )
                )
            ).all()

            print()
            print("GLOBAL_JOBS TABLES")
            print("------------------")

            if not tables:
                print("NONE")
            else:
                for schema, table in tables:
                    print(f"{schema}.{table}")

    finally:
        await database.close()


if __name__ == "__main__":
    asyncio.run(main())
