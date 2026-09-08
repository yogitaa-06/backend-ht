"""Local verification of Supabase access tokens against the project's JWKS."""

import asyncio
import json
from collections.abc import Awaitable, Callable
from time import monotonic
from typing import Any, cast
from urllib.request import Request, urlopen
from uuid import UUID

import jwt
from jwt import PyJWK

from app.auth.claims import VerifiedClaims
from app.core.config import Settings

ALLOWED_ALGORITHMS = frozenset({"ES256", "RS256"})
JWKS_MAX_BYTES = 1_048_576

type JwksDocument = dict[str, object]
type JwksFetcher = Callable[[str], Awaitable[JwksDocument]]
type Clock = Callable[[], float]


class InvalidAccessTokenError(Exception):
    """The bearer token cannot establish a trusted identity."""


class JwksUnavailableError(Exception):
    """Authentication key infrastructure is unavailable or unusable."""


def _fetch_jwks_sync(url: str) -> JwksDocument:
    request = Request(  # noqa: S310 - Settings permits HTTPS origins only.
        url, headers={"Accept": "application/json"}, method="GET"
    )
    with urlopen(request, timeout=5) as response:  # noqa: S310 - URL validated by Settings.
        body = response.read(JWKS_MAX_BYTES + 1)
    if len(body) > JWKS_MAX_BYTES:
        raise ValueError("JWKS response is too large")
    payload = json.loads(body)
    if not isinstance(payload, dict):
        raise ValueError("JWKS response must be an object")
    return cast(JwksDocument, payload)


async def fetch_jwks(url: str) -> JwksDocument:
    """Fetch a bounded JWKS document without blocking the event loop."""
    return await asyncio.to_thread(_fetch_jwks_sync, url)


class SupabaseJwtVerifier:
    """Verify Supabase access tokens with a small, rotation-aware JWKS cache."""

    def __init__(
        self,
        settings: Settings,
        *,
        fetcher: JwksFetcher = fetch_jwks,
        cache_ttl_seconds: float = 600,
        unknown_kid_refresh_cooldown_seconds: float = 60,
        clock: Clock = monotonic,
    ) -> None:
        self._issuer = settings.supabase_jwt_issuer
        self._audience = settings.supabase_jwt_audience
        self._jwks_url = settings.supabase_jwks_url
        self._fetcher = fetcher
        self._cache_ttl_seconds = cache_ttl_seconds
        self._unknown_kid_refresh_cooldown_seconds = unknown_kid_refresh_cooldown_seconds
        self._clock = clock
        self._keys: dict[str, PyJWK] = {}
        self._fetched_at: float | None = None
        self._last_unknown_kid_refresh_at: float | None = None
        self._lock = asyncio.Lock()

    async def verify(self, token: str) -> VerifiedClaims:
        """Verify token integrity and required claims, then return trusted identity data."""
        if self._issuer is None or self._jwks_url is None:
            raise JwksUnavailableError

        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise InvalidAccessTokenError from exc

        algorithm = header.get("alg")
        key_id = header.get("kid")
        if algorithm not in ALLOWED_ALGORITHMS or not isinstance(key_id, str) or not key_id:
            raise InvalidAccessTokenError

        signing_key = await self._get_signing_key(key_id)
        if signing_key is None or signing_key.algorithm_name != algorithm:
            raise InvalidAccessTokenError

        try:
            raw_claims = jwt.decode(
                token,
                key=signing_key.key,
                algorithms=[algorithm],
                audience=self._audience,
                issuer=self._issuer,
                options={"require": ["exp", "iat", "sub"]},
            )
        except (jwt.PyJWTError, TypeError, ValueError) as exc:
            raise InvalidAccessTokenError from exc

        subject_value = raw_claims.get("sub")
        if not isinstance(subject_value, str):
            raise InvalidAccessTokenError
        try:
            subject = UUID(subject_value)
        except ValueError as exc:
            raise InvalidAccessTokenError from exc

        email_value = raw_claims.get("email")
        session_value = raw_claims.get("session_id")
        provider_role_value = raw_claims.get("role")
        return VerifiedClaims(
            subject=subject,
            email=email_value if isinstance(email_value, str) else None,
            session_id=session_value if isinstance(session_value, str) else None,
            provider_role=provider_role_value if isinstance(provider_role_value, str) else None,
        )

    async def _get_signing_key(self, key_id: str) -> PyJWK | None:
        keys, fetched_at = await self._get_cached_keys()
        signing_key = keys.get(key_id)
        if signing_key is not None:
            return signing_key

        keys = await self._refresh_for_unknown_key(fetched_at)
        return keys.get(key_id)

    async def _get_cached_keys(self) -> tuple[dict[str, PyJWK], float]:
        async with self._lock:
            now = self._clock()
            if (
                self._fetched_at is None
                or not self._keys
                or now - self._fetched_at >= self._cache_ttl_seconds
            ):
                await self._fetch_keys()
            if self._fetched_at is None:  # pragma: no cover - established by _fetch_keys
                raise JwksUnavailableError
            return self._keys.copy(), self._fetched_at

    async def _refresh_for_unknown_key(self, observed_fetched_at: float) -> dict[str, PyJWK]:
        async with self._lock:
            now = self._clock()
            refreshed_by_another_request = self._fetched_at != observed_fetched_at
            refresh_on_cooldown = (
                self._last_unknown_kid_refresh_at is not None
                and now - self._last_unknown_kid_refresh_at
                < self._unknown_kid_refresh_cooldown_seconds
            )
            if not refreshed_by_another_request and not refresh_on_cooldown:
                self._last_unknown_kid_refresh_at = now
                await self._fetch_keys()
            return self._keys.copy()

    async def _fetch_keys(self) -> None:
        if self._jwks_url is None:  # pragma: no cover - checked by verify
            raise JwksUnavailableError
        try:
            document = await self._fetcher(self._jwks_url)
            keys = self._parse_keys(document)
        except JwksUnavailableError:
            raise
        except Exception as exc:
            raise JwksUnavailableError from exc
        self._keys = keys
        self._fetched_at = self._clock()

    @staticmethod
    def _parse_keys(document: JwksDocument) -> dict[str, PyJWK]:
        raw_keys = document.get("keys")
        if not isinstance(raw_keys, list):
            raise JwksUnavailableError

        keys: dict[str, PyJWK] = {}
        for raw_key in raw_keys:
            if not isinstance(raw_key, dict):
                continue
            key_id = raw_key.get("kid")
            if not isinstance(key_id, str) or not key_id:
                continue
            try:
                key = PyJWK.from_dict(cast(dict[str, Any], raw_key))
            except (jwt.PyJWTError, ValueError, TypeError):
                continue
            if key.algorithm_name in ALLOWED_ALGORITHMS:
                keys[key_id] = key

        if not keys:
            raise JwksUnavailableError
        return keys
