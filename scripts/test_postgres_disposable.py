"""Run database tests against a generated loopback-only disposable PostgreSQL database."""

from __future__ import annotations

import asyncio
import os
import re
import subprocess
import sys
from uuid import uuid4

import asyncpg
from sqlalchemy.engine import URL

from app.core.config import Settings
from app.db.urls import parse_database_url

_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}
_DATABASE_PATTERN = re.compile(r"^hireandtech_disposable_[0-9a-f]{12}$")


def _safe_urls(settings: Settings) -> tuple[URL, URL, str]:
    secret = settings.database_migration_url or settings.database_url
    if secret is None:
        raise RuntimeError("A local PostgreSQL URL is required")
    source = parse_database_url(secret)
    if source.host not in _LOOPBACK_HOSTS:
        raise RuntimeError("Disposable tests refuse non-loopback PostgreSQL servers")
    database_name = f"hireandtech_disposable_{uuid4().hex[:12]}"
    if _DATABASE_PATTERN.fullmatch(database_name) is None:  # pragma: no cover - invariant
        raise RuntimeError("Unsafe disposable database name")
    admin = source.set(database="postgres", drivername="postgresql")
    test = source.set(database=database_name, drivername="postgresql")
    return admin, test, database_name


async def _create_database(admin_url: URL, database_name: str) -> None:
    connection = await asyncpg.connect(admin_url.render_as_string(hide_password=False), ssl=False)
    try:
        await connection.execute(f'CREATE DATABASE "{database_name}"')
    finally:
        await connection.close()


async def _drop_database(admin_url: URL, database_name: str) -> None:
    if _DATABASE_PATTERN.fullmatch(database_name) is None:
        raise RuntimeError("Refusing to drop an unrecognized database name")
    connection = await asyncpg.connect(admin_url.render_as_string(hide_password=False), ssl=False)
    try:
        await connection.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = $1 AND pid <> pg_backend_pid()",
            database_name,
        )
        await connection.execute(f'DROP DATABASE IF EXISTS "{database_name}"')
    finally:
        await connection.close()


def main() -> int:
    settings = Settings()
    admin_url, test_url, database_name = _safe_urls(settings)
    asyncio.run(_create_database(admin_url, database_name))
    environment = os.environ.copy()
    rendered_test_url = test_url.render_as_string(hide_password=False)
    environment["HIREANDTECH_TEST_DATABASE_URL"] = rendered_test_url
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "pytest", "--cov=app", "--cov-report=term-missing"],
            env=environment,
            check=False,
        )
        return completed.returncode
    finally:
        asyncio.run(_drop_database(admin_url, database_name))


if __name__ == "__main__":
    raise SystemExit(main())
