# API Documentation

This file consolidates all public API endpoints, authentication, and error handling for the HireAndTech backend.

## Base URL
```
http://<host>:8000/api/v1
```

## Health Checks
- `GET /health` – Liveness probe.
- `GET /health/ready` – Readiness probe.

## Authentication
All protected endpoints require a **Bearer JWT** issued by Supabase. The token is verified against the JWKS endpoint configured in `HIREANDTECH_SUPABASE_URL`.

| Endpoint | Method | Auth | Description |
|---|---|---|---|
| `/auth/me` | GET | ✔️ | Returns the current user profile. |
| `/resumes` | POST/GET/PUT/DELETE | ✔️ | Owner‑scoped resume file management. |
| `/admin/security/ip/current` | GET/POST | ✔️ (admin) | IP allow‑list management. |
| `/jobs` | GET | ✔️ | Query global jobs with filters: `source`, `location`, `company`, `title`. |
| `/jobs/{job_id}` | GET | ✔️ | Retrieve a single job detail. |

## Error Model
All errors follow a structured envelope:
```json
{
  "code": "string",   // machine‑readable identifier
  "message": "string", // safe for client display
  "details": { ... }    // optional additional context
}
```
Typical HTTP status mappings:
- `400` – `BadRequestError`
- `401` – `AuthenticationError`
- `403` – `AuthorizationError`
- `404` – `NotFoundError`
- `429` – `RateLimitError`
- `500` – `InternalServerError`

## Pagination
List endpoints accept `limit` and `offset` query parameters. Defaults: `limit=20`, `offset=0`.

## Rate Limiting
Authentication‑related routes (`/auth/*`, `/admin/*`) are rate‑limited per IP using an in‑process token bucket (see `app/core/rate_limit.py`).

For the full OpenAPI spec, run the service and visit `/docs`.
