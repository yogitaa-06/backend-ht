# API contracts

The version prefix defaults to `/api/v1`. Pydantic schemas under `app/schemas` are the
public contracts; SQLAlchemy models are never returned directly.

Important route groups:

- `/` — public service metadata;
- `/api/v1/health` — process liveness;
- `/api/v1/health/ready` — required dependency readiness;
- `/api/v1/auth/me` — authenticated local profile;
- `/api/v1/jobs` and `/api/v1/jobs/recommended` — browsing and recommendations;
- `/api/v1/search` — asynchronous search creation/progress;
- `/api/v1/resumes` — owner-scoped private resume lifecycle;
- `/api/v1/admin/*` — administrator-only operations.

Expected failures use this envelope:

```json
{
  "error": {
    "code": "SEARCH_NOT_FOUND",
    "message": "The requested search does not exist.",
    "request_id": "correlation-id"
  }
}
```

Services raise `ApplicationError` subclasses. HTTP conversion and request IDs are
owned by `app/core/errors.py`. Unexpected details, SQL, tokens, and resume content are
never placed in responses.
