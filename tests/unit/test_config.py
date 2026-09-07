"""Unit tests for deployment-safety configuration invariants."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings


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
        Settings(_env_file=None, environment="production")


def test_production_accepts_explicit_network_configuration() -> None:
    settings = Settings(
        _env_file=None,
        environment="production",
        allowed_hosts=["api.hireandtech.example"],
        cors_allowed_origins=["https://hireandtech.example"],
    )

    assert settings.environment == "production"
