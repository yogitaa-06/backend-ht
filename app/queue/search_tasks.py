"""Thin ARQ entrypoint for asynchronous search execution."""

from typing import Any
from uuid import UUID

from app.db.session import Database
from app.search.execution import SearchExecutionService


async def run_job_search(ctx: dict[str, Any], search_id: UUID) -> None:
    """Delegate one search to the application service."""
    database: Database = ctx["database"]
    executor = ctx.get("search_executor")
    if not isinstance(executor, SearchExecutionService):
        executor = SearchExecutionService()
    async with database.sessions() as session:
        await executor.execute(session, search_id)
