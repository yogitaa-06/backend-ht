# Database design

All application objects live in the `hireandtech` PostgreSQL schema. SQLAlchemy models
are registered in `app/domain`; Alembic revisions are the only schema mutation path.

## Main aggregates

- `profiles`: local authorization identity corresponding to a Supabase subject.
- `resumes`, `candidate_profiles`, `resume_storage_cleanup`: private resume lifecycle.
- `companies`, `jobs`, `job_sources`: canonical job catalog and provider observations.
- `global_jobs`: legacy compatibility data during canonical migration.
- `job_searches`, `job_search_results`: asynchronous search lifecycle and future results.
- `ip_access_rules`, `security_audit_events`: network policy and audit history.

Collection writes a legacy row and attempts a canonical write in a nested transaction.
Canonical company, job, source observation, and freshness changes share the caller's
transaction. Same-source identity is protected by unique constraints and advisory
locking. Search result uniqueness is enforced by `(search_id, job_id)`.

Existing revisions are immutable. Add schema changes as new files, verify a single
head with `uv run alembic heads`, and test upgrades against a disposable PostgreSQL
database before deployment.
