"""ASGI enforcement for trusted IPs, persistent allowlisting, and route limits.

Preflight and health/readiness requests bypass the database-backed allowlist so edge
health checks and browser CORS negotiation remain operational. All other requests are
resolved and enforced before FastAPI authentication dependencies execute.
"""

import logging

from fastapi import status
from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.config import Settings
from app.core.errors import ApplicationError, application_error_handler
from app.db.session import get_database
from app.domain.security import SecurityAuditEventType
from app.repositories.security import IpRuleRepository
from app.security.ip import IpAddress, TrustedClientIpResolver, address_in_networks
from app.security.rate_limit import RateLimitStoreError, RouteRateLimiter
from app.security.service import add_audit_event, audit_context

logger = logging.getLogger(__name__)


class IpSecurityMiddleware:
    """Enforce security controls without treating IP addresses as user identity."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        settings: Settings,
        resolver: TrustedClientIpResolver,
        rate_limiter: RouteRateLimiter,
        rule_repository: IpRuleRepository | None = None,
    ) -> None:
        self.app = app
        self.settings = settings
        self.resolver = resolver
        self.rate_limiter = rate_limiter
        self.rules = rule_repository or IpRuleRepository()
        prefix = settings.api_v1_prefix
        self._health_paths = frozenset({f"{prefix}/health", f"{prefix}/health/ready"})

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        client_ip = self._resolve_request_ip(scope)
        scope.setdefault("state", {})["resolved_client_ip"] = client_ip
        excluded = request.method == "OPTIONS" or request.url.path in self._health_paths

        if self.settings.ip_allowlist_enabled and not excluded:
            outcome = await self._enforce_allowlist(request, client_ip)
            if outcome is not None:
                await self._send_error(request, outcome, scope, receive, send)
                return

        rate_error = await self._enforce_rate_limit(request, client_ip, excluded=excluded)
        if rate_error is not None:
            await self._send_error(request, rate_error, scope, receive, send)
            return
        await self.app(scope, receive, send)

    def _resolve_request_ip(self, scope: Scope) -> IpAddress | None:
        client = scope.get("client")
        peer_host = client[0] if client else None
        forwarded_values = [
            value.decode("latin-1")
            for name, value in scope.get("headers", [])
            if name.lower() == b"x-forwarded-for"
        ]
        return self.resolver.resolve(peer_host, forwarded_values=forwarded_values)

    async def _enforce_allowlist(
        self, request: Request, client_ip: IpAddress | None
    ) -> ApplicationError | None:
        if client_ip is not None and address_in_networks(
            client_ip, self.settings.ip_emergency_bypass_cidrs
        ):
            await self._record_request_event(
                request, client_ip, SecurityAuditEventType.IP_EMERGENCY_BYPASS_USED
            )
            return None
        try:
            database = get_database(request)
            async with database.sessions() as session:
                allowed = client_ip is not None and await self.rules.matches(
                    session, str(client_ip)
                )
        except Exception:
            logger.warning("ip_allowlist_database_failure", extra={"operation": "ip_allowlist"})
            if self.settings.ip_allowlist_fail_closed:
                return _access_denied()
            return None
        if not allowed:
            await self._record_request_event(
                request,
                client_ip,
                SecurityAuditEventType.IP_ACCESS_DENIED,
                metadata={"method": request.method},
            )
            return _access_denied()
        return None

    async def _record_request_event(
        self,
        request: Request,
        client_ip: IpAddress | None,
        event_type: SecurityAuditEventType,
        *,
        metadata: dict[str, object] | None = None,
    ) -> None:
        try:
            database = get_database(request)
            async with database.sessions() as session:
                add_audit_event(
                    session,
                    event_type,
                    audit_context(None, client_ip, request.headers.get("user-agent")),
                    resource_type="http_request",
                    metadata=metadata,
                )
                await session.commit()
        except Exception:
            logger.warning("security_audit_write_failed", extra={"operation": "security_audit"})

    async def _enforce_rate_limit(
        self, request: Request, client_ip: IpAddress | None, *, excluded: bool
    ) -> ApplicationError | None:
        if not self.settings.rate_limit_enabled or excluded:
            return None
        policy = self._rate_policy(request.method, request.url.path)
        if policy is None:
            return None
        route_group, limit = policy
        try:
            decision = await self.rate_limiter.check(
                route_group,
                str(client_ip) if client_ip is not None else "unresolved",
                limit=limit,
                window_seconds=self.settings.rate_limit_window_seconds,
            )
        except RateLimitStoreError:
            return ApplicationError(
                "RATE_LIMIT_UNAVAILABLE",
                "The service is temporarily unavailable.",
                status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        if decision is not None and not decision.allowed:
            return ApplicationError(
                "RATE_LIMITED",
                "Too many requests.",
                status.HTTP_429_TOO_MANY_REQUESTS,
                headers={"Retry-After": str(decision.retry_after_seconds)},
            )
        return None

    def _rate_policy(self, method: str, path: str) -> tuple[str, int] | None:
        prefix = self.settings.api_v1_prefix
        if path.startswith(f"{prefix}/admin/security"):
            return "admin-security", self.settings.rate_limit_admin_security_requests
        if path.startswith(f"{prefix}/auth"):
            return "authentication", self.settings.rate_limit_auth_requests
        resumes_path = f"{prefix}/resumes"
        if method == "POST" and (
            path == resumes_path
            or (path.startswith(f"{resumes_path}/") and path.endswith("/replace"))
        ):
            return "resume-write", self.settings.rate_limit_resume_write_requests
        return None

    @staticmethod
    async def _send_error(
        request: Request,
        error: ApplicationError,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        response = await application_error_handler(request, error)
        await response(scope, receive, send)


def _access_denied() -> ApplicationError:
    return ApplicationError(
        "IP_ACCESS_DENIED", "Access is not permitted.", status.HTTP_403_FORBIDDEN
    )
