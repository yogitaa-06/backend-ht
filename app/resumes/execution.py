"""Bounded execution for synchronous parsing of untrusted resume documents."""

from __future__ import annotations

import asyncio
from typing import Protocol, runtime_checkable

from app.core.errors import ApplicationError
from app.resumes.parser import ResumeParser
from app.schemas.resumes import ParsedResume


class ResumeParserExecutionError(RuntimeError):
    """A parser failed unexpectedly or exceeded its execution deadline."""


@runtime_checkable
class ResumeParseExecutor(Protocol):
    """Asynchronous execution boundary around a synchronous parser."""

    async def parse(self, parser: ResumeParser, content: bytes) -> ParsedResume: ...


class InlineResumeParseExecutor:
    """Deterministic executor used by isolated service tests and injected callers."""

    async def parse(self, parser: ResumeParser, content: bytes) -> ParsedResume:
        try:
            return parser.parse(content)
        except ApplicationError:
            raise
        except Exception as exc:
            raise ResumeParserExecutionError from exc


class BoundedThreadResumeParseExecutor:
    """Keep blocking PDF work off the event loop with shared concurrency limits."""

    def __init__(self, *, max_concurrency: int, timeout_seconds: float) -> None:
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._timeout_seconds = timeout_seconds

    async def parse(self, parser: ResumeParser, content: bytes) -> ParsedResume:
        await self._semaphore.acquire()
        worker = asyncio.create_task(asyncio.to_thread(parser.parse, content))
        release_deferred = False
        try:
            return await asyncio.wait_for(
                asyncio.shield(worker),
                timeout=self._timeout_seconds,
            )
        except ApplicationError:
            raise
        except TimeoutError as exc:
            worker.add_done_callback(self._release_worker_slot)
            release_deferred = True
            raise ResumeParserExecutionError from exc
        except asyncio.CancelledError:
            worker.add_done_callback(self._release_worker_slot)
            release_deferred = True
            raise
        except Exception as exc:
            raise ResumeParserExecutionError from exc
        finally:
            if not release_deferred:
                self._semaphore.release()

    def _release_worker_slot(self, worker: asyncio.Task[ParsedResume]) -> None:
        """Release capacity only after a timed-out thread has actually stopped."""
        if not worker.cancelled():
            _ = worker.exception()
        self._semaphore.release()
