"""Early ASGI request-size enforcement for expensive multipart resume writes."""

from __future__ import annotations

from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import Settings
from app.core.errors import ApplicationError, application_error_handler

_MULTIPART_OVERHEAD_BYTES = 64 * 1024


class _RequestBodyTooLarge(Exception):
    """Internal control flow raised before a request reaches an endpoint."""


class ResumeRequestBodyLimitMiddleware:
    """Reject oversized resume multipart bodies while they are being received."""

    def __init__(self, app: ASGIApp, *, settings: Settings) -> None:
        self.app = app
        self._prefix = f"{settings.api_v1_prefix}/resumes"
        self._maximum = settings.resume_max_size_bytes + _MULTIPART_OVERHEAD_BYTES

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not self._is_limited(scope):
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        declared_length = request.headers.get("content-length")
        if declared_length is not None:
            try:
                if int(declared_length) > self._maximum:
                    await self._reject(request, scope, receive, send)
                    return
            except ValueError:
                pass

        received = 0
        response_started = False

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self._maximum:
                    raise _RequestBodyTooLarge
            return message

        async def tracked_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracked_send)
        except _RequestBodyTooLarge:
            if response_started:  # pragma: no cover - multipart is read before response start
                raise
            await self._reject(request, scope, receive, send)

    def _is_limited(self, scope: Scope) -> bool:
        if scope.get("method") != "POST":
            return False
        path = str(scope.get("path", ""))
        return path == self._prefix or (
            path.startswith(f"{self._prefix}/") and path.endswith("/replace")
        )

    @staticmethod
    async def _reject(
        request: Request,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        error = ApplicationError(
            "RESUME_FILE_TOO_LARGE",
            "The uploaded resume exceeds the allowed size.",
            413,
        )
        response = await application_error_handler(request, error)
        await response(scope, receive, send)
