# Security Documentation

This document describes the security model implemented in the **HireAndTech** backend.

## Authentication & Authorization
* **OAuth2 JWT** – All API endpoints are protected by a Bearer token issued by the internal auth service (`/auth/token`).  The token payload contains the `sub` (user UUID) and optional role claims.
* **FastAPI dependencies** – `app.api.dependencies.get_current_user` validates the token, checks expiration, and returns a `Profile` domain object.
* **Role‑Based Access** – Endpoints use the `profile.has_role(...)` helper to enforce admin‑only actions (e.g., IP rule management, job source admin endpoints).

## IP Trust & Rate Limiting
* **TrustedClientIpResolver** (see `app/security/ip.py`) resolves the client IP while ignoring untrusted `X‑Forwarded‑For` headers unless the source IP belongs to a configured trusted proxy CIDR list (`settings.ip_trusted_proxy_cidrs`).
* **IpSecurityMiddleware** (see `app/security/middleware.py`) runs before authentication. It enforces:
  * **Allow‑list** – Optional CIDR allow‑list (`settings.ip_allowlist_enabled`).  Requests not matching an enabled rule are rejected with `403`.
  * **Emergency Bypass** – Administrators can define emergency CIDRs (`settings.ip_emergency_bypass_cidrs`) that bypass the allow‑list.
  * **Rate Limiting** – Fixed‑window per‑IP limits via `IpSecurityMiddleware` + `RouteRateLimiter`.  Limits are configurable per route group in `Settings`.
* **Audit Logging** – Every allow‑list decision and rate‑limit violation creates a `SecurityAuditEvent` (see `app/security/service.py`).  Events are stored in the `security_audit_events` table and include a sanitized user‑agent and request IP.

## Secrets Management
* All secrets (JWT signing key, DB password, third‑party API keys) are read from environment variables and loaded by `app.core.config.Settings`.  No secret is committed to source control.
* In production the service expects a **Docker secret** or **Kubernetes secret** mounted as an env var.

## Database Hardening
* The PostgreSQL user defined in `DATABASE_URL` has the least privileges required: `SELECT`, `INSERT`, `UPDATE`, `DELETE` on the application schemas and `EXECUTE` on required functions.
* Row‑level security is **not** used; the application enforces access control in the service layer.

## Transport Security
* The API is served behind an **HTTPS terminator** (NGINX or Cloud‑load‑balancer).  `uvicorn` runs with HTTP only on the internal port.

## Security‑Related Settings (excerpt from `app/core/config.py`)
```
class Settings(BaseSettings):
    # Authentication
    jwt_secret_key: SecretStr
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    # IP security
    ip_allowlist_enabled: bool = False
    ip_allowlist_fail_closed: bool = True
    ip_emergency_bypass_cidrs: list[IpNetwork] = []
    ip_trusted_proxy_cidrs: list[IpNetwork] = []

    # Rate limiting
    rate_limit_enabled: bool = True
    rate_limit_fail_closed: bool = False
    rate_limit_window_seconds: int = 60
    rate_limit_admin_security_requests: int = 30
    rate_limit_auth_requests: int = 120
    rate_limit_resume_write_requests: int = 10
```

## Operational Controls
* **Pre‑commit hooks** run `ruff` and `mypy`; they catch insecure patterns such as hard‑coded secrets.
* **CI pipeline** includes a secret‑scan step (`truffleHog`) to ensure no credentials are leaked.
* **Audit alerts** – SecurityAuditEvents with type `IP_ACCESS_DENIED` or `RATE_LIMITED` trigger alerts in the observability stack (Grafana Loki + Alertmanager).

---
*All statements reflect the current repository implementation; no code changes are performed by this document.*
