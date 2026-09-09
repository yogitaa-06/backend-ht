from __future__ import annotations

from uuid import UUID

import httpx
import pytest

from app.resumes.storage import (
    ResumeStorageError,
    SupabaseResumeStorage,
    build_resume_object_key,
)

SUPABASE_URL = "https://example.supabase.co"
SECRET_KEY = "test-storage-token"  # noqa: S105 - non-secret test fixture value.
BUCKET = "private resumes"

OWNER_ID = UUID("11111111-1111-1111-1111-111111111111")
RESUME_ID = UUID("22222222-2222-2222-2222-222222222222")


def test_build_resume_object_key() -> None:
    object_key = build_resume_object_key(
        OWNER_ID,
        RESUME_ID,
    )

    assert object_key == (
        "11111111-1111-1111-1111-111111111111/22222222-2222-2222-2222-222222222222.pdf"
    )


@pytest.mark.anyio
async def test_supabase_adapter_uploads_private_pdf() -> None:
    captured_request: httpx.Request | None = None

    async def handler(
        request: httpx.Request,
    ) -> httpx.Response:
        nonlocal captured_request
        captured_request = request

        return httpx.Response(
            status_code=200,
            json={"Key": "stored"},
        )

    transport = httpx.MockTransport(handler)

    async with httpx.AsyncClient(
        transport=transport,
    ) as client:
        storage = SupabaseResumeStorage(
            client=client,
            supabase_url=SUPABASE_URL,
            secret_key=SECRET_KEY,
            bucket=BUCKET,
        )

        await storage.upload(
            object_key="owner id/resume name.pdf",
            content=b"%PDF-1.7 test",
            content_type="application/pdf",
        )

    assert captured_request is not None

    assert str(captured_request.url) == (
        "https://example.supabase.co/storage/v1/object/"
        "private%20resumes/owner%20id/resume%20name.pdf"
    )

    assert captured_request.method == "POST"
    assert captured_request.headers["apikey"] == SECRET_KEY
    assert captured_request.headers["authorization"] == f"Bearer {SECRET_KEY}"
    assert captured_request.headers["x-upsert"] == "false"
    assert captured_request.headers["content-type"] == "application/pdf"
    assert captured_request.content == b"%PDF-1.7 test"


@pytest.mark.anyio
async def test_supabase_adapter_url_encodes_path_components() -> None:
    captured_url: str | None = None

    async def handler(
        request: httpx.Request,
    ) -> httpx.Response:
        nonlocal captured_url
        captured_url = str(request.url)

        return httpx.Response(status_code=200)

    transport = httpx.MockTransport(handler)

    async with httpx.AsyncClient(
        transport=transport,
    ) as client:
        storage = SupabaseResumeStorage(
            client=client,
            supabase_url=SUPABASE_URL,
            secret_key=SECRET_KEY,
            bucket="résumé bucket",
        )

        await storage.upload(
            object_key="owner+one/file #1.pdf",
            content=b"%PDF-test",
            content_type="application/pdf",
        )

    assert captured_url == (
        "https://example.supabase.co/storage/v1/object/"
        "r%C3%A9sum%C3%A9%20bucket/"
        "owner%2Bone/file%20%231.pdf"
    )


@pytest.mark.anyio
async def test_supabase_adapter_upload_sends_upsert_false() -> None:
    async def handler(
        request: httpx.Request,
    ) -> httpx.Response:
        assert request.headers["x-upsert"] == "false"
        return httpx.Response(status_code=201)

    transport = httpx.MockTransport(handler)

    async with httpx.AsyncClient(
        transport=transport,
    ) as client:
        storage = SupabaseResumeStorage(
            client=client,
            supabase_url=SUPABASE_URL,
            secret_key=SECRET_KEY,
            bucket=BUCKET,
        )

        await storage.upload(
            object_key="owner/resume.pdf",
            content=b"%PDF-1.7",
            content_type="application/pdf",
        )


@pytest.mark.anyio
async def test_supabase_adapter_delete_sends_auth_headers() -> None:
    captured_request: httpx.Request | None = None

    async def handler(
        request: httpx.Request,
    ) -> httpx.Response:
        nonlocal captured_request
        captured_request = request

        return httpx.Response(status_code=200)

    transport = httpx.MockTransport(handler)

    async with httpx.AsyncClient(
        transport=transport,
    ) as client:
        storage = SupabaseResumeStorage(
            client=client,
            supabase_url=SUPABASE_URL,
            secret_key=SECRET_KEY,
            bucket=BUCKET,
        )

        await storage.delete(
            object_key="owner/resume.pdf",
        )

    assert captured_request is not None
    assert captured_request.method == "DELETE"
    assert captured_request.headers["apikey"] == SECRET_KEY
    assert captured_request.headers["authorization"] == f"Bearer {SECRET_KEY}"


@pytest.mark.anyio
async def test_supabase_adapter_delete_404_is_idempotent() -> None:
    async def handler(
        request: httpx.Request,
    ) -> httpx.Response:
        return httpx.Response(
            status_code=404,
            json={"message": "Object not found"},
        )

    transport = httpx.MockTransport(handler)

    async with httpx.AsyncClient(
        transport=transport,
    ) as client:
        storage = SupabaseResumeStorage(
            client=client,
            supabase_url=SUPABASE_URL,
            secret_key=SECRET_KEY,
            bucket=BUCKET,
        )

        await storage.delete(
            object_key="owner/missing.pdf",
        )


@pytest.mark.anyio
async def test_supabase_adapter_upload_failure_is_wrapped() -> None:
    async def handler(
        request: httpx.Request,
    ) -> httpx.Response:
        return httpx.Response(
            status_code=500,
            json={"message": (f"failure involving {SECRET_KEY}")},
        )

    transport = httpx.MockTransport(handler)

    async with httpx.AsyncClient(
        transport=transport,
    ) as client:
        storage = SupabaseResumeStorage(
            client=client,
            supabase_url=SUPABASE_URL,
            secret_key=SECRET_KEY,
            bucket=BUCKET,
        )

        with pytest.raises(
            ResumeStorageError,
        ) as exc_info:
            await storage.upload(
                object_key="owner/resume.pdf",
                content=b"%PDF-test",
                content_type="application/pdf",
            )

    error_text = str(exc_info.value)

    assert "upload" in error_text
    assert "500" in error_text
    assert SECRET_KEY not in error_text
    assert "failure involving" not in error_text


@pytest.mark.anyio
async def test_supabase_adapter_delete_failure_is_wrapped() -> None:
    async def handler(
        request: httpx.Request,
    ) -> httpx.Response:
        return httpx.Response(
            status_code=403,
            json={"message": SECRET_KEY},
        )

    transport = httpx.MockTransport(handler)

    async with httpx.AsyncClient(
        transport=transport,
    ) as client:
        storage = SupabaseResumeStorage(
            client=client,
            supabase_url=SUPABASE_URL,
            secret_key=SECRET_KEY,
            bucket=BUCKET,
        )

        with pytest.raises(
            ResumeStorageError,
        ) as exc_info:
            await storage.delete(
                object_key="owner/resume.pdf",
            )

    error_text = str(exc_info.value)

    assert "delete" in error_text
    assert "403" in error_text
    assert SECRET_KEY not in error_text


@pytest.mark.anyio
async def test_supabase_adapter_request_error_is_wrapped_without_secret() -> None:
    async def handler(
        request: httpx.Request,
    ) -> httpx.Response:
        raise httpx.ConnectError(
            f"connection failed {SECRET_KEY}",
            request=request,
        )

    transport = httpx.MockTransport(handler)

    async with httpx.AsyncClient(
        transport=transport,
    ) as client:
        storage = SupabaseResumeStorage(
            client=client,
            supabase_url=SUPABASE_URL,
            secret_key=SECRET_KEY,
            bucket=BUCKET,
        )

        with pytest.raises(
            ResumeStorageError,
        ) as exc_info:
            await storage.upload(
                object_key="owner/resume.pdf",
                content=b"%PDF-test",
                content_type="application/pdf",
            )

    error_text = str(exc_info.value)

    assert error_text == "Resume storage upload failed"
    assert SECRET_KEY not in error_text
