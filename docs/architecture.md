# Backend architecture

## Deployment model

HireAndTech is a modular monolith deployed as independently scalable processes:

```text
HTTP clients -> FastAPI process -> PostgreSQL
                         |       -> Redis/ARQ
                         |
Redis -> scrape worker -> collector -> ingestion -> PostgreSQL
Redis -> search worker -> search execution lifecycle -> PostgreSQL
```

AI and notification workers are planned, not implemented. Source availability is
not part of API liveness.

## Dependency direction

```text
API router -> service/use case -> domain logic -> repository -> database
ARQ worker -> task -> service/use case -> domain/repository
```

Routers validate HTTP input and map responses. Services own transactions and use-case
state transitions. Matching and normalization have no FastAPI dependency. Repositories
contain SQLAlchemy queries and never accept HTTP request objects. Provider-specific
HTTP and parsing stays beneath `jobs/sources/<provider>`.

## Composition boundaries

- `app.main.create_app()` assembles HTTP middleware and process-owned resources.
- `app.queue.workers.scrape` assembles the collection worker.
- `app.queue.workers.search` assembles the search worker.
- `app.jobs.sources.registry` is the explicit collector registry.
- `app.jobs.ingestion.service` owns source-independent canonical ingestion.

## Data authority

The canonical `companies`, `jobs`, and `job_sources` graph is the target read model.
`global_jobs` remains a legacy compatibility model and is still dual-written by
collection. See [canonical-job-migration.md](canonical-job-migration.md).

## Current gaps

- Async search candidate retrieval and result persistence are not implemented.
- Cross-source duplicate candidates are not automatically merged.
- Rate limiting is process-local.
- No AI, notification, or application-tracking domain is implemented.
- Metrics/traces and a source circuit breaker remain planned.
