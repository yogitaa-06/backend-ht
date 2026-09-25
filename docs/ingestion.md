# Job Ingestion Pipeline

This document describes the end‑to‑end ingestion flow for job listings in **HireAndTech**.

## High‑Level Flow
1. **Collect Jobs** – `scripts/collect_jobs.py` parses CLI arguments and builds a `CollectionTarget`.
2. **Coordinator** – `app.jobs.collection.CollectionCoordinator.run` orchestrates:
   * **Discovery** – calls `collector.discover(target)` to get lightweight `DiscoveredSourceJob` candidates (max `target.max_jobs`).
   * **Freshness Check** – uses `LegacyJobPersistence.get_existing_by_external_ids` and `CanonicalJobIngestionService.detail_fetched_by_source_id` to decide which candidates need a fresh detail fetch.
   * **Detail Fetch** – `collector.fetch_details(target, candidates)` returns `RawSourceJob` objects.
3. **Normalization** – each `RawSourceJob` is passed to `app.jobs.normalization.normalize_job` producing a deterministic `NormalizedJob` with a content hash.
4. **Persistence** – `CollectionCoordinator.persist_raw_jobs` upserts the raw job into the legacy `legacy_jobs` table and then calls `CanonicalJobIngestionService.ingest` to write the canonical representation into `global_jobs` and create a source observation.
5. **Touch‑Seen** – recently seen jobs are marked with `touch_seen` to avoid unnecessary re‑scrapes.

## Key Components
| Component | File | Role |
|-----------|------|------|
| **CollectionCoordinator** | `app/jobs/collection.py` | Orchestrates discovery, detail fetching, deduplication, normalization, and persistence. |
| **JobSourceCollector** | `app/jobs/registry.py` + source modules (`sources/*.py`) | Provides `discover` and `fetch_details` for a given source. |
| **CanonicalJobIngestionService** | `app/jobs/ingestion.py` | Handles dual‑write to `global_jobs` and source observation, resolves companies, and logs outcomes. |
| **LegacyJobPersistence** | `app/repositories/jobs.py` (via `GlobalJobRepository`) | Dual‑write path that stores raw source payload for audit/back‑fill. |
| **Normalization** | `app/jobs/normalization.py` | Turns `RawSourceJob` into `NormalizedJob` (hash, role family, normalized fields). |

## Deduplication & Freshness
* **Legacy deduplication** – `CollectionCoordinator._has_complete_core_details` checks core fields; if recent (within 6 h) and details are complete, the job is skipped.
* **Canonical deduplication** – `CanonicalJobIngestionService.ingest` locks the source identity, then either creates a new canonical job or updates an existing one based on `content_hash`.

## Scheduling & Queues
* The collection script can be run manually or via a scheduled ARQ task.
* ARQ workers are defined in `app/queue/` (not shown here) and consume jobs queued by `collect_jobs.py` when `--schedule` is used.

## Error Handling
* Source‑specific errors (`SourceRateLimitedError`, `SourceBlockedError`, `TemporaryCollectionError`) are raised by collectors and propagated to the coordinator, which logs them and continues processing other candidates.
* Persistence errors bubble up to the caller; the surrounding transaction is rolled back to keep canonical and legacy stores consistent.

## Extending the Pipeline
To add a new source:
1. Implement a collector class with `discover` and `fetch_details` returning the appropriate models.
2. Register it in `app.jobs.registry.build_collector_registry`.
3. Ensure the collector yields all required fields (title, company, location, description, etc.) so that `normalize_job` can populate the `NormalizedJob`.

---
*All references are to the current repository state; no code changes are made by this documentation.*
