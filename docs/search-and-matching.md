# Search and matching

## Generic browsing — IMPLEMENTED

`GET /api/v1/jobs` calls `JobService`, which delegates candidate reduction and
pagination to `CanonicalJobRepository`. Filtering supports query, role, location,
remote, employment type, and source. Recommendations query compatible role families,
apply hard eligibility, calculate deterministic score components, and rank results.

Matching is framework-independent under `app/jobs/matching`:

- `eligibility.py`: active, role, and minimum-experience gates;
- `models.py`: `Candidate`, `MatchableJob`, and `JobMatchScore`;
- `scoring.py`: role, skill, experience, location, and freshness components;
- `ranking.py`: deterministic score ordering and identity tie-breaker.

## User-specific async search — PARTIAL

`POST /api/v1/search` creates a `JobSearch`, commits it, and enqueues its ID. The search
worker delegates to `SearchExecutionService`. Candidate retrieval, filtering, result
persistence, and result endpoints are not yet implemented. Execution therefore marks
the search failed at `candidate_retrieval_not_implemented`; it does not report an empty
search as a successful completion.

Future query work should reduce candidates in PostgreSQL before Python scoring using
indexed filters, FTS/`pg_trgm`, freshness constraints, and keyset pagination.
