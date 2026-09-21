# Global job platform

`backend-ht` is the source of truth. The missing `backend` reference directory
was not available in this workspace, so source-specific adapters remain isolated
behind the collection contract rather than copied from an unavailable tree.

```text
SOURCES
   ↓
SCHEDULED COLLECTION
   ↓
REDIS / ARQ (worker deployment boundary)
   ↓
NORMALIZE
   ↓
DEDUPLICATE (source + external_job_id)
   ↓
GLOBAL JOB DB
   ↓
CANDIDATE PROFILE
   ↓
ELIGIBILITY
   ↓
RANKING
   ↓
RECOMMENDATIONS
```

`global_jobs` is canonical and belongs to the private `hireandtech` schema.
Collection adapters return `RawSourceJob`; `normalize_job` produces the only
accepted persistence shape. Upsert preserves source identity and updates
`last_seen_at`, `scraped_at`, and content on repeat observations.

Role matching is explicit. DevOps, SRE, platform, and cloud are one compatible
cluster; generic words such as “engineer” do not create compatibility. Required
experience is extracted only from conservative phrases such as `2+ years`,
`3-5 years`, `minimum 3 years`, and `at least 4 years`. Unknown experience does
not reject a candidate.

`GET /api/v1/jobs` searches PostgreSQL only. `GET /api/v1/jobs/recommended`
loads the existing candidate profile, applies active/role/experience eligibility,
then ranks skills, experience, location, and freshness. No user request invokes
a scraper.

The coordinator provides per-source non-overlap within a worker process and
structured run logging. Production deployment should replace that lock with a
Redis distributed lock and enqueue the coordinator through ARQ; Redis/ARQ are
optional deployment infrastructure and are intentionally not imported by the
API process.

