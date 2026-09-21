"""Unit tests for deployment-safety configuration invariants."""

import pytest
from pydantic import SecretStr, ValidationError

from app.core.config import Settings


def _production_settings(**updates: object) -> Settings:
    values: dict[str, object] = {
        "_env_file": None,
        "environment": "production",
        "allowed_hosts": ["api.hireandtech.example"],
        "cors_allowed_origins": ["https://hireandtech.example"],
        "database_url": SecretStr("postgresql://application:password@database.example/hireandtech"),
        "supabase_url": "https://example.supabase.co",
        "supabase_secret_key": SecretStr("test-only-server-secret"),
    }
    values.update(updates)
    return Settings(**values)  # type: ignore[arg-type]


def test_local_defaults_are_valid() -> None:
    settings = Settings(_env_file=None)

    assert settings.environment == "local"
    assert settings.api_v1_prefix == "/api/v1"


def test_wildcard_host_allowlist_is_rejected() -> None:
    with pytest.raises(ValidationError, match="wildcard entries are not allowed"):
        Settings(_env_file=None, allowed_hosts=["*"])


def test_wildcard_origin_allowlist_is_rejected() -> None:
    with pytest.raises(ValidationError, match="wildcard entries are not allowed"):
        Settings(_env_file=None, cors_allowed_origins=["*"])


def test_empty_network_allowlist_entry_is_rejected() -> None:
    with pytest.raises(ValidationError, match="entries must not be empty"):
        Settings(_env_file=None, allowed_hosts=[""])


@pytest.mark.parametrize(
    "origin",
    [
        "localhost:3000",
        "http://localhost:3000/path",
        "https://user@example.com",
        "http://localhost:99999",
    ],
)
def test_malformed_browser_origin_is_rejected(origin: str) -> None:
    with pytest.raises(ValidationError, match="origins must"):
        Settings(_env_file=None, cors_allowed_origins=[origin])


def test_invalid_api_prefix_is_rejected() -> None:
    with pytest.raises(ValidationError, match="must start with '/' and must not end with '/'"):
        Settings(_env_file=None, api_v1_prefix="api/v1/")


def test_production_rejects_local_network_defaults() -> None:
    with pytest.raises(ValidationError, match="require HIREANDTECH_ALLOWED_HOSTS"):
        _production_settings(allowed_hosts=["localhost", "127.0.0.1"])


def test_production_accepts_explicit_network_configuration() -> None:
    settings = _production_settings()

    assert settings.environment == "production"


@pytest.mark.parametrize(
    ("field", "message"),
    [
        ("database_url", "HIREANDTECH_DATABASE_URL"),
        ("supabase_url", "HIREANDTECH_SUPABASE_URL"),
        ("supabase_secret_key", "HIREANDTECH_SUPABASE_SECRET_KEY"),
    ],
)
def test_production_requires_runtime_dependencies(field: str, message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        _production_settings(**{field: None})


def test_supabase_url_derives_authentication_endpoints() -> None:
    settings = Settings(
        supabase_url="https://example.supabase.co/",
        _env_file=None,
    )

    assert settings.supabase_url == "https://example.supabase.co"
    assert settings.supabase_jwt_issuer == "https://example.supabase.co/auth/v1"
    assert settings.supabase_jwks_url == "https://example.supabase.co/auth/v1/.well-known/jwks.json"
    assert settings.supabase_jwt_audience == "authenticated"


@pytest.mark.parametrize(
    "url",
    [
        "http://example.supabase.co",
        "https://example.supabase.co/path",
        "https://user:password@example.supabase.co",
        "https://example.supabase.co?query=value",
        "https://example.supabase.co#fragment",
        "https://example.supabase.co:99999",
        "not-a-url",
    ],
)
def test_supabase_url_rejects_invalid_origins(url: str) -> None:
    with pytest.raises(ValidationError):
        Settings(
            supabase_url=url,
            _env_file=None,
        )


def test_supabase_authentication_configuration_is_optional_locally() -> None:
    settings = Settings(_env_file=None)

    assert settings.supabase_url is None
    assert settings.supabase_jwt_issuer is None
    assert settings.supabase_jwks_url is None
    assert settings.supabase_jwt_audience == "authenticated"
