"""
Runtime configuration for the HireAndTech API.

Purpose:
    Provide one typed, environment-driven configuration boundary.

Security:
    Browser origins and accepted Host headers are allowlists. Wildcards are rejected
    so an accidental production deployment cannot silently become permissive.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.db.urls import parse_database_url

Environment = Literal["local", "test", "staging", "production"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class Settings(BaseSettings):
    """Validated application settings loaded from `HIREANDTECH_*` variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="HIREANDTECH_",
        case_sensitive=False,
        extra="ignore",
        hide_input_in_errors=True,
    )

    application_name: str = "HireAndTech API"
    environment: Environment = "local"
    log_level: LogLevel = "INFO"
    api_v1_prefix: str = "/api/v1"
    allowed_hosts: list[str] = Field(default_factory=lambda: ["localhost", "127.0.0.1"])
    cors_allowed_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])
    database_url: SecretStr | None = None
    database_migration_url: SecretStr | None = None
    database_ssl_mode: Literal["disable", "verify-full"] = "verify-full"
    database_ssl_ca_file: Path | None = None
    database_pool_size: int = Field(default=5, ge=1, le=50)
    database_max_overflow: int = Field(default=5, ge=0, le=50)
    database_pool_timeout_seconds: float = Field(default=5, gt=0, le=60)
    database_connect_timeout_seconds: float = Field(default=5, gt=0, le=60)
    database_statement_timeout_seconds: float = Field(default=10, gt=0, le=300)

    @field_validator("database_url", "database_migration_url")
    @classmethod
    def validate_database_url(cls, value: SecretStr | None) -> SecretStr | None:
        """Validate secrets without exposing their original input in errors."""
        if value is not None:
            parse_database_url(value)
        return value

    @model_validator(mode="after")
    def validate_database_tls(self) -> Self:
        """Permit plaintext only for loopback development and test databases."""
        if self.database_ssl_mode == "disable":
            if self.environment not in {"local", "test"}:
                raise ValueError("non-local databases require verify-full TLS")
            for secret in (self.database_url, self.database_migration_url):
                if secret and parse_database_url(secret).host not in {
                    "localhost",
                    "127.0.0.1",
                    "::1",
                }:
                    raise ValueError("TLS can only be disabled for a loopback database")
        return self

    @field_validator("api_v1_prefix")
    @classmethod
    def validate_api_prefix(cls, value: str) -> str:
        """Keep route composition predictable and prevent malformed API paths."""
        if not value.startswith("/") or value.endswith("/"):
            raise ValueError("must start with '/' and must not end with '/'")
        return value

    @field_validator("allowed_hosts", "cors_allowed_origins")
    @classmethod
    def reject_wildcards_and_empty_allowlists(cls, values: list[str]) -> list[str]:
        """Require deliberate network allowlists in every environment."""
        if not values:
            raise ValueError("must contain at least one entry")
        if any(not value.strip() for value in values):
            raise ValueError("entries must not be empty")
        if any("*" in value for value in values):
            raise ValueError("wildcard entries are not allowed")
        return values

    @field_validator("cors_allowed_origins")
    @classmethod
    def validate_browser_origins(cls, values: list[str]) -> list[str]:
        """Only permit explicit HTTP(S) origins; paths and trailing slashes are invalid."""
        for value in values:
            parsed = urlsplit(value)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError("origins must use http:// or https://")
            if parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password:
                raise ValueError("origins must contain only scheme, host, and optional port")
            try:
                _ = parsed.port
            except ValueError as exc:
                raise ValueError("origins must contain a valid port") from exc
        return values

    @model_validator(mode="after")
    def validate_deployment_defaults(self) -> Self:
        """Prevent local defaults from being promoted to a non-local deployment."""
        if self.environment in {"staging", "production"}:
            if self.allowed_hosts == ["localhost", "127.0.0.1"]:
                raise ValueError("non-local environments require HIREANDTECH_ALLOWED_HOSTS")
            if self.cors_allowed_origins == ["http://localhost:3000"]:
                raise ValueError("non-local environments require HIREANDTECH_CORS_ALLOWED_ORIGINS")
        return self


@lru_cache
def get_settings() -> Settings:
    """Load settings once per process; tests can inject settings into `create_app`."""
    return Settings()
