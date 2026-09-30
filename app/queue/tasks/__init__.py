"""Thin ARQ task entrypoints."""

from app.queue.tasks.scrape import run_job_collection
from app.queue.tasks.search import run_job_search

__all__ = ["run_job_collection", "run_job_search"]
