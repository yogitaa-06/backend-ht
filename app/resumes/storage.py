"""Private storage contract and Supabase adapter for resume documents."""

from __future__ import annotations

from typing import Protocol
from urllib.parse import quote
from uuid import UUID

import httpx


class ResumeStorageError(RuntimeError):
    """Raised when private resume storage cannot complete an operation."""


class ResumeStorage(Protocol):
    """Storage operations required by the resume service."""

    async def upload(
        self,
        *,
        object_key: str,
        content: bytes,
        content_type: str,
    ) -> None:
        """Upload one private resume object."""
        ...

    async def delete(
        self,
        *,
        object_key: str,
    ) -> None:
        """Delete one private resume object."""
        ...


def build_resume_object_key(
    owner_id: UUID,
    resume_id: UUID,
) -> str:
    """Build an ownership-scoped, non-user-controlled storage key."""
    return f"{owner_id}/{resume_id}.pdf"


class SupabaseResumeStorage:
    """Store private resumes through the Supabase Storage REST API."""

    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        supabase_url: str,
        secret_key: str,
        bucket: str,
    ) -> None:
        if not supabase_url.strip():
            raise ValueError("Supabase URL is required")

        if not secret_key:
            raise ValueError("Supabase secret key is required")

        if not bucket.strip():
            raise ValueError("Resume storage bucket is required")

        self._client = client
        self._supabase_url = supabase_url.rstrip("/")
        self._secret_key = secret_key
        self._bucket = bucket

    def _object_url(self, object_key: str) -> str:
        encoded_bucket = quote(self._bucket, safe="")

        encoded_key = "/".join(quote(component, safe="") for component in object_key.split("/"))

        return f"{self._supabase_url}/storage/v1/object/{encoded_bucket}/{encoded_key}"

    def _authorization_headers(self) -> dict[str, str]:
        return {
            "apikey": self._secret_key,
            "Authorization": f"Bearer {self._secret_key}",
        }

    async def upload(
        self,
        *,
        object_key: str,
        content: bytes,
        content_type: str,
    ) -> None:
        """Upload without silently replacing an existing object."""
        try:
            response = await self._client.post(
                self._object_url(object_key),
                headers={
                    **self._authorization_headers(),
                    "Content-Type": content_type,
                    "x-upsert": "false",
                },
                content=content,
            )
        except httpx.RequestError as exc:
            raise ResumeStorageError("Resume storage upload failed") from exc

        if not response.is_success:
            raise ResumeStorageError(
                f"Resume storage upload failed with HTTP status {response.status_code}"
            )

    async def delete(
        self,
        *,
        object_key: str,
    ) -> None:
        """Delete an object, treating an absent object as deleted."""
        try:
            response = await self._client.delete(
                self._object_url(object_key),
                headers=self._authorization_headers(),
            )
        except httpx.RequestError as exc:
            raise ResumeStorageError("Resume storage delete failed") from exc

        if response.status_code == httpx.codes.NOT_FOUND:
            return

        if not response.is_success:
            raise ResumeStorageError(
                f"Resume storage delete failed with HTTP status {response.status_code}"
            )
