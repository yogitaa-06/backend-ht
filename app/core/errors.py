"""
Safe HTTP error handling.

Responsibilities:
    - Convert expected application failures into stable error contracts.
    - Convert validation failures into client-safe responses.
    - Hide exception details from unexpected failures while retaining server logs.

Security:
    Responses never include stack traces or raw exception messages. Request IDs let
    operators correlate a safe client response with internal structured logs.
"""

import logging
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.middleware import get_request_id

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ApplicationError(Exception):
    """Expected domain-safe failure that can be returned to an API caller."""

    code: str
    message: str
    status_code: int = status.HTTP_400_BAD_REQUEST


def _error_response(
    *,
    request: Request,
    status_code: int,
    code: str,
    message: str,
    details: list[dict[str, Any]] | None = None,
) -> JSONResponse:
    content: dict[str, Any] = {
        "error": {
            "code": code,
            "message": message,
            "request_id": get_request_id(request),
        }
    }
    if details is not None:
        content["details"] = details
    return JSONResponse(
        status_code=status_code,
        content=content,
        headers={"X-Request-ID": get_request_id(request)},
    )


async def application_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Render known application failures without exposing implementation details."""
    if not isinstance(exc, ApplicationError):  # pragma: no cover - framework contract
        raise TypeError("application_error_handler received an unexpected exception")
    return _error_response(
        request=request,
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
    )


async def validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Return a stable message while preserving structured validation locations."""
    if not isinstance(exc, RequestValidationError):  # pragma: no cover - framework contract
        raise TypeError("validation_error_handler received an unexpected exception")
    details: list[dict[str, Any]] = [
        {"location": list(error["loc"]), "message": error["msg"], "type": error["type"]}
        for error in exc.errors()
    ]
    return _error_response(
        request=request,
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        code="REQUEST_VALIDATION_FAILED",
        message="The request did not pass validation.",
        details=details,
    )


async def http_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Normalize framework HTTP failures without echoing arbitrary exception details."""
    if not isinstance(exc, StarletteHTTPException):  # pragma: no cover - framework contract
        raise TypeError("http_error_handler received an unexpected exception")
    code, message = {
        status.HTTP_401_UNAUTHORIZED: ("UNAUTHENTICATED", "Authentication is required."),
        status.HTTP_403_FORBIDDEN: ("FORBIDDEN", "Access is not permitted."),
        status.HTTP_404_NOT_FOUND: ("NOT_FOUND", "The requested resource was not found."),
        status.HTTP_405_METHOD_NOT_ALLOWED: ("METHOD_NOT_ALLOWED", "The method is not allowed."),
    }.get(
        exc.status_code,
        ("HTTP_ERROR", "The request could not be completed."),
    )
    return _error_response(
        request=request,
        status_code=exc.status_code,
        code=code,
        message=message,
    )


async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Log unexpected failures and return a non-sensitive response."""
    logger.exception(
        "unhandled_request_error",
        extra={"operation": f"{request.method} {request.url.path}", "status": "error"},
    )
    return _error_response(
        request=request,
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        code="INTERNAL_SERVER_ERROR",
        message="An unexpected error occurred.",
    )


async def database_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Keep SQL, bound values, and driver diagnostics out of responses and logs."""
    logger.error(
        "database_request_failed",
        extra={"operation": "database_request", "request_id": get_request_id(request)},
    )
    return _error_response(
        request=request,
        status_code=500,
        code="INTERNAL_SERVER_ERROR",
        message="An unexpected error occurred.",
    )


def register_exception_handlers(application: FastAPI) -> None:
    """Register the complete API exception policy in one place."""
    application.add_exception_handler(ApplicationError, application_error_handler)
    application.add_exception_handler(RequestValidationError, validation_error_handler)
    application.add_exception_handler(StarletteHTTPException, http_error_handler)
    application.add_exception_handler(SQLAlchemyError, database_error_handler)
    application.add_exception_handler(Exception, unexpected_error_handler)
