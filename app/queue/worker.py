"""Compatibility entrypoint for the scrape worker.

The supported legacy command remains ``arq app.queue.worker.WorkerSettings``.
New deployments may use ``arq app.queue.workers.scrape.ScrapeWorkerSettings``.
"""

from app.queue.workers.scrape import (
    ScrapeWorkerSettings,
    shutdown,
    startup,
)

WorkerSettings = ScrapeWorkerSettings

__all__ = ["WorkerSettings", "shutdown", "startup"]
