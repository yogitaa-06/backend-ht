# HireAndTech Backend

Production-oriented FastAPI backend for HireAndTech, a global job intelligence and
application-management platform. This repository is intentionally independent from
the HireAndTech frontend.

## Current scope

Backend Phase 1 establishes the application foundation:

- versioned FastAPI routing and a dependency-free health endpoint;
- typed environment configuration with deployment-safety validation;
- JSON structured logging and request correlation IDs;
- safe, consistent error handling;
- explicit Host and CORS allowlists;
- unit and HTTP integration test foundations;
- linting, strict type checking, coverage, and container configuration.

Database access, authentication, IP policy enforcement, queues, and business domains
are deliberately deferred to their dedicated incremental phases.

## Architecture

```text
app/
├── api/v1/             Versioned HTTP routing and endpoints
├── core/               Configuration, errors, logging, and middleware
├── schemas/            Validated public API contracts
└── main.py             Application factory and assembly
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

The API is available at `http://127.0.0.1:8000`. Local interactive documentation is
at `/docs`; the liveness endpoint is `GET /api/v1/health`.

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

## Environment variables

All variables use the `HIREANDTECH_` prefix. See `.env.example` for copyable local
defaults.

| Variable | Purpose | Local default |
| --- | --- | --- |
| `HIREANDTECH_ENVIRONMENT` | `local`, `test`, `staging`, or `production` | `local` |
| `HIREANDTECH_LOG_LEVEL` | Application logging threshold | `INFO` |
| `HIREANDTECH_ALLOWED_HOSTS` | JSON array of accepted HTTP Host values | localhost only |
| `HIREANDTECH_CORS_ALLOWED_ORIGINS` | JSON array of browser origins | local frontend |

Wildcard Host and CORS entries are rejected. Staging and production must provide
explicit non-local allowlists. Secrets must be supplied through the deployment's
secret manager and must never be added to `.env.example` or committed `.env` files.

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
infrastructure, and configure explicit public Host and frontend-origin values. Proxy
trust and client IP resolution will be introduced and documented in the dedicated IP
security phase; forwarding headers must not be trusted until then.

##  phase 2


Production-oriented FastAPI backend for HireAndTech, a global job intelligence and
application-management platform.

This backend repository is intentionally independent from the HireAndTech frontend.
Frontend and backend are developed, tested, versioned, and committed separately.

## Current scope

Backend Phase 2 establishes the production application and PostgreSQL persistence
foundation.

Implemented capabilities include:

- versioned FastAPI API routing;
- application liveness and database-readiness endpoints;
- typed environment configuration and deployment-safety validation;
- JSON structured logging and request correlation IDs;
- safe and consistent application error handling;
- explicit Host and CORS allowlists;
- asynchronous PostgreSQL connectivity through SQLAlchemy 2 and asyncpg;
- bounded database connection pooling;
- database connection, pool, and statement timeouts;
- configurable PostgreSQL TLS policy;
- request-scoped asynchronous database sessions;
- private application PostgreSQL schema;
- deterministic SQLAlchemy constraint naming conventions;
- reusable UUID and timestamp persistence conventions;
- Alembic migration framework;
- migration-specific database connections;
- unit and integration tests using real PostgreSQL;
- linting, formatting, strict type checking, and coverage enforcement.

Authentication, user profiles, IP access control, job-domain tables, queues, workers,
scraping, matching, and AI processing are deliberately deferred to their dedicated
incremental phases.

## Architecture

```text
Client
  |
  v
FastAPI
  |
  +--> API v1 routes
  |
  +--> configuration / logging / errors / middleware
  |
  v
Database dependency
  |
  v
SQLAlchemy 2 async
  |
  v
asyncpg
  |
  v
PostgreSQL
     |
     +--> private "hireandtech" schema
     |
     +--> Alembic migration history
