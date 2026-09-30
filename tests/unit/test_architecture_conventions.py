"""Regression tests for shared domain and error conventions."""

from app.core.errors import (
    AuthenticationError,
    AuthorizationError,
    ConflictError,
    DomainValidationError,
    ExternalServiceError,
    InfrastructureError,
    NotFoundError,
)
from app.jobs.types import RemoteType, SearchStatus


def test_canonical_remote_values_are_stable() -> None:
    assert {value.value for value in RemoteType} == {"remote", "hybrid", "on_site"}


def test_search_lifecycle_values_are_stable() -> None:
    assert {value.value for value in SearchStatus} == {
        "queued",
        "processing",
        "completed",
        "failed",
    }


def test_application_error_categories_map_to_expected_statuses() -> None:
    assert DomainValidationError("INVALID", "invalid").status_code == 422
    assert NotFoundError("MISSING", "missing").status_code == 404
    assert ConflictError("CONFLICT", "conflict").status_code == 409
    assert AuthenticationError("AUTH", "auth").status_code == 401
    assert AuthorizationError("DENIED", "denied").status_code == 403
    assert ExternalServiceError("UPSTREAM", "upstream").status_code == 502
    assert InfrastructureError("INFRA", "infra").status_code == 503
