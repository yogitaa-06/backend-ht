import pytest
from pydantic import SecretStr

from app.db.urls import parse_database_url


def test_parse_database_url_converts_postgresql_to_asyncpg() -> None:
    url = parse_database_url(SecretStr("postgresql://user:password@localhost:5432/hireandtech"))

    assert url.drivername == "postgresql+asyncpg"
    assert url.host == "localhost"
    assert url.port == 5432
    assert url.username == "user"
    assert url.database == "hireandtech"


def test_parse_database_url_accepts_asyncpg_scheme() -> None:
    url = parse_database_url(
        SecretStr("postgresql+asyncpg://user:password@localhost:5432/hireandtech")
    )

    assert url.drivername == "postgresql+asyncpg"


@pytest.mark.parametrize(
    "value",
    [
        "sqlite:///test.db",
        "postgresql://localhost:5432/hireandtech",
        "postgresql://user:password@localhost:5432",
        "postgresql://user:password@localhost:99999/hireandtech",
        "postgresql://user:password@localhost:5432/hireandtech?sslmode=require",
        "postgresql://user:password@localhost:5432/hireandtech#fragment",
        "postgresql://user:password@local host:5432/hireandtech",
        "not-a-url",
    ],
)
def test_parse_database_url_rejects_invalid_urls(value: str) -> None:
    with pytest.raises(ValueError, match="database URL must be a PostgreSQL URI"):
        parse_database_url(SecretStr(value))


def test_parse_database_url_rejects_supabase_transaction_pooler_port() -> None:
    with pytest.raises(
        ValueError,
        match="use the Supabase direct or session connection on port 5432",
    ):
        parse_database_url(
            SecretStr("postgresql://user:password@db.example.supabase.co:6543/hireandtech")
        )
