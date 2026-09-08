"""
Runtime configuration for the HireAndTech API.

Purpose:
    Provide one typed, environment-driven configuration boundary for the backend.

Responsibilities:
    - Application runtime settings.
    - API prefix configuration.
    - Network Host and CORS allowlists.
    - PostgreSQL connection configuration.
    - Supabase authentication trust configuration.
    - Validation of security-sensitive deployment settings.

Does NOT:
    - Authenticate users directly.
    - Verify JWT signatures.
    - Store passwords or authentication secrets.
    - Perform database queries.

Security:
    Browser origins and accepted Host headers are explicit allowlists.
    Wildcards are rejected so a production deployment cannot accidentally
    become permissive.

    Supabase authentication settings are centralized here. The project URL is
    treated as a trust boundary. The expected JWT issuer and JWKS endpoint are
    derived from that project URL instead of being configured independently.
"""

from functools import lru_cache
from ipaddress import IPv4Network, IPv6Network, ip_network
from pathlib import Path
from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.db.urls import parse_database_url

Environment = Literal["local", "test", "staging", "production"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
SupabaseJwtAudience = Literal["authenticated"]
IpNetwork = IPv4Network | IPv6Network


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

    # Application
    application_name: str = "HireAndTech API"
    environment: Environment = "local"
    log_level: LogLevel = "INFO"
    api_v1_prefix: str = "/api/v1"

    # Network security
    allowed_hosts: list[str] = Field(default_factory=lambda: ["localhost", "127.0.0.1"])
    cors_allowed_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])
    trusted_proxy_cidrs: list[IpNetwork] = Field(default_factory=list)
    ip_allowlist_enabled: bool = False
    ip_allowlist_fail_closed: bool = True
    ip_emergency_bypass_cidrs: list[IpNetwork] = Field(default_factory=list)
    rate_limit_enabled: bool = True
    rate_limit_fail_closed: bool = True
    rate_limit_window_seconds: int = Field(default=60, ge=1, le=3600)
    rate_limit_auth_requests: int = Field(default=30, ge=1, le=10_000)
    rate_limit_admin_security_requests: int = Field(default=60, ge=1, le=10_000)
    rate_limit_max_keys: int = Field(default=10_000, ge=100, le=1_000_000)

    # PostgreSQL
    database_url: SecretStr | None = None
    database_migration_url: SecretStr | None = None
    database_ssl_mode: Literal["disable", "verify-full"] = "verify-full"
    database_ssl_ca_file: Path | None = None
    database_pool_size: int = Field(default=5, ge=1, le=50)
    database_max_overflow: int = Field(default=5, ge=0, le=50)
    database_pool_timeout_seconds: float = Field(default=5, gt=0, le=60)
    database_connect_timeout_seconds: float = Field(default=5, gt=0, le=60)
    database_statement_timeout_seconds: float = Field(default=10, gt=0, le=300)

    # Supabase authentication
    supabase_url: str | None = None
    supabase_jwt_audience: SupabaseJwtAudience = "authenticated"

    @field_validator("trusted_proxy_cidrs", "ip_emergency_bypass_cidrs", mode="before")
    @classmethod
    def normalize_ip_networks(cls, value: object) -> object:
        """Normalize configured IPv4/IPv6 networks and reject malformed entries."""
        if not isinstance(value, (list, tuple)):
            return value
        normalized: list[IpNetwork] = []
        for item in value:
            if not isinstance(item, (str, IPv4Network, IPv6Network)):
                raise ValueError("IP network entries must be CIDR strings")
            try:
                normalized.append(ip_network(item, strict=False))
            except ValueError:
                raise ValueError("IP network entries must be valid IPv4 or IPv6 CIDRs") from None
        return normalized

    @field_validator("database_url", "database_migration_url")
    @classmethod
    def validate_database_url(
        cls,
        value: SecretStr | None,
    ) -> SecretStr | None:
        """Validate database URLs without exposing their original values."""
        if value is not None:
            parse_database_url(value)

        return value

    @field_validator("supabase_url")
    @classmethod
    def validate_supabase_url(
        cls,
        value: str | None,
    ) -> str | None:
        """
        Validate the Supabase project URL used as an authentication trust boundary.

        Only an HTTPS origin is accepted. Paths, credentials, query strings, and
        fragments are rejected because authentication endpoints are derived from
        this value internally.
        """
        if value is None:
            return None

        normalized_value = value.rstrip("/")
        parsed = urlsplit(normalized_value)

        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.path
            or parsed.query
            or parsed.fragment
            or parsed.username
            or parsed.password
        ):
            raise ValueError("SUPABASE_URL must be an HTTPS origin containing only scheme and host")

        try:
            _ = parsed.port
        except ValueError as exc:
            raise ValueError("SUPABASE_URL must contain a valid port") from exc

        return normalized_value

    @property
    def supabase_jwt_issuer(self) -> str | None:
        """Return the trusted issuer expected on Supabase access tokens."""
        if self.supabase_url is None:
            return None

        return f"{self.supabase_url}/auth/v1"

    @property
    def supabase_jwks_url(self) -> str | None:
        """Return the public JWKS endpoint used for JWT signature verification."""
        issuer = self.supabase_jwt_issuer

        if issuer is None:
            return None

        return f"{issuer}/.well-known/jwks.json"

    @model_validator(mode="after")
    def validate_database_tls(self) -> Self:
        """
        Permit plaintext PostgreSQL connections only for local/test loopback DBs.

        Staging and production environments must use verify-full TLS.
        """
        if self.database_ssl_mode == "disable":
            if self.environment not in {"local", "test"}:
                raise ValueError("non-local databases require verify-full TLS")

            for secret in (
                self.database_url,
                self.database_migration_url,
            ):
                if secret is not None and parse_database_url(secret).host not in {
                    "localhost",
                    "127.0.0.1",
                    "::1",
                }:
                    raise ValueError("TLS can only be disabled for a loopback database")

        return self

    @field_validator("api_v1_prefix")
    @classmethod
    def validate_api_prefix(cls, value: str) -> str:
        """Keep route composition predictable and reject malformed API prefixes."""
        if not value.startswith("/") or value.endswith("/"):
            raise ValueError("must start with '/' and must not end with '/'")

        return value

    @field_validator(
        "allowed_hosts",
        "cors_allowed_origins",
    )
    @classmethod
    def reject_wildcards_and_empty_allowlists(
        cls,
        values: list[str],
    ) -> list[str]:
        """Require deliberate, non-empty network allowlists."""
        if not values:
            raise ValueError("must contain at least one entry")

        if any(not value.strip() for value in values):
            raise ValueError("entries must not be empty")

        if any("*" in value for value in values):
            raise ValueError("wildcard entries are not allowed")

        return values

    @field_validator("cors_allowed_origins")
    @classmethod
    def validate_browser_origins(
        cls,
        values: list[str],
    ) -> list[str]:
        """Require explicit HTTP(S) browser origins."""
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
        """
        Prevent local development defaults from reaching staging/production.

        Non-local environments must explicitly configure Host and CORS allowlists.
        """
        if self.environment in {"staging", "production"}:
            if not self.ip_allowlist_fail_closed or not self.rate_limit_fail_closed:
                raise ValueError("non-local security controls must fail closed")
            if self.allowed_hosts == [
                "localhost",
                "127.0.0.1",
            ]:
                raise ValueError("non-local environments require HIREANDTECH_ALLOWED_HOSTS")

            if self.cors_allowed_origins == [
                "http://localhost:3000",
            ]:
                raise ValueError("non-local environments require HIREANDTECH_CORS_ALLOWED_ORIGINS")

        return self


@lru_cache
def get_settings() -> Settings:
    """Load application configuration once per process."""
    return Settings()
