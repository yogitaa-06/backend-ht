from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.config import Settings
from app.main import create_app


@pytest.mark.anyio
async def test_lifespan_owns_and_closes_shared_http_client() -> None:
    settings = Settings(
        _env_file=None,
        environment="test",
        allowed_hosts=["testserver"],
        cors_allowed_origins=["http://testserver"],
    )

    database = MagicMock()
    database.check_connection = AsyncMock(return_value=True)
    database.close = AsyncMock()

    http_client = MagicMock()
    http_client.aclose = AsyncMock()

    with (
        patch("app.main.Database", return_value=database),
        patch("app.main.httpx.AsyncClient", return_value=http_client),
    ):
        application = create_app(settings)

        async with application.router.lifespan_context(application):
            assert application.state.database is database
            assert application.state.http_client is http_client

        http_client.aclose.assert_awaited_once_with()
        database.close.assert_awaited_once_with()
        assert application.state.http_client is None
        assert application.state.database is None
