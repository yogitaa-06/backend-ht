# Global job platform

`backend-ht` is the authoritative backend. Collection is platform-wide and is
strictly separate from resume upload, job search, and recommendation requests.

```text
                    Redis
                      │
Scheduler ────────────┤
                      ↓
                  ARQ Worker
                      ↓
               Source Registry
                      ↓
               Collector Interface
                      ↓
            Collection Coordinator
                      ↓
                  Normalize
                      ↓
               GlobalJobRepository
                      ↓
                  PostgreSQL
```

## Process separation

FastAPI serves HTTP and reads PostgreSQL. It neither starts a worker nor runs a
scraper loop. `GET /api/v1/jobs`, `GET /api/v1/jobs/recommended`, and all resume
routes never enqueue collection work.

ARQ runs in an independent process using `app.queue.worker.WorkerSettings`. The
worker owns its PostgreSQL pool and uses ARQ's Redis pool. Worker startup fails
clearly if Redis or PostgreSQL is unavailable; this does not make the FastAPI
process depend on Redis.

## Configuration

All variables use the `HIREANDTECH_` prefix:

- `REDIS_URL`: secret Redis or Redis TLS DSN.
- `JOB_COLLECTION_ENABLED`: enables scheduler enqueueing; it does not affect HTTP.
- `DICE_COLLECTION_INTERVAL_MINUTES`, `LINKEDIN_COLLECTION_INTERVAL_MINUTES`,
  and `GLASSDOOR_COLLECTION_INTERVAL_MINUTES`: source-specific cadence.
- `JOB_COLLECTION_MAX_JOBS_PER_TARGET`: deployment-wide result ceiling.
- `JOB_COLLECTION_LOCK_TTL_SECONDS`: distributed-lock crash safety.
- `JOB_COLLECTION_TASK_TIMEOUT_SECONDS` and `JOB_COLLECTION_MAX_TRIES`: bounded
  execution and retry limits.
- `JOB_COLLECTION_TARGETS`: optional JSON list of platform targets.

The built-in targets cover software, backend, frontend, full stack, DevOps,
SRE, platform, cloud, data engineering, data science, machine learning, QA
automation, and security. Exact duplicate searches are collapsed before
enqueueing. Targets contain only source, query, location, enabled state, and a
result limit—never user, resume, or candidate identifiers.

## Scheduler and queue behavior

An ARQ cron function checks due work once per minute. Source-specific Redis due
keys atomically prevent multiple scheduler processes from enqueueing the same
source window. ARQ job IDs provide another enqueue-time uniqueness boundary.
One target enqueue failure is logged and does not stop other targets.

Only registered collectors are enqueued. The registry is intentionally empty in
Checkpoint 2: no collector pretends to scrape. Checkpoint 3 adds a real Dice
collector and registers it in `build_collector_registry()` without changing the
scheduler or task orchestration.

## Collection task and result

`run_job_collection` validates the target, resolves the collector, acquires an
expiring Redis lease, and delegates collection, normalization, and persistence
to `CollectionCoordinator`. The task does not duplicate normalization or upsert
logic. Results and logs contain:

- source, query, and location;
- start, finish, and duration;
- discovered, normalized, inserted, updated, skipped, and failed counts;
- lock acquisition and status.

Statuses are `success`, `partial`, `failed`, `skipped_locked`, or
`source_unavailable`. Unchanged source jobs refresh observation timestamps and
count as skipped, not inserted. Item failures use nested database transactions
so one malformed job does not invalidate the entire collection transaction.

## Distributed locking and retries

The Redis lock key is based on a stable source/query/location identity. Locks
use `SET NX PX`, a random owner token, and a Lua compare-and-delete release.
Expiration prevents permanent deadlock after worker crashes, while the token
prevents an expired owner from releasing a newer worker's lock.

Collectors must classify temporary network, rate-limit, and source-block errors
as `TemporaryCollectionError` variants. ARQ retries those with bounded backoff
and a configured maximum attempt count. Permanent configuration errors and
ordinary no-result responses are not retried indefinitely.

## Health status

`GET /api/v1/admin/system/status` performs a bounded Redis ping only when Redis
is configured. Redis can be `healthy`, `unavailable`, or `unknown`. Worker health
is `healthy` only when ARQ's actual heartbeat key exists; installation alone is
never reported as health. Collection reports `disabled`, `healthy`, or `unknown`
based on configuration and worker evidence.

## Local operation (Windows PowerShell)

Start Redis with Docker:

```powershell
docker run --name hireandtech-redis --detach --publish 6379:6379 redis:7-alpine
docker exec hireandtech-redis redis-cli ping
```

Configure the current PowerShell session:

```powershell
$env:HIREANDTECH_REDIS_URL = "redis://localhost:6379/0"
$env:HIREANDTECH_JOB_COLLECTION_ENABLED = "true"
```

Run FastAPI and the worker in separate terminals:

```powershell
uv run uvicorn app.main:app --reload
uv run arq app.queue.worker.WorkerSettings
```

Check the real worker heartbeat and run validation:

```powershell
uv run arq app.queue.worker.WorkerSettings --check
uv run ruff check .
uv run mypy app
uv run pytest -q
```

