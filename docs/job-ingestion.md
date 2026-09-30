# Job ingestion

Status: **IMPLEMENTED with conservative deduplication**.

```text
provider collector
  -> RawSourceJob
  -> normalize_job
  -> NormalizedJob
  -> same-source identity lock
  -> conservative dedup decision
  -> company/job/source persistence
  -> freshness update
```

Collectors own source HTTP, pagination, block/rate-limit translation, and provider
payload mapping. `app/jobs/collection.py` coordinates discovery/detail fetching and
legacy/canonical writes. `app/jobs/ingestion` owns all provider-neutral behavior.

Remote values are exactly `remote`, `hybrid`, and `on_site`. Normalizers also produce
stable employment, salary, experience, skill, role-family, URL, and content-hash data.

Same `(source, source_job_id)` is authoritative identity. A normalized URL may reuse a
canonical job only within the same source. Company/title similarity is not sufficient
to merge two openings. `DedupDecision` records method, confidence, evidence, target,
and whether a merge is allowed. Cross-source decisions currently always reject the
merge pending stronger evidence and review policy.

ARQ is at-least-once. Unique identities, source locks, upserts, and freshness updates
make retries safe. A canonical-transition failure is isolated so it cannot discard an
established legacy write during the migration period.
