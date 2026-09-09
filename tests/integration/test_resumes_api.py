"""HTTP contract tests for authenticated, owner-scoped resume routes."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, status
from httpx import ASGITransport, AsyncClient

from app.api.v1.routes.resumes import _validated_upload
from app.auth.dependencies import get_current_profile
from app.core.config import Settings
from app.core.errors import ApplicationError
from app.db.session import get_session
from app.domain.profiles import Profile
from app.domain.resumes import CandidateProfile, Resume, ResumeStatus
from app.main import create_app
from app.resumes.dependencies import get_resume_service
from app.resumes.service import ResumeService


def _profile() -> Profile:
    now = datetime.now(UTC)
    return Profile(
        id=uuid4(),
        auth_user_id=uuid4(),
        email="owner@example.com",
        created_at=now,
        updated_at=now,
    )


def _resume(owner_id: UUID, *, filename: str = "resume.pdf") -> Resume:
    now = datetime.now(UTC)
    resume_id = uuid4()
    return Resume(
        id=resume_id,
        owner_profile_id=owner_id,
        original_filename=filename,
        storage_bucket="private-resumes",
        storage_object_key=f"{owner_id}/{resume_id}.pdf",
        content_type="application/pdf",
        size_bytes=12,
        sha256="a" * 64,
        status=ResumeStatus.PARSED,
        parser_version="deterministic-v1",
        created_at=now,
        updated_at=now,
    )


def _candidate_profile(owner_id: UUID, resume_id: UUID) -> CandidateProfile:
    now = datetime.now(UTC)
    return CandidateProfile(
        id=uuid4(),
        resume_id=resume_id,
        owner_profile_id=owner_id,
        full_name="Candidate Name",
        email="candidate@example.com",
        years_of_experience=Decimal("6.5"),
        extracted_text="private extracted text",
        skills=["Python"],
        employment_history=[{"company": "Example", "title": "Engineer"}],
        education=[],
        certifications=[],
        languages=["English"],
        raw_parser_output={"private": "diagnostic"},
        created_at=now,
        updated_at=now,
    )


def _application(
    settings: Settings,
    *,
    profile: Profile,
    service: AsyncMock,
) -> FastAPI:
    application = create_app(settings)

    async def current_profile_override() -> Profile:
        return profile

    async def session_override() -> AsyncIterator[object]:
        yield object()

    application.dependency_overrides[get_current_profile] = current_profile_override
    application.dependency_overrides[get_session] = session_override
    application.dependency_overrides[get_resume_service] = lambda: service
    return application


async def _client(application: FastAPI) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=application, raise_app_exceptions=False),
        base_url="http://testserver",
    )


@pytest.mark.anyio
async def test_resume_routes_require_authentication(test_settings: Settings) -> None:
    application = create_app(test_settings)

    async def session_override() -> AsyncIterator[object]:
        yield object()

    application.dependency_overrides[get_session] = session_override
    async with await _client(application) as client:
        response = await client.get("/api/v1/resumes")

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


@pytest.mark.anyio
async def test_upload_uses_authenticated_owner_and_returns_only_safe_fields(
    test_settings: Settings,
) -> None:
    profile = _profile()
    service = AsyncMock(spec=ResumeService)
    service.upload.return_value = _resume(profile.id)
    application = _application(test_settings, profile=profile, service=service)

    async with await _client(application) as client:
        response = await client.post(
            "/api/v1/resumes",
            data={"owner_profile_id": str(uuid4())},
            files={"file": ("resume.pdf", b"%PDF-content", "application/pdf")},
        )

    assert response.status_code == status.HTTP_201_CREATED
    payload = response.json()
    assert payload["original_filename"] == "resume.pdf"
    assert {
        "storage_bucket",
        "storage_object_key",
        "sha256",
        "deleted_at",
    }.isdisjoint(payload)
    assert service.upload.await_args.kwargs["owner_profile_id"] == profile.id
    upload = service.upload.await_args.kwargs["upload"]
    assert upload.content == b"%PDF-content"
    assert upload.sha256 not in payload.values()


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("filename", "content_type", "content", "expected_status", "expected_code"),
    [
        (
            "resume.pdf",
            "application/pdf",
            b"not-a-pdf",
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "RESUME_FILE_INVALID",
        ),
        (
            "resume.pdf",
            "text/plain",
            b"%PDF-content",
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "RESUME_CONTENT_TYPE_UNSUPPORTED",
        ),
        (
            "resume.exe.pdf",
            "application/pdf",
            b"%PDF-content",
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "RESUME_FILENAME_UNSAFE",
        ),
    ],
)
async def test_upload_rejects_unsafe_files_with_stable_errors(
    test_settings: Settings,
    filename: str,
    content_type: str,
    content: bytes,
    expected_status: int,
    expected_code: str,
) -> None:
    profile = _profile()
    service = AsyncMock(spec=ResumeService)
    application = _application(test_settings, profile=profile, service=service)

    async with await _client(application) as client:
        response = await client.post(
            "/api/v1/resumes",
            files={"file": (filename, content, content_type)},
        )

    assert response.status_code == expected_status
    assert response.json()["error"]["code"] == expected_code
    service.upload.assert_not_awaited()


@pytest.mark.anyio
async def test_upload_reads_only_one_byte_beyond_limit_and_closes_file(
    test_settings: Settings,
) -> None:
    settings = test_settings.model_copy(update={"resume_max_size_bytes": 1_024})
    file = AsyncMock()
    file.filename = "resume.pdf"
    file.content_type = "application/pdf"
    file.read.return_value = b"%PDF-" + (b"x" * 1_020)

    with pytest.raises(ApplicationError) as raised:
        await _validated_upload(file, settings)

    assert raised.value.code == "RESUME_FILE_TOO_LARGE"
    file.read.assert_awaited_once_with(1_025)
    file.close.assert_awaited_once()


@pytest.mark.anyio
async def test_upload_closes_file_when_read_fails(test_settings: Settings) -> None:
    file = AsyncMock()
    file.read.side_effect = OSError("upload stream failed")

    with pytest.raises(OSError, match="upload stream failed"):
        await _validated_upload(file, test_settings)

    file.close.assert_awaited_once()


@pytest.mark.anyio
async def test_upload_rejects_oversized_body_with_stable_http_error(
    test_settings: Settings,
) -> None:
    settings = test_settings.model_copy(update={"resume_max_size_bytes": 1_024})
    profile = _profile()
    service = AsyncMock(spec=ResumeService)
    application = _application(settings, profile=profile, service=service)

    async with await _client(application) as client:
        response = await client.post(
            "/api/v1/resumes",
            files={
                "file": (
                    "resume.pdf",
                    b"%PDF-" + (b"x" * 1_020),
                    "application/pdf",
                )
            },
        )

    assert response.status_code == status.HTTP_413_CONTENT_TOO_LARGE
    assert response.json()["error"]["code"] == "RESUME_FILE_TOO_LARGE"
    service.upload.assert_not_awaited()


@pytest.mark.anyio
async def test_list_forwards_pagination_and_excludes_private_fields(
    test_settings: Settings,
) -> None:
    profile = _profile()
    service = AsyncMock(spec=ResumeService)
    service.list_owned.return_value = ([_resume(profile.id)], 1)
    application = _application(test_settings, profile=profile, service=service)

    async with await _client(application) as client:
        response = await client.get("/api/v1/resumes?offset=2&limit=7")

    assert response.status_code == status.HTTP_200_OK
    payload = response.json()
    assert payload["offset"] == 2
    assert payload["limit"] == 7
    assert payload["total"] == 1
    assert "storage_object_key" not in payload["items"][0]
    service.list_owned.assert_awaited_once()
    assert service.list_owned.await_args.kwargs == {
        "owner_profile_id": profile.id,
        "offset": 2,
        "limit": 7,
    }


@pytest.mark.anyio
@pytest.mark.parametrize("query", ["offset=-1", "limit=0", "limit=101"])
async def test_list_rejects_invalid_pagination(
    test_settings: Settings,
    query: str,
) -> None:
    profile = _profile()
    service = AsyncMock(spec=ResumeService)
    application = _application(test_settings, profile=profile, service=service)

    async with await _client(application) as client:
        response = await client.get(f"/api/v1/resumes?{query}")

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert response.json()["error"]["code"] == "REQUEST_VALIDATION_FAILED"
    service.list_owned.assert_not_awaited()


@pytest.mark.anyio
async def test_candidate_profile_is_owner_scoped_and_hides_parser_data(
    test_settings: Settings,
) -> None:
    profile = _profile()
    resume_id = uuid4()
    service = AsyncMock(spec=ResumeService)
    service.get_candidate_profile.return_value = _candidate_profile(profile.id, resume_id)
    application = _application(test_settings, profile=profile, service=service)

    async with await _client(application) as client:
        response = await client.get(f"/api/v1/resumes/{resume_id}/profile")

    assert response.status_code == status.HTTP_200_OK
    payload = response.json()
    assert payload["resume_id"] == str(resume_id)
    assert payload["full_name"] == "Candidate Name"
    assert "extracted_text" not in payload
    assert "raw_parser_output" not in payload
    assert "owner_profile_id" not in payload
    assert service.get_candidate_profile.await_args.kwargs == {
        "resume_id": resume_id,
        "owner_profile_id": profile.id,
    }


@pytest.mark.anyio
async def test_candidate_profile_missing_is_generic_not_found(
    test_settings: Settings,
) -> None:
    profile = _profile()
    service = AsyncMock(spec=ResumeService)
    service.get_candidate_profile.side_effect = ApplicationError(
        "NOT_FOUND",
        "The requested resource was not found.",
        status.HTTP_404_NOT_FOUND,
    )
    application = _application(test_settings, profile=profile, service=service)

    async with await _client(application) as client:
        response = await client.get(f"/api/v1/resumes/{uuid4()}/profile")

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json()["error"] == {
        "code": "NOT_FOUND",
        "message": "The requested resource was not found.",
        "request_id": response.headers["X-Request-ID"],
    }


@pytest.mark.anyio
async def test_replace_validates_upload_and_uses_authenticated_owner(
    test_settings: Settings,
) -> None:
    profile = _profile()
    old_resume_id = uuid4()
    service = AsyncMock(spec=ResumeService)
    service.replace.return_value = _resume(profile.id, filename="replacement.pdf")
    application = _application(test_settings, profile=profile, service=service)

    async with await _client(application) as client:
        response = await client.post(
            f"/api/v1/resumes/{old_resume_id}/replace",
            files={"file": ("replacement.pdf", b"%PDF-new", "application/pdf")},
        )

    assert response.status_code == status.HTTP_200_OK
    payload = response.json()
    assert payload["replaced"] is True
    assert payload["resume"]["original_filename"] == "replacement.pdf"
    assert "storage_object_key" not in payload["resume"]
    assert service.replace.await_args.kwargs["resume_id"] == old_resume_id
    assert service.replace.await_args.kwargs["owner_profile_id"] == profile.id


@pytest.mark.anyio
async def test_replace_rejects_invalid_upload_before_service(
    test_settings: Settings,
) -> None:
    profile = _profile()
    service = AsyncMock(spec=ResumeService)
    application = _application(test_settings, profile=profile, service=service)

    async with await _client(application) as client:
        response = await client.post(
            f"/api/v1/resumes/{uuid4()}/replace",
            files={"file": ("replacement.pdf", b"invalid", "application/pdf")},
        )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert response.json()["error"]["code"] == "RESUME_FILE_INVALID"
    service.replace.assert_not_awaited()


@pytest.mark.anyio
async def test_delete_uses_authenticated_owner_and_returns_safe_contract(
    test_settings: Settings,
) -> None:
    profile = _profile()
    resume = _resume(profile.id)
    service = AsyncMock(spec=ResumeService)
    service.delete.return_value = resume
    application = _application(test_settings, profile=profile, service=service)

    async with await _client(application) as client:
        response = await client.delete(f"/api/v1/resumes/{resume.id}")

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"resume_id": str(resume.id), "deleted": True}
    assert service.delete.await_args.kwargs == {
        "resume_id": resume.id,
        "owner_profile_id": profile.id,
    }


@pytest.mark.anyio
async def test_delete_missing_or_wrong_owner_is_generic_not_found(
    test_settings: Settings,
) -> None:
    profile = _profile()
    service = AsyncMock(spec=ResumeService)
    service.delete.side_effect = ApplicationError(
        "NOT_FOUND",
        "The requested resource was not found.",
        status.HTTP_404_NOT_FOUND,
    )
    application = _application(test_settings, profile=profile, service=service)

    async with await _client(application) as client:
        response = await client.delete(f"/api/v1/resumes/{uuid4()}")

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json()["error"]["code"] == "NOT_FOUND"
