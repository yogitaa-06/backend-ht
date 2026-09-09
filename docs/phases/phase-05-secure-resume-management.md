# Backend Phase 5 — Secure Resume Management

Phase 5 adds authenticated, owner-scoped resume management without introducing AI,
Redis, public storage URLs, or background parsing.

## API

All routes require the active local profile resolved by `get_current_profile`:

- `POST /api/v1/resumes` uploads and parses one PDF.
- `GET /api/v1/resumes` lists active owned resumes.
- `GET /api/v1/resumes/{resume_id}/profile` returns safe structured candidate data.
- `POST /api/v1/resumes/{resume_id}/replace` atomically replaces an owned resume.
- `DELETE /api/v1/resumes/{resume_id}` soft-deletes an owned resume and cleans storage.

The authenticated `Profile.id` is the sole source of ownership. Request bodies and
query parameters cannot select an owner. Missing and cross-owner resources use the same
generic `NOT_FOUND` response.

## Private storage and safe responses

The backend generates storage keys as `{owner_profile_id}/{resume_id}.pdf` and accesses
the configured private Supabase Storage bucket with a backend-only secret. Uploads do
not upsert, path components are URL encoded, and deleting a missing object succeeds
idempotently. Storage errors map to stable errors without exposing credentials or
provider diagnostics.

Public resume responses omit the storage bucket, object key, SHA-256, and deletion
metadata. Candidate profile responses omit owner identifiers, extracted text, and raw
parser output.

## Validation and deterministic parsing

The upload boundary reads at most one byte beyond the configured maximum, always closes
the upload stream, and validates the actual byte length, PDF MIME type, `.pdf` suffix,
dangerous double extensions, and `%PDF-` signature. SHA-256 is calculated by the
backend for private persistence.

The parser performs no network or AI calls. It enforces the configured page bound and
caps extracted text at `min(HIREANDTECH_RESUME_MAX_EXTRACTED_CHARACTERS, 200000)` so
parser output can always satisfy the `ParsedResume` schema.

## Persistence and compensation

`hireandtech.resumes` stores private metadata and lifecycle state.
`hireandtech.candidate_profiles` stores structured fields plus private extracted text
and raw parser output. Composite ownership and uniqueness constraints keep candidate
profiles bound to exactly one resume owned by the same profile.

- Upload storage succeeds before database persistence. A database failure rolls back
  and best-effort deletes the new object. A safe parser failure is persisted on upload.
- Replacement uploads and parses first, then inserts the replacement and profile while
  soft-deleting the old row in one transaction. Old storage is removed only afterward.
- Deletion commits the soft-delete before storage removal. Retrying a deleted resume
  retries only idempotent storage cleanup.

The owner-scoped SHA-256 repository lookup remains available, but duplicate uploads are
not rejected because duplicate prevention is not part of the Phase 5 public contract.
