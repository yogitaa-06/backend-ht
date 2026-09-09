"""HTTP behavior tests for IP allowlisting, exclusions, auditing, and throttling."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.middleware import RequestContextMiddleware
from app.domain.security import SecurityAuditEvent, SecurityAuditEventType
from app.security.ip import TrustedClientIpResolver
from app.security.middleware import IpSecurityMiddleware
from app.security.rate_limit import BoundedMemoryRateLimitStore, RouteRateLimiter

pytestmark = pytest.mark.anyio


class FakeSession:
    def __init__(self, *, commit_error: Exception | None = None) -> None:
        self.added: list[object] = []
        self.commits = 0
        self.commit_error = commit_error

    def add(self, value: object) -> None:
        self.added.append(value)

    async def commit(self) -> None:
        self.commits += 1
        if self.commit_error is not None:
            raise self.commit_error


class FakeDatabase:
    def __init__(self) -> None:
        self.session = FakeSession()

    @asynccontextmanager
    async def sessions(self) -> AsyncIterator[AsyncSession]:
        yield cast(AsyncSession, self.session)


class FakeRuleRepository:
    def __init__(self, allowed: bool | Exception) -> None:
        self.allowed = allowed
        self.calls: list[str] = []

    async def matches(
        self, _: AsyncSession, client_ip: str, *, exclude_rule_id: object = None
    ) -> bool:
        self.calls.append(client_ip)
        if isinstance(self.allowed, Exception):
            raise self.allowed
        return self.allowed


class FailingRateLimitStore:
    async def consume(self, key: str, *, limit: int, window_seconds: int) -> object:
        raise RuntimeError("rate-limit backend detail")


def settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "_env_file": None,
        "environment": "test",
        "allowed_hosts": ["testserver"],
        "cors_allowed_origins": ["http://frontend.test"],
        "ip_allowlist_enabled": True,
        "rate_limit_enabled": False,
    }
    values.update(overrides)
    return Settings(**values)


def build_app(
    config: Settings,
    rules: FakeRuleRepository,
    *,
    rate_store: object | None = None,
) -> tuple[FastAPI, FakeDatabase]:
    app = FastAPI()
    database = FakeDatabase()
    app.add_api_route("/private", lambda: {"ok": True})
    app.add_api_route("/api/v1/auth/me", lambda: {"ok": True})
    app.add_api_route("/api/v1/admin/security/ip-rules", lambda: {"ok": True})
    app.add_api_route("/api/v1/health", lambda: {"status": "ok"})
    app.add_api_route("/api/v1/health/ready", lambda: {"status": "ready"})
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_allowed_origins,
        allow_methods=["GET", "OPTIONS"],
        allow_headers=["Authorization"],
    )
    app.add_middleware(
        IpSecurityMiddleware,
        settings=config,
        resolver=TrustedClientIpResolver(config.trusted_proxy_cidrs),
        rate_limiter=RouteRateLimiter(
            cast(
                Any,
                rate_store or BoundedMemoryRateLimitStore(config.rate_limit_max_keys),
            ),
            fail_closed=config.rate_limit_fail_closed,
        ),
        rule_repository=cast(Any, rules),
    )
    app.add_middleware(RequestContextMiddleware)
    return app, database


async def request(
    app: FastAPI,
    *,
    path: str = "/private",
    method: str = "GET",
    headers: dict[str, str] | None = None,
    client_ip: str = "192.0.2.9",
) -> Response:
    transport = ASGITransport(app=app, client=(client_ip, 12345))
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.request(method, path, headers=headers)


async def test_allowlist_disabled_does_not_query_rules(monkeypatch: pytest.MonkeyPatch) -> None:
    rules = FakeRuleRepository(False)
    app, database = build_app(settings(ip_allowlist_enabled=False), rules)
    monkeypatch.setattr("app.security.middleware.get_database", lambda _: database)

    response = await request(app)

    assert response.status_code == 200
    assert rules.calls == []


@pytest.mark.parametrize(("allowed", "status_code"), [(True, 200), (False, 403)])
async def test_enabled_allowlist_matches_or_denies_and_audits(
    monkeypatch: pytest.MonkeyPatch, allowed: bool, status_code: int
) -> None:
    rules = FakeRuleRepository(allowed)
    app, database = build_app(settings(), rules)
    monkeypatch.setattr("app.security.middleware.get_database", lambda _: database)

    response = await request(app)

    assert response.status_code == status_code
    assert rules.calls == ["192.0.2.9"]
    events = [value for value in database.session.added if isinstance(value, SecurityAuditEvent)]
    if allowed:
        assert events == []
    else:
        assert events[0].event_type is SecurityAuditEventType.IP_ACCESS_DENIED
        assert "authorization" not in events[0].event_metadata


async def test_disabled_rule_does_not_match(monkeypatch: pytest.MonkeyPatch) -> None:
    rules = FakeRuleRepository(False)
    app, database = build_app(settings(), rules)
    monkeypatch.setattr("app.security.middleware.get_database", lambda _: database)

    assert (await request(app)).status_code == 403


async def test_overlapping_enabled_cidr_match_is_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    rules = FakeRuleRepository(True)
    app, database = build_app(settings(), rules)
    monkeypatch.setattr("app.security.middleware.get_database", lambda _: database)

    assert (await request(app, client_ip="10.2.3.4")).status_code == 200


@pytest.mark.parametrize(("fail_closed", "status_code"), [(True, 403), (False, 200)])
async def test_database_failure_obeys_policy(
    monkeypatch: pytest.MonkeyPatch, fail_closed: bool, status_code: int
) -> None:
    rules = FakeRuleRepository(RuntimeError("database detail"))
    app, database = build_app(settings(ip_allowlist_fail_closed=fail_closed), rules)
    monkeypatch.setattr("app.security.middleware.get_database", lambda _: database)

    response = await request(app)

    assert response.status_code == status_code
    assert "database detail" not in response.text


async def test_audit_failure_never_reverses_a_deny_decision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rules = FakeRuleRepository(False)
    app, database = build_app(settings(ip_allowlist_fail_closed=False), rules)
    database.session.commit_error = RuntimeError("audit unavailable")
    monkeypatch.setattr("app.security.middleware.get_database", lambda _: database)

    response = await request(app)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "IP_ACCESS_DENIED"


async def test_health_and_cors_preflight_are_intentionally_excluded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rules = FakeRuleRepository(False)
    app, database = build_app(settings(), rules)
    monkeypatch.setattr("app.security.middleware.get_database", lambda _: database)

    health = await request(app, path="/api/v1/health")
    readiness = await request(app, path="/api/v1/health/ready")
    preflight = await request(
        app,
        path="/private",
        method="OPTIONS",
        headers={"Origin": "http://frontend.test", "Access-Control-Request-Method": "GET"},
    )

    assert health.status_code == 200
    assert readiness.status_code == 200
    assert preflight.status_code == 200
    assert preflight.headers["Access-Control-Allow-Origin"] == "http://frontend.test"
    assert rules.calls == []


async def test_emergency_bypass_allows_and_creates_event(monkeypatch: pytest.MonkeyPatch) -> None:
    rules = FakeRuleRepository(False)
    app, database = build_app(
        settings(ip_emergency_bypass_cidrs=["192.0.2.9/32"]),
        rules,
    )
    monkeypatch.setattr("app.security.middleware.get_database", lambda _: database)

    response = await request(app)

    assert response.status_code == 200
    assert rules.calls == []
    event = cast(SecurityAuditEvent, database.session.added[0])
    assert event.event_type is SecurityAuditEventType.IP_EMERGENCY_BYPASS_USED


async def test_auth_route_limit_returns_429_with_retry_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rules = FakeRuleRepository(True)
    app, database = build_app(
        settings(
            ip_allowlist_enabled=False,
            rate_limit_enabled=True,
            rate_limit_auth_requests=1,
        ),
        rules,
    )
    monkeypatch.setattr("app.security.middleware.get_database", lambda _: database)

    first = await request(app, path="/api/v1/auth/me")
    second = await request(app, path="/api/v1/auth/me")

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "RATE_LIMITED"
    assert second.headers["Retry-After"] == "60"


async def test_admin_security_route_limit_returns_429_with_retry_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rules = FakeRuleRepository(True)
    app, database = build_app(
        settings(
            ip_allowlist_enabled=False,
            rate_limit_enabled=True,
            rate_limit_admin_security_requests=1,
        ),
        rules,
    )
    monkeypatch.setattr("app.security.middleware.get_database", lambda _: database)

    first = await request(app, path="/api/v1/admin/security/ip-rules")
    second = await request(app, path="/api/v1/admin/security/ip-rules")

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "RATE_LIMITED"
    assert second.headers["Retry-After"] == "60"


@pytest.mark.parametrize(("fail_closed", "status_code"), [(True, 503), (False, 200)])
async def test_rate_limit_store_failure_http_behavior(
    monkeypatch: pytest.MonkeyPatch,
    fail_closed: bool,
    status_code: int,
) -> None:
    rules = FakeRuleRepository(True)
    app, database = build_app(
        settings(
            ip_allowlist_enabled=False,
            rate_limit_enabled=True,
            rate_limit_fail_closed=fail_closed,
        ),
        rules,
        rate_store=FailingRateLimitStore(),
    )
    monkeypatch.setattr("app.security.middleware.get_database", lambda _: database)

    response = await request(app, path="/api/v1/auth/me")

    assert response.status_code == status_code
    assert "rate-limit backend detail" not in response.text
    if fail_closed:
        assert response.json()["error"]["code"] == "RATE_LIMIT_UNAVAILABLE"


async def test_malformed_forwarded_chain_from_trusted_proxy_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rules = FakeRuleRepository(True)
    app, database = build_app(
        settings(trusted_proxy_cidrs=["10.0.0.0/8"]),
        rules,
    )
    monkeypatch.setattr("app.security.middleware.get_database", lambda _: database)

    response = await request(
        app,
        headers={"X-Forwarded-For": "malformed, 192.0.2.9"},
        client_ip="10.0.0.4",
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "IP_ACCESS_DENIED"
    assert rules.calls == []


async def test_trusted_forwarded_ip_is_used_for_allowlist_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rules = FakeRuleRepository(True)
    app, database = build_app(
        settings(trusted_proxy_cidrs=["10.0.0.0/8"]),
        rules,
    )
    monkeypatch.setattr("app.security.middleware.get_database", lambda _: database)

    response = await request(
        app,
        headers={"X-Forwarded-For": "198.51.100.7"},
        client_ip="10.0.0.4",
    )

    assert response.status_code == 200
    assert rules.calls == ["198.51.100.7"]
