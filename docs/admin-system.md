# HireAndTech administrator system

## Current architecture

The backend uses Supabase JWT verification followed by a local
`hireandtech.profiles` lookup. Administrator access is granted only when the
resolved profile has the database-backed `admin` role. Frontend role flags are
not trusted. Admin routes are under `/api/v1/admin`.

The repository currently contains profile, private resume/candidate-profile,
IP allowlist, security-audit, authentication, and health functionality. It does
not contain a `GlobalJob` model, Auto Search model/scheduler, AI usage ledger,
Redis/ARQ worker integration, scraper registry, or collection telemetry. The
admin API reports those areas as unavailable or returns HTTP 501; it does not
fabricate metrics or create parallel tables.

## Implemented endpoints

`GET /api/v1/admin/dashboard` returns SQL aggregates for profiles, resumes,
parsed candidate profiles, and security audit events. Unsupported job,
Auto Search, and AI metrics are explicitly marked unavailable.

`GET /api/v1/admin/users?page=1&page_size=50&search=...` and
`GET /api/v1/admin/users/{user_id}` provide paginated profile administration,
resume counts, active resume, and candidate-profile availability. User creation
is intentionally not exposed because this repository has no Supabase Admin API
client; no local password or second authentication system is introduced.

`GET /api/v1/admin/resumes` and `GET /api/v1/admin/resumes/{resume_id}` expose
safe metadata and parsed candidate fields. Storage credentials, raw parser
output, and private storage URLs are not returned.

Existing security administration remains available:

- `GET /api/v1/admin/security/ip/current`
- `GET|POST /api/v1/admin/security/ip-rules`
- `PATCH|DELETE /api/v1/admin/security/ip-rules/{rule_id}`
- `GET /api/v1/admin/security/audit-events`

These retain CIDR normalization, lockout safeguards, cache invalidation, and
secret-free audit responses.

`GET /api/v1/admin/analytics/overview`, `GET /api/v1/admin/system/status`,
and `GET /api/v1/admin/settings` expose supported aggregates, a database/API
probe, and safe deployment metadata. Redis, workers, collection, and scraper
status are reported unavailable because they are not configured here.

The following capability-discovery routes return HTTP 501 after authorization
until their underlying architecture exists:

- `GET /api/v1/admin/jobs`
- `GET /api/v1/admin/jobs/{job_id}`
- `GET /api/v1/admin/jobs/stats`
- `GET /api/v1/admin/auto-searches`
- `GET /api/v1/admin/ai-costs`

## Pagination and authorization

Profile and resume list APIs use `page`, `page_size`, `total`, and `pages`, with
a maximum page size of 100. The shared `require_admin` dependency ensures
missing/invalid credentials result in 401 and authenticated non-admin profiles
result in 403.

## Capability status

| Area | Status |
|---|---|
| Admin authorization | Implemented and reused |
| IP allowlist and security audit | Implemented before this change |
| Users | Implemented read-only administration |
| Resumes and candidate profiles | Implemented read-only administration |
| Dashboard | Partially implemented using current models |
| Analytics | Partially implemented; supported aggregates are limited |
| System status | Partially implemented; database/API probes only |
| Global jobs | Not implemented in current backend |
| Auto Search | Not implemented in current backend |
| AI costs | Not implemented in current backend |
| Redis/ARQ/scraper monitoring | Not implemented in current backend |
| Admin user creation | Not implemented; requires Supabase Admin API integration |

