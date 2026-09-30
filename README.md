# HireAndTech Backend

HireAndTech is a modular FastAPI backend for collecting public job listings,
normalizing them into a shared PostgreSQL catalog, serving job browsing and
deterministic recommendations, and managing private candidate resumes. FastAPI,
scrape workers, and search workers are separate processes in one modular monolith.

## Architecture status

| Capability | Status | Notes |
| --- | --- | --- |
| Supabase JWT authentication and local roles | IMPLEMENTED | JWKS signature, issuer, audience, expiry, and active-profile checks |
| PostgreSQL and Alembic | IMPLEMENTED | Async SQLAlchemy; migrations are a deployment step |
| Job collection | IMPLEMENTED | Dice, LinkedIn, Glassdoor, and HiringCafe adapters |
| Canonical job ingestion | PARTIAL | Same-source identity is safe; cross-source merging is deliberately disabled |
| Legacy `global_jobs` compatibility | IMPLEMENTED | Collection dual-writes while reads migrate to canonical tables |
| Job browsing and recommendations | IMPLEMENTED | Canonical reads plus deterministic matching |
| Async user search | PARTIAL | API and queue lifecycle exist; candidate retrieval/result persistence do not |
| Resume management | IMPLEMENTED | Private storage, validation, parsing, compensation, reconciliation |
| Admin and IP security | IMPLEMENTED | Local authorization, CIDR policy, audit records, security headers |
| Rate limiting | PARTIAL | Bounded and process-local; no Redis-backed distributed store yet |
| AI, notifications, applications | PLANNED | No production implementation is claimed |

See [architecture.md](docs/architecture.md) and
[backend-structure.md](docs/backend-structure.md) for dependency rules and ownership.

## Technology

- Python 3.12, FastAPI, Pydantic Settings
- PostgreSQL, SQLAlchemy async, Alembic
- Redis and ARQ
- httpx, curl-cffi, and Playwright for source-specific collection
- uv, Ruff, mypy, pytest, and coverage

## Important structure

```text
app/
├── api/                    HTTP routers and response mapping
├── auth/                   Supabase verification and auth dependencies
├── core/                   Settings, errors, logging, middleware
├── db/                     SQLAlchemy base, engine, and sessions
├── domain/                 SQLAlchemy persistence models
├── jobs/
│   ├── ingestion/          Normalization, canonicalization, dedupe, freshness, service
│   ├── matching/           Eligibility, typed scores, scoring, ranking
│   ├── parsing/            Shared deterministic field parsers
│   └── sources/            Provider-owned integrations and registry
├── queue/
│   ├── scheduler/          Collection scheduling policy
│   ├── tasks/              Thin ARQ entrypoints
│   └── workers/            Independently runnable worker settings
├── resumes/                Resume service, repository, parsing, storage, validation
├── search/                 Async search service, repository, and execution lifecycle
└── security/               IP policy, auditing, rate limiting, repository
migrations/                 Immutable Alembic history
scripts/                    Explicit operator/developer utilities
tests/{unit,integration}/   Behavior-focused tests
docs/                       Current architecture and operations documentation
```

Compatibility modules under `app/jobs`, `app/queue`, and `app/repositories` preserve
established imports during the migration. New code should import the domain-owned
modules shown above.

## Local requirements

- Python 3.12 (also pinned by `.python-version`)
- [uv](https://docs.astral.sh/uv/)
- PostgreSQL for persistence and database integration tests
- Redis for collection/search workers
- Chromium installed through Playwright only when running HiringCafe collection
- Docker, optionally, for image validation

## Setup

```powershell
Copy-Item .env.example .env
uv sync --frozen
uv run playwright install chromium
```

Fill `.env` with local values. `.env` is ignored and must never be committed.
PostgreSQL URLs must use the `postgresql://` or `postgresql+asyncpg://` scheme. Local
plaintext database connections require `HIREANDTECH_DATABASE_SSL_MODE=disable`.

Create or upgrade the schema:

```powershell
uv run alembic heads
uv run alembic upgrade head
```

Start the API:

```powershell
uv run uvicorn app.main:app --reload
```

The process liveness endpoint is `GET /api/v1/health`; dependency readiness is
`GET /api/v1/health/ready`. Readiness checks PostgreSQL. Optional scraper source
availability does not affect liveness.

## Workers and collection

Start Redis before the workers, set `HIREANDTECH_REDIS_URL`, and enable collection
only in the scrape-worker environment.

```powershell
# Scrape scheduler + collection worker (preferred path)
uv run arq app.queue.workers.scrape.ScrapeWorkerSettings

# Backward-compatible scrape-worker path
uv run arq app.queue.worker.WorkerSettings

# Async search lifecycle worker
uv run arq app.queue.workers.search.SearchWorkerSettings
```

Run configured collectors directly without ARQ:

```powershell
uv run python scripts/collect_jobs.py
```

Live source scripts under `scripts/` are optional smoke/debug tools and are not part
of unit tests or CI. They make external requests and may be blocked or rate limited.

## Quality and tests

```powershell
uv lock --check
uv run ruff check .
uv run ruff format --check .
uv run mypy app tests
uv run pytest
uv run pytest --cov=app --cov-report=term-missing
```

Database tests are skipped unless `HIREANDTECH_TEST_DATABASE_URL` points to a
disposable PostgreSQL database. Never point it at shared or production data.

```powershell
$env:HIREANDTECH_TEST_DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/hireandtech_test"
uv run pytest -m database
```

The configured coverage gate is 90%. The current branch remains below that target;
the gap is tracked as a known quality limitation rather than hidden by lowering the
threshold.

## Docker

```powershell
docker build -t hireandtech-backend .
docker run --rm -p 8000:8000 --env-file .env hireandtech-backend
```

The non-root image starts only the API. Run migrations as a separate release step
and deploy worker commands as separate processes from the same image.

## Security and operations

- Secrets use `SecretStr` and deployment secret injection; tokens and resume bodies
  are excluded from structured logs.
- Forwarded IP headers are trusted only from configured proxy CIDRs.
- In-memory rate-limit counters are per process. Horizontal deployments need a
  future Redis `RateLimitStore` implementation for global limits.
- Source retries apply only to transient failures. No production circuit breaker is
  implemented yet.
- Existing migrations are immutable; schema changes require a new revision and one
  expected Alembic head.

## Known limitations

- Dice parsing is still a large cohesive parser inside its provider package and is a
  candidate for a later behavior-preserving parser/mapper extraction.
- Cross-source duplicate candidates are never auto-merged.
- Async search intentionally ends in `candidate_retrieval_not_implemented`; it does
  not fabricate completed results.
- No AI provider, AI worker, notifications worker, applications domain, distributed
  rate limiter, circuit breaker, or OpenTelemetry/Prometheus export is implemented.
- PostgreSQL full-text/trigram search and keyset pagination remain future work.

Further setup and operational detail lives in [development.md](docs/development.md)
and [deployment.md](docs/deployment.md).
