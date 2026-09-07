"""
Alembic environment for the private HireAndTech PostgreSQL schema.

Bootstrap the schema before Alembic creates its version table. Domain DDL is always
revision-driven; startup never invokes this module. Autogeneration only inspects our
schema and cannot propose changes to Supabase auth, storage, or public schemas.
"""

import asyncio
from typing import Any

from alembic import context
from alembic.util import CommandError
from sqlalchemy import Connection, text

from app.core.config import Settings
from app.core.logging import configure_logging
from app.db.base import SCHEMA, Base
from app.db.session import create_database_engine


def include_name(name: str | None, type_: str, parent_names: dict[str, Any]) -> bool:
    """Restrict reflection to our schema; future models must be imported above."""
    if type_ == "schema":
        return name == SCHEMA
    return True


def run_migrations(connection: Connection) -> None:
    """Run revisions using a caller-owned transaction."""
    context.configure(
        connection=connection,
        target_metadata=Base.metadata,
        version_table_schema=SCHEMA,
        include_schemas=True,
        include_name=include_name,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_online() -> None:
    """Use a separate unpooled connection and safely dispose it on all paths."""
    settings = Settings()
    configure_logging(settings.log_level)
    engine = create_database_engine(settings, migration=True)
    try:
        async with engine.begin() as connection:
            await connection.execute(text("CREATE SCHEMA IF NOT EXISTS hireandtech"))
            await connection.run_sync(run_migrations)
    except Exception:
        raise CommandError(
            "Database migration failed; check connectivity, privileges, and revision SQL"
        ) from None
    finally:
        await engine.dispose()


if context.is_offline_mode():
    # Generating reviewable SQL needs neither credentials nor a running database.
    context.configure(
        dialect_name="postgresql",
        target_metadata=Base.metadata,
        version_table_schema=SCHEMA,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.execute("CREATE SCHEMA IF NOT EXISTS hireandtech")
        context.run_migrations()
else:
    asyncio.run(run_online())
