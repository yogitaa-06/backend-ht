# Phase 2 — PostgreSQL Persistence Foundation

## 1. Purpose

Phase 2 gives HireAndTech a production-oriented persistence boundary for later domain
data. It standardizes how the application validates PostgreSQL configuration, owns
connections, creates asynchronous sessions, maps shared columns, applies schema changes,
reports database readiness, and handles database failures.

The phase deliberately establishes infrastructure before adding business tables. Its
only revision, `0001_persistence_foundation`, secures Alembic bookkeeping in the private
application schema. Domain tables arrive in later revisions; the current repository's
`0002_profiles` revision is documented in
[Phase 3](phase-03-authenticated-access-control.md).

## 2. Architecture

```mermaid
flowchart TD
    API[FastAPI application and dependencies]
    DB[Database resource and session factory]
    ORM[SQLAlchemy 2 async engine and ORM]
    DRIVER[asyncpg driver]
    PG[(PostgreSQL)]

    API --> DB --> ORM --> DRIVER --> PG
```

| Layer | Responsibility |
| --- | --- |
| FastAPI | Owns the database resource for the application lifespan and injects request-scoped sessions. |
| `Database` | Configures pooling, sessions, bounded connection probes, and engine disposal. |
| SQLAlchemy 2 async | Provides declarative mappings, transactions, the async engine, and `AsyncSession`. |
| asyncpg | Implements the PostgreSQL wire connection beneath SQLAlchemy. |
| PostgreSQL | Generates durable identifiers and timestamps and stores application and migration state. |

## 3. Database Design

The persistence implementation is PostgreSQL-specific:

- `app/db/urls.py` accepts `postgres`, `postgresql`, or `postgresql+asyncpg` URLs and
  normalizes them to the `postgresql+asyncpg` SQLAlchemy driver.
- `app/db/base.py` declares one metadata boundary for the `hireandtech` schema and a
  deterministic naming convention for indexes and constraints.
- `IdentityTimestampMixin` supplies a PostgreSQL-generated UUID primary key plus
  timezone-aware `created_at` and `updated_at` columns.
- Both timestamps default to PostgreSQL `now()`. SQLAlchemy sets `updated_at` during ORM
  updates; raw SQL writers are responsible for updating it themselves.
- `app/db/session.py` creates the async engine and an `async_sessionmaker` configured with
  `expire_on_commit=False` and `autoflush=False`.
- `get_session()` yields one `AsyncSession` for a request or task. The dependency closes
  the session on exit, which rolls back unfinished work, but it does not commit for the
  caller.
- `Database.check_connection()` performs a bounded `SELECT 1` probe.
- `get_database()` and `get_session()` are the FastAPI dependency boundaries. A missing
  lifespan-owned database fails closed with a sanitized 503 error.

The normal runtime engine uses a bounded queue pool with pre-ping and 30-minute recycle.
Migrations use a separate `NullPool` engine so migration connections are not retained.

## 4. Private Application Schema

All mapped application objects use the PostgreSQL schema `hireandtech`; `Base.metadata`
sets it as the default schema. This keeps HireAndTech-owned data and Alembic state out of
PostgreSQL's default `public` schema and out of provider-managed schemas such as Supabase
Auth or Storage.

`migrations/env.py` creates the schema if needed, stores `alembic_version` inside it, and
restricts Alembic autogeneration reflection to that schema. Revision
`0001_persistence_foundation` revokes `PUBLIC` access to the schema and migration version
table. Its downgrade intentionally preserves the schema and those restrictions.

## 5. Database Configuration

`Settings` loads case-insensitive `HIREANDTECH_*` variables from the environment and,
for local use, `.env`. Database URLs are held as Pydantic `SecretStr` values and are not
embedded in `alembic.ini`.

| Environment variable | Purpose | Code default |
| --- | --- | --- |
| `HIREANDTECH_DATABASE_URL` | Runtime application connection. Also the migration fallback. | Not configured |
| `HIREANDTECH_DATABASE_MIGRATION_URL` | Optional migration-specific connection. | Not configured |
| `HIREANDTECH_DATABASE_SSL_MODE` | `disable` or `verify-full`. | `verify-full` |
| `HIREANDTECH_DATABASE_SSL_CA_FILE` | Optional CA file used by `verify-full`. | Not configured |
| `HIREANDTECH_DATABASE_POOL_SIZE` | Number of persistent runtime pool connections. | `5` |
| `HIREANDTECH_DATABASE_MAX_OVERFLOW` | Maximum temporary overflow connections. | `5` |
| `HIREANDTECH_DATABASE_POOL_TIMEOUT_SECONDS` | Maximum wait for a pooled connection. | `5` |
| `HIREANDTECH_DATABASE_CONNECT_TIMEOUT_SECONDS` | asyncpg connection timeout. | `5` |
| `HIREANDTECH_DATABASE_STATEMENT_TIMEOUT_SECONDS` | Client command and PostgreSQL statement timeout. | `10` |

Safe example values:

```dotenv
HIREANDTECH_DATABASE_URL=postgresql://USER:PASSWORD@localhost:5432/DATABASE
HIREANDTECH_DATABASE_MIGRATION_URL=postgresql://MIGRATION_USER:PASSWORD@localhost:5432/DATABASE
HIREANDTECH_DATABASE_SSL_MODE=disable
```

The runtime URL represents the application's least-privilege connection. Alembic prefers
the migration URL, which allows deployments to use a separate role with DDL privileges;
if it is absent, migrations fall back to the runtime URL.

URLs must identify a PostgreSQL user, host, and database. Query-string driver options are
rejected because TLS and timeout policy have dedicated settings. Supabase transaction
pooler URLs on port 6543 are also rejected; the implementation requires a direct or
session connection on port 5432.

`verify-full` creates a validating SSL context, optionally using the configured CA file.
Plaintext mode is accepted only for loopback databases in `local` or `test`; staging and
production cannot disable TLS.

## 6. SQLAlchemy Foundation

The main shared types are:

| Symbol | File | Role |
| --- | --- | --- |
| `SCHEMA` | `app/db/base.py` | Canonical `hireandtech` schema name. |
| `NAMING_CONVENTION` | `app/db/base.py` | Stable names for index, unique, check, foreign-key, and primary-key constraints. |
| `Base` | `app/db/base.py` | SQLAlchemy declarative base and Alembic metadata boundary. |
| `IdentityTimestampMixin` | `app/db/base.py` | Shared UUID identity and creation/update timestamps. |
| `Database` | `app/db/session.py` | Application-owned engine, session factory, health probe, and cleanup. |
| `create_database_engine()` | `app/db/session.py` | Runtime or migration engine construction. |
| `parse_database_url()` | `app/db/urls.py` | Safe validation and asyncpg driver normalization. |

Constraint names follow forms such as `pk_<table>`, `uq_<table>_<columns>`, and
`fk_<table>_<columns>_<referred_table>`. Stable names make Alembic output reviewable and
portable across environments.

## 7. Database Session Management

`create_app()` constructs `Database` inside the FastAPI lifespan, stores it on
`application.state.database`, and runs a connection probe before serving traffic. A
failed probe aborts startup. The engine is disposed in a `finally` block on shutdown or
failed startup.

At request time:

```text
FastAPI dependency -> get_database(request) -> Database.sessions()
                   -> one AsyncSession -> endpoint/service/repository
                   -> session closes on dependency exit
```

Transactions remain explicit. The dependency never commits on behalf of application
code, and sessions must not be shared across concurrent tasks.

The runtime pool uses:

- configured `pool_size`, `max_overflow`, and `pool_timeout`;
- `pool_pre_ping=True` to detect stale connections;
- `pool_recycle=1800` seconds;
- connect, command, server-side statement, and idle-in-transaction timeouts;
- UTC and the `hireandtech-api` PostgreSQL application name.

Migration connections instead use `NullPool` and the `hireandtech-migrations`
application name.

## 8. Alembic Migration System

`alembic.ini` contains only repository paths. `migrations/env.py` loads validated
`Settings`, constructs an async migration engine, imports mapped models for metadata,
and runs synchronous Alembic operations through SQLAlchemy's async connection bridge.

Online migrations:

- prefer `HIREANDTECH_DATABASE_MIGRATION_URL`;
- fall back to `HIREANDTECH_DATABASE_URL`;
- create `hireandtech` if it does not exist;
- keep `alembic_version` in that schema;
- compare column types and server defaults during autogeneration;
- inspect only the application schema;
- dispose the unpooled engine on every exit path;
- replace raw migration failures with a credential-safe `CommandError`.

Offline SQL generation uses the PostgreSQL dialect and does not require credentials or a
live database.

Phase 2 introduced `migrations/versions/0001_persistence_foundation.py`:

| Revision property | Value |
| --- | --- |
| Revision | `0001_persistence_foundation` |
| Parent | None |
| Upgrade | Revoke `PUBLIC` access to the application schema and Alembic table. |
| Downgrade | Preserve the schema and its restrictions; Alembic removes the revision stamp. |

Developer commands:

```powershell
uv run alembic current
uv run alembic heads
uv run alembic upgrade head
```

The current repository head also includes Phase 3's `0002_profiles` revision.

## 9. Health / Readiness

The two API v1 health routes have different operational meanings:

| Route | Meaning | Database interaction |
| --- | --- | --- |
| `GET /api/v1/health` | Process liveness: the API can handle a request. | None |
| `GET /api/v1/health/ready` | Service readiness: the API can reach PostgreSQL. | Bounded `SELECT 1` |

The readiness route returns the normal health payload on success. A failed database
probe returns 503 with code `DATABASE_UNAVAILABLE` and a safe public message. Liveness
stays independent so an orchestrator can distinguish an unavailable dependency from a
dead API process.

## 10. Error Handling

The database boundary is designed not to expose credentials, SQL, parameters, driver
diagnostics, or network topology:

- SQLAlchemy engine echo is disabled and bound parameter display is hidden.
- Connection probes catch driver failures, log only a stable `database_unavailable`
  event, and return `False`.
- readiness converts probe failure to a sanitized 503 response;
- `SQLAlchemyError` raised during a request is handled as a generic 500 response;
- error responses use a stable envelope and request ID, never a raw exception;
- online migration failures become a generic Alembic `CommandError`.

Unexpected errors remain available to server-side logging through the general exception
policy, while client responses stay non-sensitive.

## 11. Testing

Phase 2 coverage is split between isolated contract tests and optional real-PostgreSQL
tests:

- `tests/unit/test_database_base.py` checks the schema, naming convention, and mixin.
- `tests/unit/test_database_urls.py` checks URL normalization and rejection rules.
- `tests/unit/test_database_session.py` checks engine/session construction, failure
  behavior, disposal, and app-state dependency resolution.
- `tests/unit/test_config.py` checks environment and deployment safety validation.
- `tests/integration/test_database.py` checks shared mappings and a real connection.
- `tests/integration/test_migrations.py` runs `alembic upgrade head` against PostgreSQL.
- `tests/integration/test_health.py` and `tests/integration/test_errors.py` exercise the
  HTTP health and safe-error contracts.

The real database tests read a disposable database URL from
`HIREANDTECH_TEST_DATABASE_URL` and skip when it is absent. Never point them at a shared
or production database.

```powershell
$env:HIREANDTECH_TEST_DATABASE_URL="postgresql://USER:PASSWORD@localhost:5432/hireandtech_test"
uv run pytest tests/integration/test_database.py -v
uv run pytest tests/integration/test_migrations.py -v
```

## 12. Security Decisions

| Decision | Rationale |
| --- | --- |
| Environment-owned credentials | No connection secret is hard-coded in application or Alembic configuration. |
| Pydantic `SecretStr` URLs | Reduces accidental credential disclosure in normal representations and validation errors. |
| Private schema with revoked `PUBLIC` access | Separates application objects from public and provider-managed namespaces. |
| Separate runtime and migration URLs | Supports least-privilege runtime access and controlled DDL privileges. |
| Verified TLS outside local/test loopback | Prevents plaintext remote database connections. |
| Bounded pool and query timeouts | Limits resource exhaustion and hung dependency calls. |
| Hidden SQL parameters and sanitized errors | Keeps credentials and record values out of public errors and routine database logs. |
| Revision-only DDL | Application startup checks connectivity but never creates domain tables or runs migrations. |

## 13. Files Introduced / Modified

Important Phase 2 files:

```text
alembic.ini
migrations/
├── env.py
├── script.py.mako
└── versions/0001_persistence_foundation.py
app/
├── core/
│   ├── config.py
│   └── errors.py
├── db/
│   ├── base.py
│   ├── session.py
│   └── urls.py
├── api/v1/routes/health.py
└── main.py
tests/
├── unit/test_database_base.py
├── unit/test_database_session.py
├── unit/test_database_urls.py
├── integration/test_database.py
└── integration/test_migrations.py
.env.example
pyproject.toml
```

## 14. Definition of Done

Phase 2 establishes a validated PostgreSQL connection boundary, asynchronous engine and
session lifecycle, private application schema, reusable mapping conventions, reversible
Alembic workflow, readiness probe, sanitized database failures, and real-database test
entry points. Later domain phases can add mapped tables and repositories without
recreating persistence infrastructure.

## 15. What Phase 2 Does NOT Implement

Phase 2 itself did not implement:

- authenticated identity or application authorization (added in Phase 3);
- public signup or automatic profile provisioning;
- IP allowlisting, trusted proxy resolution, rate limiting, or security auditing;
- job ingestion, job search, or scraping;
- Redis queues or background workers;
- AI processing, matching, or notification infrastructure.

These boundaries keep persistence concerns independent from access control and later
business domains.
