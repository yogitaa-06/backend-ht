# Database Schema Documentation

This document describes the **PostgreSQL** schema used by the **HireAndTech** backend. All tables live in the private schema `hireandtech` (see `app/db/base.py`).

## Core Tables
| Table | Primary Key | Purpose |
|-------|-------------|---------|
| `global_jobs` | `id` (UUID) | Legacy normalized job representation. Stores a copy of the raw source payload (`content_hash`) and is used for backward‑compatible reads. |
| `jobs` (canonical) | `id` (UUID) | The authoritative job record independent of any source. Contains normalized fields, experience ranges, salary, remote type, etc. |
| `companies` | `id` (UUID) | Normalized employer entity. De‑duplicates companies across sources via `normalized_name`. |
| `job_sources` | `id` (UUID) | Observation linking a source listing to a canonical job. Stores source‑specific URLs, timestamps, raw JSON payload, and a content hash for deduplication. |

## Important Columns
* **Source identification** – `source` (enum `JobSource`) and `source_job_id` uniquely identify a listing.
* **Timestamps** – All tables inherit `created_at`, `updated_at` from `IdentityTimestampMixin`. Additional timestamps (`first_seen_at`, `last_seen_at`, `scraped_at`, `posted_at`, `source_updated_at`) track freshness.
* **Content hash** – SHA‑256 hash of the normalized payload (`content_hash` on legacy jobs, `canonical_hash` on canonical jobs, `content_hash` on source observations) enables deterministic deduplication.

## Indexes & Constraints
* Unique constraint on (`source`, `external_job_id`) in `global_jobs` and (`source`, `source_job_id`) in `job_sources` ensures one row per provider listing.
* Many functional indexes support the API search layer (e.g., `ix_jobs_active_posted`, `ix_jobs_role_family_active`).
* Check constraints enforce non‑negative experience values and ordering (`experience_max_years >= experience_min_years`).

## Relationships
* `CanonicalJob` → optional `Company` (`company_id`).
* `JobSourceObservation` → required `CanonicalJob` (`job_id`).
* `Company` → collection of `CanonicalJob`s.

## Migration Strategy
The repository uses **Alembic** (not shown here) for schema evolution. New columns are added with careful defaults to preserve existing data. Legacy tables (`global_jobs`) remain read‑only after the migration to the canonical model.

---
*All references reflect the current repository state; no code changes are made by this documentation.*
