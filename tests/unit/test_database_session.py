from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from starlette.requests import Request

from app.core.config import Settings
from app.core.errors import ApplicationError
from app.db.session import Database, create_database_engine, get_database


def make_settings() -> Settings:
    """Create isolated test settings for local PostgreSQL behavior."""
    return Settings(
        environment="test",
        database_url=SecretStr("postgresql://user:password@localhost:5432/hireandtech_test"),
        database_ssl_mode="disable",
    )


def make_request(app: FastAPI) -> Request:
    """Create the smallest Starlette request needed for app-state tests."""
    return Request(
        {
            "type": "http",
            "app": app,
            "method": "GET",
            "path": "/",
            "headers": [],
            "query_string": b"",
            "server": ("testserver", 80),
            "client": ("127.0.0.1", 50000),
            "scheme": "http",
        }
    )


def test_create_database_engine_requires_database_url() -> None:
    settings = Settings(
        environment="test",
        database_url=None,
    )

    with pytest.raises(
        ValueError,
        match="HIREANDTECH_DATABASE_URL is required",
    ):
        create_database_engine(settings)


def test_create_database_engine_uses_asyncpg_driver() -> None:
    settings = make_settings()

    engine = create_database_engine(settings)

    assert engine.url.drivername == "postgresql+asyncpg"
    assert engine.url.host == "localhost"
    assert engine.url.database == "hireandtech_test"


def test_database_creates_session_factory() -> None:
    settings = make_settings()

    database = Database(settings)

    assert database.engine is not None
    assert database.sessions is not None
    assert database.probe_timeout > 0


@pytest.mark.anyio
async def test_check_connection_returns_false_when_connection_fails() -> None:
    settings = make_settings()
    database = Database(settings)

    with patch.object(
        type(database.engine),
        "connect",
        side_effect=RuntimeError("connection failed"),
    ):
        assert await database.check_connection() is False


@pytest.mark.anyio
async def test_close_disposes_engine() -> None:
    settings = make_settings()
    database = Database(settings)

    with patch.object(
        type(database.engine),
        "dispose",
        new_callable=AsyncMock,
    ) as dispose:
        await database.close()

        dispose.assert_awaited_once_with()


def test_get_database_returns_application_database() -> None:
    settings = make_settings()
    database = Database(settings)

    app = FastAPI()
    app.state.database = database

    request = make_request(app)

    assert get_database(request) is database


def test_get_database_fails_closed_when_database_is_missing() -> None:
    app = FastAPI()
    request = make_request(app)

    with pytest.raises(ApplicationError) as exc_info:
        get_database(request)

    assert exc_info.value.code == "DATABASE_UNAVAILABLE"
    assert exc_info.value.status_code == 503
