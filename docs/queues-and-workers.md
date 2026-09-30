# Queues and workers

Redis/ARQ is infrastructure; use-case behavior remains in services.

| Module | Responsibility |
| --- | --- |
| `queue/connection.py` | Validated Redis-to-ARQ configuration and pool creation |
| `queue/locks.py` | Ownership-safe distributed collection leases |
| `queue/scheduler/collection.py` | Due calculation, target rotation, enqueue policy |
| `queue/tasks/scrape.py` | Thin collection task, retry translation, lock release |
| `queue/tasks/search.py` | Thin search execution delegation |
| `queue/workers/scrape.py` | Scrape process composition and ARQ settings |
| `queue/workers/search.py` | Search process composition and ARQ settings |

Commands:

```powershell
uv run arq app.queue.workers.scrape.ScrapeWorkerSettings
uv run arq app.queue.workers.search.SearchWorkerSettings
```

The scrape scheduler uses Redis due keys and deterministic ARQ job IDs. Collection
locks are released in success and failure paths. Transient collection errors become
bounded ARQ retries; permanent failures do not retry blindly. Logs include source,
task/search identity where available, counts, attempts, and duration fields.

AI and notification queues/workers do not exist. No circuit breaker is implemented.
