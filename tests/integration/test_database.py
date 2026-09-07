import os

import pytest
from pydantic import SecretStr
from sqlalchemy import MetaData, text

from app.core.config import Settings
from app.db.base import SCHEMA, Base, IdentityTimestampMixin
from app.db.session import Database


def test_database_schema_is_private_application_schema() -> None:
    """Application tables must live outside provider-managed schemas."""
    assert SCHEMA == "hireandtech"
    assert isinstance(Base.metadata, MetaData)
    assert Base.metadata.schema == "hireandtech"


def test_base_uses_naming_convention() -> None:
    """Constraint naming must remain deterministic for Alembic migrations."""
    convention = Base.metadata.naming_convention

    assert convention is not None
    assert convention["pk"] == "pk_%(table_name)s"
    assert convention["fk"] == ("fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s")


def test_identity_timestamp_mixin_declares_common_columns() -> None:
    """Shared persistence mixin must expose identity and audit timestamps."""
    annotations = IdentityTimestampMixin.__annotations__

    assert "id" in annotations
    assert "created_at" in annotations
    assert "updated_at" in annotations


TEST_DATABASE_URL = os.getenv("HIREANDTECH_TEST_DATABASE_URL")


@pytest.mark.skipif(
    TEST_DATABASE_URL is None,
    reason="HIREANDTECH_TEST_DATABASE_URL is not configured",
)
@pytest.mark.anyio
async def test_real_postgresql_connection() -> None:
    """Verify that the backend can connect to a real PostgreSQL database."""
    assert TEST_DATABASE_URL is not None

    settings = Settings(
        environment="test",
        database_url=SecretStr(TEST_DATABASE_URL),
        database_ssl_mode="disable",
    )

    database = Database(settings)

    try:
        assert await database.check_connection() is True

        async with database.engine.connect() as connection:
            result = await connection.execute(text("SELECT 1"))
            assert result.scalar_one() == 1
    finally:
        await database.close()
