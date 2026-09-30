# Canonical job migration plan

## Current state

- **Authoritative long-term model:** `companies` + `jobs` + `job_sources`.
- **Legacy compatibility model:** `global_jobs`.
- **Writes:** collection writes `global_jobs`, then canonical tables in an isolated
  savepoint. Canonical failure is logged and counted without losing the legacy write.
- **Reads:** public job browsing and recommendations use canonical tables; some admin
  and operational compatibility paths still inspect `global_jobs`.

No table is dropped by this structural refactor.

## Safe migration sequence

1. Inventory every `GlobalJob` and `global_jobs` read/write with repository-level tests.
2. Backfill legacy rows into canonical company/job/source observations idempotently.
3. Compare counts and sampled field parity by source and collection window.
4. Run canonical reads in shadow mode and monitor missing/stale observations.
5. Migrate remaining admin/operator reads to canonical repositories.
6. Stop legacy writes behind an explicit release flag after a rollback window.
7. Confirm no production code, scripts, or dashboards depend on `global_jobs`.
8. Create a new reviewed Alembic revision to drop the table in a later release.

## Removal gates

Legacy removal requires a complete backfill, zero known callers, canonical write
reliability at the agreed operational threshold, tested rollback/restore procedures,
and an explicit data-retention decision. Cross-source fuzzy merging is not a gate and
must not be introduced as part of the backfill.
