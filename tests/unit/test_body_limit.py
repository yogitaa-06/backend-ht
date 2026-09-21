"""Early request-body limits protect resume multipart parsing."""

from collections.abc import Awaitable, Callable

import pytest
from starlette.types import Message, Scope

from app.core.body_limit import ResumeRequestBodyLimitMiddleware
from app.core.config import Settings

pytestmark = pytest.mark.anyio


def _scope(*, path: str, method: str = "POST", content_length: int | None = None) -> Scope:
    headers = [] if content_length is None else [(b"content-length", str(content_length).encode())]
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": headers,
        "client": ("192.0.2.1", 1234),
        "server": ("testserver", 80),
        "state": {},
    }


async def _invoke(
    middleware: ResumeRequestBodyLimitMiddleware,
    scope: Scope,
    messages: list[Message],
) -> list[Message]:
    sent: list[Message] = []

    async def receive() -> Message:
        return messages.pop(0)

    async def send(message: Message) -> None:
        sent.append(message)

    await middleware(scope, receive, send)
    return sent


def _middleware() -> tuple[ResumeRequestBodyLimitMiddleware, list[int]]:
    received_sizes: list[int] = []

    async def app(
        scope: Scope,
        receive: Callable[[], Awaitable[Message]],
        send: Callable[[Message], Awaitable[None]],
    ) -> None:
        del scope
        total = 0
        more_body = True
        while more_body:
            message = await receive()
            total += len(message.get("body", b""))
            more_body = bool(message.get("more_body", False))
        received_sizes.append(total)
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    settings = Settings(_env_file=None, environment="test", resume_max_size_bytes=1024)
    return ResumeRequestBodyLimitMiddleware(app, settings=settings), received_sizes


async def test_declared_oversized_resume_is_rejected_before_body_is_read() -> None:
    middleware, received_sizes = _middleware()
    responses = await _invoke(
        middleware,
        _scope(path="/api/v1/resumes", content_length=70_000),
        [{"type": "http.request", "body": b"not-read", "more_body": False}],
    )

    assert responses[0]["status"] == 413
    assert b"RESUME_FILE_TOO_LARGE" in responses[1]["body"]
    assert received_sizes == []


async def test_chunked_oversized_replacement_is_rejected_during_receive() -> None:
    middleware, received_sizes = _middleware()
    responses = await _invoke(
        middleware,
        _scope(path="/api/v1/resumes/00000000-0000-0000-0000-000000000000/replace"),
        [
            {"type": "http.request", "body": b"a" * 40_000, "more_body": True},
            {"type": "http.request", "body": b"b" * 30_000, "more_body": False},
        ],
    )

    assert responses[0]["status"] == 413
    assert b"RESUME_FILE_TOO_LARGE" in responses[1]["body"]
    assert received_sizes == []


@pytest.mark.parametrize(
    ("path", "method"),
    [("/api/v1/resumes", "GET"), ("/api/v1/profiles", "POST")],
)
async def test_unrelated_requests_are_not_limited(path: str, method: str) -> None:
    middleware, received_sizes = _middleware()
    body = b"x" * 70_000
    responses = await _invoke(
        middleware,
        _scope(path=path, method=method, content_length=len(body)),
        [{"type": "http.request", "body": body, "more_body": False}],
    )

    assert responses[0]["status"] == 204
    assert received_sizes == [len(body)]
