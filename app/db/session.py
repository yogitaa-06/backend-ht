"""
Async PostgreSQL engine and request-scoped sessions.

Owns bounded pooling, TLS, timeouts, connection probes, and disposal. Does not commit
on behalf of callers: services must finish explicit transactions before responding.
Each request/task owns a session; sessions must never be shared across tasks.

Security:
    SQL echo is disabled and bound parameters are hidden. Callers must not log raw
    driver exceptions, which can contain database credentials or record contents.
"""

import asyncio
import logging
import ssl
from collections.abc import AsyncIterator
from typing import Any

from fastapi import Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.core.config import Settings
from app.core.errors import ApplicationError
from app.db.urls import parse_database_url

logger = logging.getLogger(__name__)


def create_database_engine(settings: Settings, *, migration: bool = False) -> AsyncEngine:
    """Create a lazy engine; migrations use their own unpooled connection."""
    secret = settings.database_migration_url if migration else settings.database_url
    secret = secret or settings.database_url
    if secret is None:
        raise ValueError("HIREANDTECH_DATABASE_URL is required to start the API or run migrations")
    tls: ssl.SSLContext | bool = False
    if settings.database_ssl_mode == "verify-full":
        tls = ssl.create_default_context(cafile=settings.database_ssl_ca_file)
    options: dict[str, Any] = {
        "echo": False,
        "hide_parameters": True,
        "connect_args": {
            "ssl": tls,
            "timeout": settings.database_connect_timeout_seconds,
            "command_timeout": settings.database_statement_timeout_seconds,
            "server_settings": {
                "application_name": "hireandtech-migrations" if migration else "hireandtech-api",
                "timezone": "UTC",
                "statement_timeout": str(int(settings.database_statement_timeout_seconds * 1000)),
                "idle_in_transaction_session_timeout": "30000",
            },
        },
    }
    if migration:
        options["poolclass"] = NullPool
    else:
        options.update(
            pool_size=settings.database_pool_size,
            max_overflow=settings.database_max_overflow,
            pool_timeout=settings.database_pool_timeout_seconds,
            pool_pre_ping=True,
            pool_recycle=1800,
        )
    return create_async_engine(parse_database_url(secret), **options)


class Database:
    """Application-owned pool and session factory with bounded health probes."""

    def __init__(self, settings: Settings) -> None:
        self.engine = create_database_engine(settings)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False, autoflush=False)
        self.probe_timeout = (
            settings.database_pool_timeout_seconds
            + settings.database_connect_timeout_seconds
            + settings.database_statement_timeout_seconds
        )

    async def check_connection(self) -> bool:
        """Probe database availability without logging driver or connection details."""
        try:
            async with asyncio.timeout(self.probe_timeout), self.engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        except Exception:
            # Driver errors can embed SQL, credentials, or network topology. A stable
            # event is sufficient here; cancellation (BaseException) still propagates.
            logger.warning("database_unavailable", extra={"operation": "database_probe"})
            return False
        return True

    async def close(self) -> None:
        """Release pooled connections on shutdown, including failed startup."""
        await self.engine.dispose()


def get_database(request: Request) -> Database:
    """Resolve the lifespan-owned pool; missing initialization fails closed."""
    database = getattr(request.app.state, "database", None)
    if not isinstance(database, Database):
        raise ApplicationError(
            "DATABASE_UNAVAILABLE",
            "The service is temporarily unavailable.",
            503,
        )
    return database


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Yield an isolated session; closing rolls back any uncommitted transaction."""
    async with get_database(request).sessions() as session:
        yield session
