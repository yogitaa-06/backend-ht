# Phase 3 — Authenticated User Access Control

## 1. Purpose

Phase 3 introduces authenticated identity and application authorization. FastAPI can
now verify a Supabase access token, connect the verified provider subject to a local
HireAndTech profile, enforce account activation, and authorize the profile's local
role.

The central security boundary is:

| System | Question answered | Authority |
| --- | --- | --- |
| Supabase Auth | **Who are you?** | Token signature and verified identity claims |
| HireAndTech PostgreSQL | **What can you do?** | Active local profile and application role |

A provider-issued `role` claim is identity-provider metadata. It is never treated as a
HireAndTech role. Phase 3 also does not implement the separate network/IP-security
controls planned for Phase 4.

## 2. Authentication Architecture

```mermaid
flowchart TD
    EMP[Employee]
    SUPA[Supabase Auth]
    TOKEN[Access token]
    API[FastAPI bearer dependency]
    VERIFY[SupabaseJwtVerifier]
    SUBJECT[Verified Supabase subject UUID]
    PROFILE[(hireandtech.profiles)]
    ACTIVE{Profile exists and is active?}
    ROLE[Local employee or admin role]
    ALLOW[Allow request]
    DENY[Deny request]

    EMP --> SUPA --> TOKEN
    TOKEN -->|Authorization: Bearer JWT| API --> VERIFY --> SUBJECT
    SUBJECT --> PROFILE --> ACTIVE
    ACTIVE -->|No| DENY
    ACTIVE -->|Yes| ROLE --> ALLOW
```

The request flow has two independent decisions:

1. `SupabaseJwtVerifier` establishes identity by verifying the asymmetric JWT and its
   required claims.
2. `get_current_profile()` loads authorization state using the verified subject UUID.
   It permits only an existing, active local profile.

No database session is opened until bearer-token verification succeeds.

## 3. Supabase Configuration

Authentication uses two settings declared in `app/core/config.py` and represented in
`.env.example`:

| Environment variable | Purpose | Default |
| --- | --- | --- |
| `HIREANDTECH_SUPABASE_URL` | Trusted Supabase project HTTPS origin. | Not configured |
| `HIREANDTECH_SUPABASE_JWT_AUDIENCE` | Required access-token audience. | `authenticated` |

Safe example:

```dotenv
HIREANDTECH_SUPABASE_URL=https://YOUR_PROJECT_REF.supabase.co
HIREANDTECH_SUPABASE_JWT_AUDIENCE=authenticated
```

`Settings` accepts only an HTTPS origin with no credentials, path, query, or fragment
and removes a trailing slash. It derives both authentication endpoints from that single
trust boundary:

```text
issuer   = <SUPABASE_URL>/auth/v1
JWKS URL = <SUPABASE_URL>/auth/v1/.well-known/jwks.json
```

The audience setting is typed to the value `authenticated`. The project URL and
audience are not secrets, but publishable/anon keys, service-role keys, access tokens,
database credentials, and private signing material must not be committed. The backend
does not need a Supabase secret key to verify access-token signatures against public
JWKS.

Authentication configuration is optional for local application construction. If a
protected route is called without a configured project URL, authentication fails closed
with a sanitized 503 response.

## 4. JWT Verification

`app/auth/verifier.py` implements local JWT verification in `SupabaseJwtVerifier`.

### Header and algorithm checks

- The verifier reads the unverified header only to select verification policy and a
  public signing key.
- `alg` must be exactly `ES256` or `RS256`.
- `kid` must be a non-empty string.
- The selected JWK's declared algorithm must match the token header.
- `HS256`, `alg=none`, malformed tokens, missing key IDs, and algorithm mismatches are
  rejected before claims are trusted.

### Signature and claim checks

PyJWT verifies the signature using the selected public JWK and validates:

- issuer against `<SUPABASE_URL>/auth/v1`;
- audience against `HIREANDTECH_SUPABASE_JWT_AUDIENCE`;
- expiration (`exp`);
- issued-at (`iat`);
- subject presence (`sub`).

`exp`, `iat`, and `sub` are required. After JWT decoding, `sub` must also be a string
containing a valid UUID. A failure becomes `InvalidAccessTokenError`; public error
handling does not expose the underlying PyJWT exception.

### JWKS retrieval and caching

The verifier requests the derived public JWKS URL with a five-second network timeout and
an `Accept: application/json` header. Blocking URL access runs in a worker thread. The
response is limited to 1 MiB and must be a JSON object containing at least one usable
`ES256` or `RS256` key with a non-empty `kid`.

Parsed keys are indexed by `kid` and cached on the application-owned verifier for ten
minutes. An `asyncio.Lock` serializes cache refreshes:

- an empty or expired cache is refreshed;
- an unknown `kid` triggers one immediate refresh so a rotated signing key can be used;
- another request's completed refresh is reused;
- repeated unknown-key refreshes are limited by a 60-second cooldown;
- a key still unknown after a successful refresh is rejected as an invalid token;
- network, JSON, oversized-response, or unusable-JWKS failures become the empty,
  non-sensitive `JwksUnavailableError`.

At the HTTP boundary, invalid tokens return 401. Unavailable or misconfigured JWKS
infrastructure returns 503, distinguishing bad caller credentials from a temporary
authentication-service failure.

## 5. Identity Claims

`VerifiedClaims` in `app/auth/claims.py` is an immutable, slotted dataclass produced only
after verification succeeds:

| Field | Type | Meaning |
| --- | --- | --- |
| `subject` | `UUID` | Required, verified Supabase user identifier from `sub`. |
| `email` | `str | None` | Optional provider identity metadata. |
| `session_id` | `UUID | str | None` | Optional provider session metadata. The verifier retains it only when represented as a string. |
| `provider_role` | `str | None` | Optional provider `role` metadata. |

`VerifiedClaims` deliberately has no application `role` field. In particular, even a
provider claim such as `service_role` cannot grant HireAndTech admin privileges. Only the
role loaded from `hireandtech.profiles` can authorize application behavior.

## 6. Local Profile Model

`Profile` in `app/domain/profiles.py` maps to `hireandtech.profiles` and inherits shared
identity/timestamp columns from `IdentityTimestampMixin`.

| Column | Type and nullability | Behavior / constraint |
| --- | --- | --- |
| `id` | UUID, not null | PostgreSQL-generated with `gen_random_uuid()`; primary key `pk_profiles`. |
| `auth_user_id` | UUID, not null | Unique provider subject; constraint `uq_profiles_auth_user_id`. |
| `email` | varchar(320), not null | Unique; constraint `uq_profiles_email`. ORM assignment trims and case-folds it. |
| `role` | constrained varchar, not null | `employee` or `admin`; defaults to `employee`; check `ck_profiles_profile_role`. |
| `is_active` | boolean, not null | Defaults to `true`. |
| `created_at` | timezone-aware timestamp, not null | PostgreSQL `now()` default. |
| `updated_at` | timezone-aware timestamp, not null | PostgreSQL `now()` default; SQLAlchemy updates it on ORM changes. |

There is no password column and no foreign key into provider-managed schemas. The model
links systems by the verified Supabase UUID while keeping application authorization
locally owned. Both `auth_user_id` and normalized email are unique.

## 7. Application Roles

`ProfileRole` defines exactly two HireAndTech roles:

| Role | Current meaning |
| --- | --- |
| `employee` | Standard authenticated application user and the default for new profiles. |
| `admin` | Profile accepted by the reusable admin dependency. |

Phase 3 does not introduce a general permissions matrix or additional RBAC hierarchy.
The local profile record is the sole source for these roles.

## 8. Current User Dependency

The authentication dependencies live in `app/auth/dependencies.py`:

1. `bearer_scheme`, an `HTTPBearer` dependency with `auto_error=False`, reads the
   `Authorization` header.
2. `get_supabase_verifier()` resolves the application-owned `SupabaseJwtVerifier`, which
   lets requests share its JWKS cache.
3. `get_verified_claims()` requires a Bearer scheme and asks the verifier to validate the
   token. Invalid credentials become 401; unavailable authentication infrastructure
   becomes 503.
4. Only then does FastAPI resolve `get_session()`.
5. `get_current_profile()` passes `VerifiedClaims.subject` to
   `ProfileRepository.get_by_auth_user_id()`.
6. A missing or inactive profile is rejected with 403.
7. An existing active `Profile` is returned as the authenticated application user.

The focused repository performs only the profile lookup; it does not own authentication
or authorization policy.

## 9. Admin Authorization

`require_admin()` composes on top of `get_current_profile()`. It returns an active
profile only when `profile.role is ProfileRole.ADMIN`; an employee receives 403.

The helper does not inspect `VerifiedClaims.provider_role` or any raw JWT claim. A
Supabase JWT role therefore cannot promote an employee to HireAndTech admin. There is no
admin HTTP endpoint in Phase 3; the dependency is the tested authorization boundary for
future protected admin routes.

## 10. No Public Signup Architecture

Phase 3 intentionally does not provide signup or automatic profile provisioning. A valid
Supabase token proves identity but does not prove HireAndTech enrollment. If
`ProfileRepository` finds no matching `auth_user_id`, `get_current_profile()` returns
403 and creates nothing.

This supports an administrator-controlled account model: administrators establish local
authorization separately, and disabling or omitting the local record denies access
without changing the provider identity.

## 11. Authentication Endpoint

### `GET /api/v1/auth/me`

The endpoint returns the active local profile for the verified bearer token. It requires:

```http
Authorization: Bearer <JWT>
```

Successful response shape:

```json
{
  "id": "11111111-1111-4111-8111-111111111111",
  "auth_user_id": "22222222-2222-4222-8222-222222222222",
  "email": "employee@example.com",
  "role": "employee",
  "is_active": true
}
```

The response is validated by `CurrentProfileResponse` and excludes timestamps, provider
claims, credentials, and tokens.

- Missing or invalid credentials return 401.
- A verified identity without an active authorized profile returns 403.
- Authentication configuration or JWKS infrastructure failure returns 503.

## 12. Error Semantics

| Condition | HTTP status | Public code | Notes |
| --- | ---: | --- | --- |
| Missing bearer token or wrong auth scheme | 401 | `UNAUTHENTICATED` | Includes `WWW-Authenticate: Bearer`. |
| Malformed or expired token | 401 | `UNAUTHENTICATED` | PyJWT details are hidden. |
| Invalid signature | 401 | `UNAUTHENTICATED` | Identity is not trusted. |
| Wrong issuer or audience | 401 | `UNAUTHENTICATED` | Token belongs to the wrong trust boundary. |
| Unsafe algorithm, missing `kid`, or invalid subject UUID | 401 | `UNAUTHENTICATED` | Rejected by verifier policy. |
| Unknown signing key after a successful allowed refresh | 401 | `UNAUTHENTICATED` | Key rotation was checked but the token remains unverifiable. |
| Missing auth configuration or JWKS retrieval/parsing failure | 503 | `AUTHENTICATION_UNAVAILABLE` | Public response omits network and parser details. |
| Missing local profile | 403 | `FORBIDDEN` | No automatic provisioning occurs. |
| Inactive local profile | 403 | `FORBIDDEN` | Provider identity may still be valid. |
| Employee passed to `require_admin()` | 403 | `FORBIDDEN` | Decision uses the local application role. |

All errors use the application's stable response envelope and request ID. The 401 helper
uses the safe message `Authentication required.`; 403 failures use `Access is not
permitted.`; JWKS availability failures use `Authentication is temporarily
unavailable.`

## 13. Database Migration

`migrations/versions/0002_profiles.py` creates the application authorization table:

| Revision property | Value |
| --- | --- |
| Revision | `0002_profiles` |
| `down_revision` | `0001_persistence_foundation` |
| Schema/table | `hireandtech.profiles` |
| Primary key | PostgreSQL-generated UUID `id` |
| Unique constraints | `auth_user_id`, `email` |
| Role enforcement | Non-native SQLAlchemy enum/check accepting only `employee` and `admin` |
| Public access | Revoked from `PUBLIC` after table creation |
| Downgrade | Drops only `hireandtech.profiles` |

The migration does not reference Supabase schemas, store provider credentials, or modify
the Phase 2 schema/migration restrictions.

## 14. Security Properties

| Security property | Implementation |
| --- | --- |
| JWT signature verification | PyJWT verifies against the public key selected from the project's JWKS. |
| Algorithm restriction | Exact allowlist: `ES256` and `RS256`; `HS256` and `none` are rejected. |
| Issuer validation | Required match to the issuer derived from the configured Supabase project origin. |
| Audience validation | Required match to `authenticated`. |
| Expiration and issued-at validation | `exp` and `iat` are required and validated by PyJWT. |
| Subject validation | `sub` is required and must parse as a UUID. |
| Local authorization | Verified subject is mapped to `hireandtech.profiles`. |
| Disabled account enforcement | Missing or inactive profiles receive 403. |
| Provider role isolation | Provider `role` is retained only as metadata; local `Profile.role` controls access. |
| Unknown signing key handling | One rotation-aware refresh; still-unknown keys are rejected, with refresh throttling. |
| JWKS cache | Application-scoped, locked, ten-minute cache with a 60-second unknown-key refresh cooldown. |
| Failure disclosure | Token/JWKS internals are translated to safe 401 or 503 responses. |
| Public signup | Not implemented; valid identities are never auto-provisioned. |

## 15. Testing

Phase 3 coverage includes:

- `tests/unit/test_auth_verifier.py`: ES256 and RS256 success; expiration, issuer,
  audience, subject, UUID, signature, algorithm, malformed-token, JWKS rotation,
  unknown-key, retrieval-failure, caching, and provider-role isolation behavior.
- `tests/unit/test_auth_dependencies.py`: missing/inactive profiles and employee/admin
  authorization.
- `tests/unit/test_profile_model.py`: email normalization, local roles, schema,
  constraints, absence of password storage, and repository lookup.
- `tests/unit/test_config.py`: Supabase URL validation and derived issuer/JWKS endpoints.
- `tests/integration/test_auth.py`: `/api/v1/auth/me` status and response contracts,
  including provider-role isolation.
- `tests/integration/test_profiles.py`: real-PostgreSQL persistence, inactive state,
  unique constraints, repository lookup, and invalid-role rejection.

Focused commands:

```powershell
uv run pytest tests/unit/test_auth_verifier.py -v
uv run pytest tests/unit/test_auth_dependencies.py -v
uv run pytest tests/integration/test_auth.py -v
```

Database-backed profile tests require a disposable PostgreSQL database and skip when
`HIREANDTECH_TEST_DATABASE_URL` is absent:

```powershell
$env:HIREANDTECH_TEST_DATABASE_URL="postgresql://USER:PASSWORD@localhost:5432/hireandtech_test"
uv run pytest tests/integration/test_profiles.py -v
```

Full validation commands:

```powershell
uv run ruff format .
uv run ruff check .
uv run mypy app tests
uv run pytest -v
```

At the time this documentation was requested, the reported DB-enabled validation result
was **102 passed, 0 failed, 0 skipped**. That is a historical result, not a guarantee for
future repository states. A Windows access warning for `.pytest_cache` was also reported;
it did not affect test correctness.

## 16. Files Introduced / Modified

Important Phase 3 files:

```text
app/
├── auth/
│   ├── claims.py
│   ├── dependencies.py
│   └── verifier.py
├── domain/profiles.py
├── repositories/profiles.py
├── schemas/auth.py
├── api/v1/routes/auth.py
├── api/v1/router.py
├── core/config.py
├── core/errors.py
└── main.py
migrations/versions/0002_profiles.py
tests/
├── unit/test_auth_verifier.py
├── unit/test_auth_dependencies.py
├── unit/test_profile_model.py
├── integration/test_auth.py
└── integration/test_profiles.py
.env.example
pyproject.toml
uv.lock
```

## 17. Definition of Done

Phase 3 guarantees that protected requests establish identity through an asymmetrically
signed, issuer/audience-bound Supabase token and establish authorization through an
existing active local profile. Application roles cannot be sourced from provider claims,
disabled or unknown users fail closed, JWKS rotation is handled with bounded caching,
and `/api/v1/auth/me` exposes only the safe local profile contract.

## 18. What Phase 3 Does NOT Implement

Phase 3 does not implement:

- IP allowlisting;
- trusted proxy handling or canonical client-IP resolution;
- a security audit event system;
- rate limiting;
- public signup or automatic local profile provisioning;
- job ingestion or job search;
- scraping;
- Redis queues or workers;
- AI processing or matching;
- notification infrastructure.

## 19. Next Phase

**Phase 4 — Network/IP Security**

Its expected conceptual scope is trusted proxy handling, canonical client-IP resolution,
an IP allowlist, rate limiting, and security auditing. None of that scope is implemented
by this documentation work.
