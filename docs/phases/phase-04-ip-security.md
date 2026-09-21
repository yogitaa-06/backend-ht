# Backend Phase 4 — IP Security

Phase 4 adds IP policy as defense in depth. It does not identify users and does not
replace Supabase verification or local profile authorization.

## Request pipeline

```text
socket peer / trusted X-Forwarded-For resolution
  -> persistent CIDR allowlist
  -> bounded route-specific rate limit
  -> Supabase authentication
  -> local profile and admin authorization
  -> endpoint
```

`OPTIONS`, `/api/v1/health`, and `/api/v1/health/ready` are the only enforcement
exclusions. They preserve CORS negotiation, liveness, and readiness. Rate limiting is
applied to authentication and administrator-security routes; Phase 5 also applies the
same infrastructure to resume upload and replacement writes.

## Trusted proxy assumptions

The direct socket peer is authoritative by default. Forwarding values are used only if
the immediate peer belongs to `HIREANDTECH_TRUSTED_PROXY_CIDRS`. A completely parseable
`X-Forwarded-For` chain is processed from right to left, stopping at the first untrusted
hop. This prevents a spoofed leftmost value from overriding the hop appended by a
correct proxy. A missing or malformed chain from a trusted proxy resolves to no client
IP and therefore fails closed when allowlisting is enabled. It never falls back to the
trusted proxy address. `X-Real-IP` is not trusted. IPv4-mapped IPv6 values are normalized
to IPv4.

Deployments must list only proxies that connect directly to Uvicorn and correctly
append or overwrite forwarding information.

## Persistent policy and recovery

`hireandtech.ip_access_rules` stores normalized PostgreSQL `CIDR` values, labels,
descriptions, enabled state, and the creating administrator. Duplicate networks are
unique. `/32`, `/128`, IPv4, and IPv6 rules are supported.

`HIREANDTECH_IP_ALLOWLIST_ENABLED=false` is explicit and logged. When enabled, a request
must match an enabled rule. Database failures deny by default; fail-open is restricted
to local/test. `HIREANDTECH_IP_EMERGENCY_BYPASS_CIDRS` is a configuration-only recovery
control. It cannot be changed by the API and its use is audited when the database is
available. There is no unauthenticated recovery endpoint.

The API prevents disabling or deleting the final enabled rule matching the current
administrator unless the request comes from an emergency CIDR. Operators should test
recovery before enabling enforcement.

## Audit safety

`hireandtech.security_audit_events` records denials, rule mutations, and emergency
bypass use. Mutation events share the rule transaction. Denial/bypass event failures do
not expose details or change the access decision. User agents have control characters
removed and are limited to 512 characters; metadata has a small key bound and is omitted
from API responses. Tokens, authorization headers, cookies, passwords, credentials, and
stack traces are never stored.

## Administrator API

All endpoints require an active local admin profile:

- `GET /api/v1/admin/security/ip/current`
- `GET|POST /api/v1/admin/security/ip-rules`
- `PATCH|DELETE /api/v1/admin/security/ip-rules/{rule_id}`
- `GET /api/v1/admin/security/audit-events`

Lists have stable ordering and bounded `offset` and `limit` pagination.

## Rate limiting

The limiter uses a capacity-bounded fixed-window in-process store keyed by route group
and trusted resolved IP. Authentication and admin-security limits are independent.
Store failures deny by default and may fail open only in local/test. The store is
injectable for a future shared backend; limits are per process because the repository
did not previously use Redis.

Limits are configured with `HIREANDTECH_RATE_LIMIT_ENABLED`,
`HIREANDTECH_RATE_LIMIT_WINDOW_SECONDS`, `HIREANDTECH_RATE_LIMIT_AUTH_REQUESTS`,
`HIREANDTECH_RATE_LIMIT_ADMIN_SECURITY_REQUESTS`, and
`HIREANDTECH_RATE_LIMIT_MAX_KEYS`. Phase 5 adds
`HIREANDTECH_RATE_LIMIT_RESUME_WRITE_REQUESTS`. `HIREANDTECH_RATE_LIMIT_FAIL_CLOSED` defaults to
`true` and cannot be disabled in staging or production.
