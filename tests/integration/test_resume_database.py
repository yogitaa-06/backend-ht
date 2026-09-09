"""Real-PostgreSQL persistence and integrity coverage for secure resumes."""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError

from app.core.config import Settings
from app.db.session import Database
from app.domain.profiles import Profile
from app.domain.resumes import CandidateProfile, Resume, ResumeStatus
from app.repositories.resumes import CandidateProfileRepository, ResumeRepository
from app.resumes.service import ResumeService
from app.resumes.validation import ValidatedResumeUpload
from app.schemas.resumes import ParsedResume

TEST_DATABASE_URL = os.getenv("HIREANDTECH_TEST_DATABASE_URL")

pytestmark = [
    pytest.mark.database,
    pytest.mark.anyio,
    pytest.mark.skipif(
        TEST_DATABASE_URL is None,
        reason="HIREANDTECH_TEST_DATABASE_URL is not configured",
    ),
]


class FakeResumeStorage:
    """In-memory call recorder that never contacts external storage."""

    def __init__(self) -> None:
        self.uploaded: list[str] = []
        self.deleted: list[str] = []

    async def upload(
        self,
        *,
        object_key: str,
        content: bytes,
        content_type: str,
    ) -> None:
        del content, content_type
        self.uploaded.append(object_key)

    async def delete(self, *, object_key: str) -> None:
        self.deleted.append(object_key)


class FakeResumeParser:
    """Deterministic parser fake for persistence tests."""

    def parse(self, content: bytes) -> ParsedResume:
        del content
        return ParsedResume(
            full_name="Database Candidate",
            extracted_text="bounded parsed resume text",
            skills=["Python", "PostgreSQL"],
            raw_parser_output={"page_count": 1},
        )


def _migrated_settings() -> Settings:
    assert TEST_DATABASE_URL is not None
    environment = os.environ.copy()
    environment.update(
        HIREANDTECH_ENVIRONMENT="test",
        HIREANDTECH_DATABASE_URL=TEST_DATABASE_URL,
        HIREANDTECH_DATABASE_MIGRATION_URL=TEST_DATABASE_URL,
        HIREANDTECH_DATABASE_SSL_MODE="disable",
    )
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, "test database migration failed"
    return Settings(
        _env_file=None,
        environment="test",
        database_url=SecretStr(TEST_DATABASE_URL),
        database_ssl_mode="disable",
        resume_storage_bucket="private-resumes",
    )


def _upload(seed: str) -> ValidatedResumeUpload:
    return ValidatedResumeUpload(
        original_filename=f"{seed}.pdf",
        content_type="application/pdf",
        size_bytes=12,
        sha256=(seed[0] * 64),
        content=b"%PDF-content",
    )


async def _cleanup(database: Database, owner_ids: set[UUID]) -> None:
    async with database.sessions() as session:
        await session.execute(
            delete(CandidateProfile).where(CandidateProfile.owner_profile_id.in_(owner_ids))
        )
        await session.execute(delete(Resume).where(Resume.owner_profile_id.in_(owner_ids)))
        await session.execute(delete(Profile).where(Profile.id.in_(owner_ids)))
        await session.commit()


async def test_resume_lifecycle_persistence_owner_isolation_and_listing() -> None:
    settings = _migrated_settings()
    database = Database(settings)
    owners = [
        Profile(auth_user_id=uuid4(), email=f"phase5-a-{uuid4()}@example.com"),
        Profile(auth_user_id=uuid4(), email=f"phase5-b-{uuid4()}@example.com"),
    ]
    owner_ids: set[UUID] = set()
    storage = FakeResumeStorage()
    service = ResumeService(
        settings,
        storage=storage,
        parser=FakeResumeParser(),
    )

    try:
        async with database.sessions() as session:
            session.add_all(owners)
            await session.commit()
            owner_ids = {owner.id for owner in owners}

            first = await service.upload(
                session,
                owner_profile_id=owners[0].id,
                upload=_upload("a"),
            )
            assert first.status is ResumeStatus.PARSED
            assert first.owner_profile_id == owners[0].id

            resumes = ResumeRepository()
            profiles = CandidateProfileRepository()
            assert (
                await resumes.get_owned(
                    session,
                    resume_id=first.id,
                    owner_profile_id=owners[1].id,
                )
                is None
            )
            assert (
                await profiles.get_owned_by_resume_id(
                    session,
                    resume_id=first.id,
                    owner_profile_id=owners[1].id,
                )
                is None
            )

            parsed = await profiles.get_owned_by_resume_id(
                session,
                resume_id=first.id,
                owner_profile_id=owners[0].id,
            )
            assert parsed is not None
            assert parsed.resume_id == first.id
            assert parsed.owner_profile_id == owners[0].id
            assert parsed.full_name == "Database Candidate"

            own_items, own_total = await resumes.list_owned_page(
                session,
                owner_profile_id=owners[0].id,
                offset=0,
                limit=50,
            )
            other_items, other_total = await resumes.list_owned_page(
                session,
                owner_profile_id=owners[1].id,
                offset=0,
                limit=50,
            )
            assert [item.id for item in own_items] == [first.id]
            assert own_total == 1
            assert other_items == []
            assert other_total == 0

            await service.delete(
                session,
                resume_id=first.id,
                owner_profile_id=owners[0].id,
            )
            assert first.status.value == ResumeStatus.DELETED.value
            assert first.deleted_at is not None
            assert await service.list_owned(
                session,
                owner_profile_id=owners[0].id,
                offset=0,
                limit=50,
            ) == ([], 0)

            old = await service.upload(
                session,
                owner_profile_id=owners[0].id,
                upload=_upload("b"),
            )
            replacement = await service.replace(
                session,
                resume_id=old.id,
                owner_profile_id=owners[0].id,
                upload=_upload("c"),
            )
            assert old.status is ResumeStatus.DELETED
            assert old.deleted_at is not None
            assert replacement.status is ResumeStatus.PARSED

            active, total = await service.list_owned(
                session,
                owner_profile_id=owners[0].id,
                offset=0,
                limit=50,
            )
            assert [item.id for item in active] == [replacement.id]
            assert total == 1

            replacement_profile = await service.get_candidate_profile(
                session,
                resume_id=replacement.id,
                owner_profile_id=owners[0].id,
            )
            assert replacement_profile.resume_id == replacement.id
            assert replacement_profile.owner_profile_id == owners[0].id
    finally:
        try:
            if owner_ids:
                await _cleanup(database, owner_ids)
        finally:
            await database.close()


def _resume(
    owner_id: UUID,
    *,
    status: ResumeStatus,
    deleted_at: datetime | None,
    digest_character: str,
) -> Resume:
    resume_id = uuid4()
    return Resume(
        id=resume_id,
        owner_profile_id=owner_id,
        original_filename="resume.pdf",
        storage_bucket="private-resumes",
        storage_object_key=f"{owner_id}/{resume_id}.pdf",
        content_type="application/pdf",
        size_bytes=12,
        sha256=digest_character * 64,
        status=status,
        parser_version="deterministic-v1",
        deleted_at=deleted_at,
    )


async def test_resume_delete_state_and_candidate_ownership_constraints() -> None:
    database = Database(_migrated_settings())
    owners = [
        Profile(auth_user_id=uuid4(), email=f"phase5-c-{uuid4()}@example.com"),
        Profile(auth_user_id=uuid4(), email=f"phase5-d-{uuid4()}@example.com"),
    ]
    owner_ids: set[UUID] = set()

    try:
        async with database.sessions() as session:
            session.add_all(owners)
            await session.commit()
            owner_ids = {owner.id for owner in owners}
            owner_a_id = owners[0].id
            owner_b_id = owners[1].id

            session.add(
                _resume(
                    owner_a_id,
                    status=ResumeStatus.DELETED,
                    deleted_at=None,
                    digest_character="d",
                )
            )
            with pytest.raises(IntegrityError):
                await session.commit()
            await session.rollback()

            session.add(
                _resume(
                    owner_a_id,
                    status=ResumeStatus.PARSED,
                    deleted_at=datetime.now(UTC),
                    digest_character="e",
                )
            )
            with pytest.raises(IntegrityError):
                await session.commit()
            await session.rollback()

            valid = _resume(
                owner_a_id,
                status=ResumeStatus.PARSED,
                deleted_at=None,
                digest_character="f",
            )
            session.add(valid)
            await session.commit()
            valid_id = valid.id

            session.add(
                CandidateProfile(
                    resume_id=valid_id,
                    owner_profile_id=owner_b_id,
                    extracted_text="wrong owner",
                )
            )
            with pytest.raises(IntegrityError):
                await session.commit()
            await session.rollback()

            session.add(
                CandidateProfile(
                    resume_id=valid_id,
                    owner_profile_id=owner_a_id,
                    extracted_text="first",
                )
            )
            await session.commit()

            session.add(
                CandidateProfile(
                    resume_id=valid_id,
                    owner_profile_id=owner_a_id,
                    extracted_text="duplicate",
                )
            )
            with pytest.raises(IntegrityError):
                await session.commit()
            await session.rollback()
    finally:
        try:
            if owner_ids:
                await _cleanup(database, owner_ids)
        finally:
            await database.close()
