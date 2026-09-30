# Deployment

Deploy one image as separate API, scrape-worker, and search-worker processes with
PostgreSQL and Redis. Do not run Alembic from API startup.

Release order:

1. Inject production secrets and explicit Host/CORS/proxy allowlists.
2. Run `uv run alembic heads` and confirm one expected head.
3. Run `uv run alembic upgrade head` as a one-off release job.
4. Start the API and verify `/api/v1/health` then `/api/v1/health/ready`.
5. Start `app.queue.workers.scrape.ScrapeWorkerSettings` where collection is enabled.
6. Start `app.queue.workers.search.SearchWorkerSettings` only with the documented
   understanding that search execution is currently partial.

The container runs as a non-root user. Terminate TLS at trusted infrastructure and set
trusted proxy CIDRs to only direct proxies. Supply database, Redis, Supabase, and proxy
credentials through a secret manager. Never bake `.env` into the image.

Rate limiting is per API process; replicas do not share counters. PostgreSQL and Redis
are required dependencies. Individual external job sources are optional and must not
make API liveness fail. Roll back application processes independently from migrations;
schema downgrades require a specific reviewed recovery plan.
