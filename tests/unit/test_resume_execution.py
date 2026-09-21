"""Bounded parser execution keeps untrusted PDF work isolated from the event loop."""

import asyncio
from threading import Event

import pytest

from app.core.errors import ApplicationError
from app.resumes.execution import (
    BoundedThreadResumeParseExecutor,
    InlineResumeParseExecutor,
    ResumeParserExecutionError,
)
from app.schemas.resumes import ParsedResume

pytestmark = pytest.mark.anyio


class SuccessfulParser:
    def parse(self, content: bytes) -> ParsedResume:
        return ParsedResume(full_name=content.decode(), extracted_text="resume")


class FailingParser:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def parse(self, content: bytes) -> ParsedResume:
        del content
        raise self.error


class BlockingParser:
    def __init__(self, started: Event, release: Event) -> None:
        self.started = started
        self.release = release

    def parse(self, content: bytes) -> ParsedResume:
        self.started.set()
        self.release.wait(timeout=2)
        return ParsedResume(full_name=content.decode(), extracted_text="resume")


async def test_inline_executor_preserves_safe_parser_errors_and_wraps_unknown_errors() -> None:
    executor = InlineResumeParseExecutor()
    safe_error = ApplicationError("INVALID", "Invalid PDF", 422)

    with pytest.raises(ApplicationError) as raised:
        await executor.parse(FailingParser(safe_error), b"pdf")
    assert raised.value is safe_error

    with pytest.raises(ResumeParserExecutionError):
        await executor.parse(FailingParser(RuntimeError("private parser detail")), b"pdf")


async def test_thread_executor_returns_successful_result() -> None:
    result = await BoundedThreadResumeParseExecutor(
        max_concurrency=1,
        timeout_seconds=1,
    ).parse(SuccessfulParser(), b"Candidate")

    assert result.full_name == "Candidate"


async def test_timed_out_worker_retains_capacity_until_its_thread_finishes() -> None:
    first_started = Event()
    first_release = Event()
    second_started = Event()
    second_release = Event()
    executor = BoundedThreadResumeParseExecutor(max_concurrency=1, timeout_seconds=0.1)

    with pytest.raises(ResumeParserExecutionError):
        await executor.parse(BlockingParser(first_started, first_release), b"first")
    assert first_started.is_set()

    second = asyncio.create_task(
        executor.parse(BlockingParser(second_started, second_release), b"second")
    )
    await asyncio.sleep(0.02)
    assert not second_started.is_set()

    first_release.set()
    for _ in range(20):
        if second_started.is_set():
            break
        await asyncio.sleep(0.01)
    assert second_started.is_set()
    second_release.set()
    assert (await second).full_name == "second"
