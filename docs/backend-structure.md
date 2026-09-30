# Backend structure

| Concern | Owner |
| --- | --- |
| HTTP routes | `app/api/v1/routes` |
| Public API schemas | `app/schemas` |
| Authentication | `app/auth` |
| Configuration/errors/logging/middleware | `app/core` |
| SQLAlchemy base and sessions | `app/db` |
| SQLAlchemy models | `app/domain` |
| Job browsing/recommendations | `app/jobs/service.py` |
| Job ingestion | `app/jobs/ingestion` |
| Deterministic matching | `app/jobs/matching` |
| Shared source parsing | `app/jobs/parsing` |
| Dice/LinkedIn/Glassdoor/HiringCafe | `app/jobs/sources/<provider>` |
| Collector contract and registry | `app/jobs/sources/base.py`, `registry.py` |
| Async search | `app/search` |
| Queue connection and locks | `app/queue/connection.py`, `locks.py` |
| Scheduler/tasks/workers | `app/queue/scheduler`, `tasks`, `workers` |
| Resume use cases | `app/resumes` |
| Security policy and persistence | `app/security` |

Modules under `app/repositories`, `app/services`, and selected older paths are small
compatibility imports. They allow callers to migrate incrementally; new code should
use the domain-owned paths above.

Provider packages currently expose `collector.py`. Their HTTP and parser code should
only be split further when that produces a real responsibility boundary. Dice remains
large and is explicitly tracked as follow-up work rather than hidden behind empty
`client.py`/`parser.py` placeholders.
