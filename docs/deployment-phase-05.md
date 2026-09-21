# Phase 1–5 Deployment Checklist

This checklist covers only the implemented backend through Phase 5.

## Before deployment

- Supply the database URL, Supabase project URL, and backend-only Supabase secret from a
  secret manager. Staging and production configuration rejects missing values.
- Confirm the resume bucket exists, is private, and does not grant anonymous `select`,
  `insert`, `update`, or `delete` access. The API never returns a public object URL.
- Configure exact Host, browser-origin, direct-proxy, emergency, and IP allowlist values.
  Send a malformed forwarding-chain probe through every trusted proxy and confirm denial.
- Back up the target database and run `uv run alembic upgrade head` as a distinct release
  job. API startup intentionally does not run migrations.
- Run the locked quality workflow, including PostgreSQL tests and the container build.

## Runtime jobs and monitoring

- Schedule `uv run python -m app.resumes.reconcile` at least every 15 minutes. It processes
  one bounded batch and is safe to run concurrently because rows are locked with
  `FOR UPDATE SKIP LOCKED`.
- Alert on repeated `resume_storage_reconciliation_completed` events with a nonzero
  `failed` count, `database_unavailable`, `rate_limit_store_failure`, and unexpected 5xx
  rates. Logs contain stable operation names and counts, not credentials or resume data.
- Monitor database pool saturation, storage request latency, parser timeouts, process CPU,
  memory, and disk. Tune parser concurrency only after load testing representative PDFs.

## Rollback

- Roll back application instances before downgrading a migration.
- Validate the downgrade on a disposable database first. Downgrading from the Phase 5
  hardening revision removes cleanup intents and optimistic-version metadata, so drain
  cleanup rows and verify private storage consistency before any production downgrade.
