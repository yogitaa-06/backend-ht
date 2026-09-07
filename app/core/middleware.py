"""
HTTP request context and observability middleware.

Each request receives a safe correlation ID and one structured completion log. A
caller-provided ID is accepted only when it matches a conservative character and
length policy, preventing control-character injection into logs and headers.
"""

import logging
import re
from contextvars import ContextVar, Token
from time import perf_counter
from uuid import uuid4

from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_request_id: ContextVar[str] = ContextVar("request_id", default="unavailable")


def get_request_id(request: Request | None = None) -> str:
    """Return a request's correlation ID, including in outer error handlers."""
    if request is not None:
        return str(getattr(request.state, "request_id", "unavailable"))
    return _request_id.get()


class RequestContextMiddleware:
    """Pure ASGI middleware that correlates responses and structured request logs."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        supplied_id = request.headers.get(REQUEST_ID_HEADER, "")
        request_id = supplied_id if _REQUEST_ID_PATTERN.fullmatch(supplied_id) else str(uuid4())
        token: Token[str] = _request_id.set(request_id)
        request.state.request_id = request_id
        started_at = perf_counter()
        status_code = 500

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = list(message.get("headers", []))
                header_name = REQUEST_ID_HEADER.lower().encode()
                if not any(name.lower() == header_name for name, _ in headers):
                    headers.append((header_name, request_id.encode()))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            duration_ms = round((perf_counter() - started_at) * 1000, 2)
            logger.info(
                "request_completed",
                extra={
                    "operation": f"{request.method} {request.url.path}",
                    "duration_ms": duration_ms,
                    "status": status_code,
                },
            )
            _request_id.reset(token)
