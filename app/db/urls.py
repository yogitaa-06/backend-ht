"""
Database URL validation at the configuration boundary.

Only PostgreSQL direct or session connections are supported. Driver options and
TLS policy have dedicated settings so URL query parameters cannot override them.
Invalid URL errors deliberately omit credentials and parser exception details.
"""

from pydantic import SecretStr
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError


def parse_database_url(secret: SecretStr) -> URL:
    """Normalize common PostgreSQL URI schemes for the asyncpg driver."""
    value = secret.get_secret_value()
    try:
        url = make_url(value)
        if (
            url.drivername not in {"postgres", "postgresql", "postgresql+asyncpg"}
            or not url.host
            or not url.username
            or not url.database
            or url.query
            or "#" in value
            or any(character.isspace() for character in value)
            or (url.port is not None and not 1 <= url.port <= 65535)
        ):
            raise ValueError
    except (ArgumentError, ValueError, TypeError):
        raise ValueError(
            "database URL must be a PostgreSQL URI with user, host, and database; "
            "percent-encode credentials and configure TLS outside the URL"
        ) from None
    if url.port == 6543 and url.host.endswith((".supabase.co", ".supabase.com")):
        raise ValueError("use the Supabase direct or session connection on port 5432")
    return url.set(drivername="postgresql+asyncpg")
