# HireAndTech Backend

Production-oriented FastAPI backend for HireAndTech, a global job intelligence and
application-management platform. This repository is intentionally independent from
the HireAndTech frontend.

## Current scope

The current backend includes the production application foundation plus PostgreSQL
persistence, authenticated access control, and IP security:

- versioned FastAPI routing and a dependency-free health endpoint;
- typed environment configuration with deployment-safety validation;
- JSON structured logging and request correlation IDs;
- safe, consistent error handling;
- explicit Host and CORS allowlists;
- asynchronous PostgreSQL persistence and Alembic migrations;
- Supabase JWT identity verification and local profile authorization;
- trusted-proxy-aware IP allowlisting and append-oriented security auditing;
- bounded route-specific rate limiting for authentication and security administration;
- unit and HTTP integration test foundations;
- linting, strict type checking, coverage, and container configuration.

Queues and business domains remain deferred to their dedicated incremental phases.

## Implementation Phases

- [Phase 2 — PostgreSQL Persistence Foundation](docs/phases/phase-02-persistence-foundation.md)
- [Phase 3 — Authenticated User Access Control](docs/phases/phase-03-authenticated-access-control.md)
- [Phase 4 — IP Security](docs/phases/phase-04-ip-security.md)

## Architecture

```text
app/
├── api/root.py         Public, unversioned API landing endpoint
├── api/v1/             Versioned HTTP routing and endpoints
├── auth/               Supabase JWT verification and access dependencies
├── core/               Configuration, errors, logging, and middleware
├── db/                 Async PostgreSQL engine, sessions, and shared mappings
├── domain/             Application persistence models and domain values
├── repositories/       Focused database access
├── schemas/            Validated public API contracts
└── main.py             Application factory and assembly
migrations/             Alembic environment and ordered database revisions
docs/phases/            Detailed implementation-phase documentation
tests/
├── unit/               Isolated configuration and utility tests
└── integration/        Full HTTP application behavior tests
```

`create_app()` is the composition boundary. Tests inject an explicit `Settings`
instance, while deployed processes load `HIREANDTECH_*` environment variables.

## Requirements

- Python 3.12 (pinned in `.python-version` and used by the production image)
- [uv](https://docs.astral.sh/uv/) (recommended)

## Local setup

```powershell
Copy-Item .env.example .env
uv sync
uv run uvicorn app.main:app --reload
```

Populate the copied `.env` with local values before starting the application; the
tracked template intentionally contains no credentials.

Local URLs with the default port and API prefix:

| Endpoint | URL |
| --- | --- |
| API root | `http://127.0.0.1:8000/` |
| Swagger | `http://127.0.0.1:8000/docs` |
| Health | `http://127.0.0.1:8000/api/v1/health` |
| Readiness | `http://127.0.0.1:8000/api/v1/health/ready` |
| Current user (bearer token required) | `http://127.0.0.1:8000/api/v1/auth/me` |
| IP security administration | `http://127.0.0.1:8000/api/v1/admin/security/ip/current` |

`GET /` returns public API metadata and relative docs/health links. It requires no
authentication and performs no database, Supabase, or readiness checks. The docs
link is `null` in staging/production, where Swagger is disabled. The health link
follows the configured API prefix. The application startup database check remains
unchanged.

If port 8000 is occupied, choose another port with `--port 8001` and use that port
in the URLs above. Restart a server started without `--reload` after code changes.

## Quality checks

Run the same checks expected before every commit:

```powershell
uv run pytest --cov=app --cov-report=term-missing
uv run ruff check .
uv run ruff format --check .
uv run mypy app tests
```

Perform a startup smoke check with:

```powershell
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

To inspect registered routes with the locked FastAPI version:

```powershell
uv run python -c "from app.main import app; from fastapi.routing import iter_route_contexts; [print(','.join(sorted(r.methods or [])), r.path) for r in iter_route_contexts(app.routes) if r.path is not None]"
```

FastAPI 0.137+ preserves included routers in `app.routes`, so a shallow `.path`
filter can hide working endpoints behind `_IncludedRouter` entries. The public
`iter_route_contexts()` helper (added in 0.137.2) resolves nested routes and their
prefixes; see the [FastAPI release notes](https://fastapi.tiangolo.com/release-notes/#01372-2026-06-18).
With the default API prefix, the output includes `GET /`, `GET /api/v1/auth/me`,
`GET /api/v1/health`, and `GET /api/v1/health/ready`. Route registration does not
require database startup; `/auth/me` without a bearer token should return 401.

## Environment variables

All variables use the `HIREANDTECH_` prefix. See `.env.example` for the local
configuration template and fill its blank assignments before startup.

| Variable | Purpose | Local default |
| --- | --- | --- |
| `HIREANDTECH_ENVIRONMENT` | `local`, `test`, `staging`, or `production` | `local` |
| `HIREANDTECH_LOG_LEVEL` | Application logging threshold | `INFO` |
| `HIREANDTECH_ALLOWED_HOSTS` | JSON array of accepted HTTP Host values | localhost only |
| `HIREANDTECH_CORS_ALLOWED_ORIGINS` | JSON array of browser origins | local frontend |
| `HIREANDTECH_TRUSTED_PROXY_CIDRS` | Peers permitted to supply forwarding chains | `[]` |
| `HIREANDTECH_IP_ALLOWLIST_ENABLED` | Enforce persistent CIDR rules | `false` |
| `HIREANDTECH_IP_ALLOWLIST_FAIL_CLOSED` | Deny on rule-store failure | `true` |
| `HIREANDTECH_IP_EMERGENCY_BYPASS_CIDRS` | Configuration-only recovery networks | `[]` |

Wildcard Host and CORS entries are rejected. Staging and production must provide
explicit non-local allowlists. Secrets must be supplied through the deployment's
secret manager and must never be added to `.env.example` or committed `.env` files.

## Authentication and authorization

Supabase Auth is the identity provider; HireAndTech does not expose public signup or
store passwords. Administrators provision a matching record in
`hireandtech.profiles`. Requests follow this trust path:

```text
Frontend -> Supabase Auth -> bearer access token -> FastAPI JWT verification
         -> local profile lookup -> active check -> application role authorization
```

JWT signatures are verified against the project's JWKS with issuer, audience,
expiration, issued-at, subject, and asymmetric-algorithm checks. The provider `role`
claim is never used for HireAndTech authorization. Employee/admin access comes only
from the active local profile, and a missing profile is not created automatically.

Authentication requires `HIREANDTECH_SUPABASE_URL` (for example,
`https://YOUR_PROJECT_REF.supabase.co`) and
`HIREANDTECH_SUPABASE_JWT_AUDIENCE` (normally `authenticated`). Neither value is a
secret; provider keys, JWTs, and database credentials must not be committed.

## IP security

IP policy is an additional control and never replaces Supabase identity or the local
application role. The socket peer is used by default. `X-Forwarded-For` is considered
only when that peer is inside `HIREANDTECH_TRUSTED_PROXY_CIDRS`; trusted proxy hops are
then removed from right to left. `X-Real-IP` is never authoritative. Configure only the
proxies that connect directly to Uvicorn and correctly append forwarding information.
Malformed or missing forwarding chains from trusted proxies resolve to no client IP and
fail closed when allowlisting is enabled; the proxy address is never used as the client.

When enabled, persistent `hireandtech.ip_access_rules` are checked before authentication.
Only `OPTIONS`, liveness, and readiness bypass the database policy. Database failures
deny by default; fail-open is accepted only in local/test. Configuration-only emergency
CIDRs permit recovery and generate audit events when the database is available. There
is no unauthenticated recovery endpoint.

Administrators manage rules and inspect audit history beneath `/api/v1/admin/security`.
Disabling or deleting the final rule matching the current administrator is rejected
unless their resolved IP is in an emergency recovery CIDR.

Phase 4 rate limits authentication and admin-security route groups using the trusted
resolved IP. Counters are capacity-bounded and per process. Multi-instance deployments
can replace the injectable store with shared infrastructure in a future operational
phase; Phase 4 does not introduce Redis or claim globally coordinated limits.

## Error and logging contracts

Errors use a stable envelope with a machine-readable code, safe message, and request
ID. Unexpected exception details stay in server-side logs. Each request returns an
`X-Request-ID`; a caller value is used only when it passes the conservative correlation
ID policy.

Logs are JSON objects intended for aggregation. Request bodies, authorization headers,
cookies, credentials, and tokens are not logged. Uvicorn access logging is disabled in
the container because application middleware emits the structured request record.

## Container

Build and run the non-root production image:

```powershell
docker build -t hireandtech-backend .
docker run --rm -p 8000:8000 --env-file .env hireandtech-backend
```

For staging and production, disable public access to `/docs`, terminate TLS at trusted
infrastructure, configure explicit public Host and frontend-origin values, and keep
trusted-proxy CIDRs synchronized with the direct application network path.
