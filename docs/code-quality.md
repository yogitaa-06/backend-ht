# Code Quality

HireAndTech enforces rigorous static quality and automated test checks in CI. The configured coverage target is 90.0%.

## Continuous Integration Behavior

The `backend-quality.yml` workflow enforces quality gates via GitHub Actions:

1. **Dependency check**: Validates `uv.lock`.
2. **Static Analysis**: Runs `ruff check` and `ruff format --check`.
3. **Type Checking**: Strict `mypy` against all `app` and `tests` directories.
4. **Integration Testing**:
   - A disposable PostgreSQL 18 service container is launched and health-checked.
   - `alembic upgrade head` applies all migrations strictly to `hireandtech_test` database.
   - `pytest` executes unit and integration tests (with `HIREANDTECH_TEST_DATABASE_URL` mapped to the CI container).
   - A CI guard ensures integration DB tests are not quietly skipped.
5. **Coverage Gate**: Validates exactly `pytest --cov=app` >= 90.0%.

## Local Integration Tests

For developers without PostgreSQL installed locally, database tests are safely skipped if `HIREANDTECH_TEST_DATABASE_URL` is omitted. However, local validation should eventually match CI via a local database.

To test locally:
```powershell
$env:HIREANDTECH_TEST_DATABASE_URL = "postgresql://postgres:admin1234@localhost:5432/hireandtech_test"
uv run alembic upgrade head
uv run pytest --cov=app --cov-report=term-missing
```

## Redis Requirements

Integration tests currently decouple job collection functionality using `FakeRedis` or `AsyncMock` to isolate logic, meaning a real Redis container is NOT required for local testing or CI. The backend leverages ARQ exclusively for queue behavior, which is validated sufficiently at the boundary layer without an external mock cluster.
