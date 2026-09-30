# Development

Use Python 3.12 and uv. Copy `.env.example` to `.env`, start disposable PostgreSQL and
Redis instances, then run:

```powershell
uv sync --frozen
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

Quality checks:

```powershell
uv lock --check
uv run ruff check .
uv run ruff format --check .
uv run mypy app tests
uv run pytest
uv run pytest --cov=app --cov-report=term-missing
uv run alembic heads
```

Database integration tests require `HIREANDTECH_TEST_DATABASE_URL` and may recreate
objects in that database. Use a disposable database only. Unit collector tests use
fixtures/mock transports and never depend on live provider sites. Live scripts are
manual smoke tests.

Keep routes thin, place use-case orchestration in services, SQLAlchemy operations in
repositories, and pure matching/normalization rules outside FastAPI and ARQ. Add a new
migration for schema changes; do not edit applied history. Use comments for rationale,
especially retry, idempotency, and security decisions.
