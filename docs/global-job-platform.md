# Phase 1A — Dice canonical global job ingestion

HireAndTech collects a platform-wide job pool on a schedule. Collection is not
triggered by searches, recommendations, resumes, or individual users. This keeps
source load bounded and gives every user a consistent view of observed openings.

## Source status

| Source | Phase 1 status |
| --- | --- |
| Dice | Implemented |
| LinkedIn | Planned for Phase 1B; not implemented here |
| Glassdoor | Planned for Phase 1C; not implemented here |
| BlueDoor | On hold |

The source registry contains only the Dice collector. Existing enum values and
cadence settings for later sources remain compatibility placeholders; the scheduler
does not enqueue a source unless its collector is registered.

## Data flow and process boundaries

```text
ARQ scheduler -> Redis queue -> worker -> Dice collector -> RawSourceJob
                                                        -> normalization
                                                        -> canonical ingestion
                                                        -> PostgreSQL
                                                           ├── companies
                                                           ├── jobs
                                                           └── job_sources
```

FastAPI reads PostgreSQL and never runs scraper loops. The independently deployed
ARQ worker owns Dice HTTP collection, Redis locking, normalization, and persistence.
The Dice adapter contains only provider-specific HTTP and parsing behavior. Everything
after `RawSourceJob` is source-neutral so later adapters can reuse it unchanged.

Dice collection separates lightweight discovery from detail fetching. Search-result
IDs are deduplicated before detail requests, recently scraped rows can skip another
detail request, and a discovery-only observation refreshes `last_seen_at` without
claiming a new `scraped_at`. Pagination, source limits, request delays, timeout
classification, rate-limit retry delays, and bounded ARQ retries remain in place.

## Database responsibilities

- `hireandtech.companies` stores a conservatively resolved employer. Phase 1A reuses
  only an exact normalized name; it does not strip corporate suffixes or fuzzy-match.
- `hireandtech.jobs` stores a real-world opening. It has no provider identity.
- `hireandtech.job_sources` stores the Dice listing and links it to one canonical job.
  `(source, source_job_id)` is unique in PostgreSQL.
- `hireandtech.global_jobs` remains the compatibility read model used by `/jobs`,
  `/jobs/recommended`, and current administration routes.

Migration `0007_canonical_jobs` is additive. It backfills each legacy `global_jobs`
row into one canonical job with the same UUID and creates its source observation.
Backfill deliberately does not merge legacy rows because historical data lacks enough
evidence to prove two requisitions are identical.

New collection items temporarily dual-write. The established `global_jobs` write is
performed first. Canonical ingestion runs in a separate savepoint, so a canonical
failure is logged and reported as a partial collection without discarding the legacy
write. Within canonical ingestion, company, job, and job-source creation share one
savepoint and roll back together.

## Deduplication and canonicalization

Dice identity is `(dice, source_job_id)`. A transaction-scoped PostgreSQL advisory
lock serializes cooperative workers ingesting that identity, while the database unique
constraint remains the final invariant for every writer. Redis target locks reduce
duplicate work but are not treated as the database correctness boundary.

The normalized Dice URL removes fragments and common tracking parameters. It is a
conservative fallback: an exact same-source URL may reuse a canonical job. A
`canonical_hash` built from normalized company, title, location, and posting date is
indexed for future candidate lookup, but is not unique and is never sufficient by
itself to merge openings. Two distinct Dice IDs with identical text remain separate
canonical jobs. This favors a recoverable false negative over a destructive false
positive merge.

Content hashes cover stable mutable listing fields and exclude observation timestamps.
An unchanged listing updates observation timestamps only. Changed content updates the
existing source observation and canonical mutable fields without changing identity or
`first_seen_at`.

## Freshness semantics

- `posted_at`: Dice's best available posting time; it remains null when absent.
- `source_updated_at`: the provider's modification time when Dice supplies one.
- `first_seen_at`: HireAndTech's initial discovery; immutable on re-observation.
- `last_seen_at`: most recent search/detail confirmation of the active listing.
- `scraped_at`: most recent successful detail scrape. Discovery-only refreshes do not
  change it.

`scraped_at` is never substituted for `posted_at`.

## Failure behavior

- Temporary Dice network failures, blocking, and rate limits are classified for
  bounded ARQ retries.
- A malformed detail is logged without inventing data; successfully parsed items are
  still retained.
- Each item uses savepoints, so one invalid item does not invalidate the collection.
- Canonical graph creation is transactional; a failed source insert cannot commit its
  new company or job.
- Ambiguous canonical candidates create separate jobs.

Structured records include source, source job ID, canonical job/company IDs, action,
collection counts, and failure status. Raw payloads and credentials are not logged.

## Local operation (Windows PowerShell)

From `backend-ht`, install dependencies and apply migrations:

```powershell
uv sync
uv run alembic upgrade head
uv run alembic current
```

Start local Redis, then run the worker and API in separate terminals:

```powershell
docker run --name hireandtech-redis --detach --publish 6379:6379 redis:7-alpine
docker exec hireandtech-redis redis-cli ping
$env:HIREANDTECH_REDIS_URL = "redis://localhost:6379/0"
$env:HIREANDTECH_JOB_COLLECTION_ENABLED = "true"
uv run arq app.queue.worker.WorkerSettings
```

```powershell
uv run uvicorn app.main:app --reload
```

Run a controlled direct Dice collection twice to verify insert then re-observation:

```powershell
uv run python scripts/test_dice_ingestion.py
uv run python scripts/test_dice_ingestion.py
```

Or enqueue the controlled collection through the running ARQ worker:

```powershell
uv run python scripts/enqueue_dice_test.py
```

Quality checks:

```powershell
uv run ruff check .
uv run ruff format --check .
uv run mypy app tests
uv run pytest
```

Database integration and migration downgrade coverage require a disposable PostgreSQL
URL in `HIREANDTECH_TEST_DATABASE_URL`. For a configured loopback PostgreSQL server,
the repository can create and remove a randomly named database safely:

```powershell
uv run python scripts/test_postgres_disposable.py
```

## Adding a later source

A future LinkedIn or Glassdoor phase should implement the existing collector contract,
emit `RawSourceJob`, register the adapter, and add tests. It must call the same
normalization and `CanonicalJobIngestionService`; it must not add source-specific
canonical tables or persistence logic. Cross-source reuse will require explicit,
reviewed evidence stronger than the current candidate hash.
