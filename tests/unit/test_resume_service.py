"""Unit tests for transactional resume upload orchestration."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.exc import StaleDataError

from app.core.config import Settings
from app.core.errors import ApplicationError
from app.domain.resumes import CandidateProfile, Resume, ResumeStatus, ResumeStorageCleanup
from app.repositories.resumes import (
    CandidateProfileRepository,
    ResumeRepository,
    ResumeStorageCleanupRepository,
)
from app.resumes.execution import ResumeParseExecutor, ResumeParserExecutionError
from app.resumes.parser import ResumeParser
from app.resumes.service import ResumeService
from app.resumes.storage import ResumeStorage, ResumeStorageError
from app.resumes.validation import ValidatedResumeUpload
from app.schemas.resumes import EducationEntry, EmploymentEntry, ParsedResume


def _settings() -> MagicMock:
    settings = MagicMock(spec=Settings)
    settings.resume_storage_bucket = "resumes"
    settings.resume_parser_version = "deterministic-v1"
    return settings


def _upload() -> ValidatedResumeUpload:
    return ValidatedResumeUpload(
        original_filename="resume.pdf",
        content_type="application/pdf",
        size_bytes=12,
        sha256="a" * 64,
        content=b"%PDF-content",
    )


def _parsed() -> ParsedResume:
    return ParsedResume(
        full_name="Candidate Name",
        email="candidate@example.com",
        phone="+1 555 0100",
        location="New York",
        current_title="Backend Engineer",
        professional_summary="Backend engineer.",
        years_of_experience=Decimal("7.5"),
        extracted_text="Candidate resume text",
        skills=["Python", "FastAPI"],
        employment_history=[
            EmploymentEntry(
                company="Example",
                title="Backend Engineer",
            )
        ],
        education=[
            EducationEntry(
                institution="Example University",
                qualification="BS",
            )
        ],
        certifications=["AWS"],
        languages=["English"],
        raw_parser_output={"page_count": 2},
    )


def _dependencies() -> tuple[
    AsyncMock,
    MagicMock,
    MagicMock,
    AsyncMock,
    AsyncMock,
]:
    session = AsyncMock(spec=AsyncSession)
    session.add = MagicMock()
    execute_result = MagicMock()
    execute_result.scalar_one_or_none.return_value = None
    session.execute.return_value = execute_result
    storage = MagicMock(spec=ResumeStorage)
    storage.upload = AsyncMock()
    storage.delete = AsyncMock()

    parser = MagicMock(spec=ResumeParser)
    parser.parse.return_value = _parsed()

    resumes = AsyncMock(spec=ResumeRepository)
    profiles = AsyncMock(spec=CandidateProfileRepository)

    return session, storage, parser, resumes, profiles


@pytest.mark.anyio
async def test_upload_stores_parses_and_commits_once() -> None:
    session, storage, parser, resumes, profiles = _dependencies()
    owner_profile_id = uuid4()
    upload = _upload()

    service = ResumeService(
        _settings(),
        storage=storage,
        parser=parser,
        resumes=resumes,
        candidate_profiles=profiles,
    )

    result = await service.upload(
        session,
        owner_profile_id=owner_profile_id,
        upload=upload,
    )

    assert isinstance(result, Resume)
    assert result.owner_profile_id == owner_profile_id
    assert result.status == ResumeStatus.PARSED
    assert result.parser_version == "deterministic-v1"
    assert result.parse_error_code is None

    storage.upload.assert_awaited_once()
    parser.parse.assert_called_once_with(upload.content)
    resumes.add.assert_awaited_once()
    profiles.add.assert_awaited_once()
    assert session.flush.await_count == 2
    assert session.commit.await_count == 2
    session.rollback.assert_not_awaited()
    storage.delete.assert_not_awaited()


@pytest.mark.anyio
async def test_upload_generates_owner_scoped_backend_object_key() -> None:
    session, storage, parser, resumes, profiles = _dependencies()
    owner_profile_id = uuid4()

    service = ResumeService(
        _settings(),
        storage=storage,
        parser=parser,
        resumes=resumes,
        candidate_profiles=profiles,
    )

    result = await service.upload(
        session,
        owner_profile_id=owner_profile_id,
        upload=_upload(),
    )

    kwargs = storage.upload.await_args.kwargs
    object_key = kwargs["object_key"]

    assert object_key == f"{owner_profile_id}/{result.id}.pdf"
    assert result.storage_object_key == object_key
    assert result.storage_bucket == "resumes"
    assert isinstance(result.id, UUID)


@pytest.mark.anyio
async def test_upload_persists_candidate_profile_for_same_owner() -> None:
    session, storage, parser, resumes, profiles = _dependencies()
    owner_profile_id = uuid4()

    service = ResumeService(
        _settings(),
        storage=storage,
        parser=parser,
        resumes=resumes,
        candidate_profiles=profiles,
    )

    resume = await service.upload(
        session,
        owner_profile_id=owner_profile_id,
        upload=_upload(),
    )

    profile = profiles.add.await_args.args[1]

    assert isinstance(profile, CandidateProfile)
    assert profile.resume_id == resume.id
    assert profile.owner_profile_id == owner_profile_id
    assert profile.full_name == "Candidate Name"
    assert profile.email == "candidate@example.com"
    assert profile.years_of_experience == Decimal("7.5")
    assert profile.extracted_text == "Candidate resume text"
    assert profile.skills == ["Python", "FastAPI"]
    assert profile.certifications == ["AWS"]
    assert profile.languages == ["English"]
    assert profile.raw_parser_output == {"page_count": 2}
    assert profile.employment_history == [
        {
            "company": "Example",
            "title": "Backend Engineer",
            "location": None,
            "start_date": None,
            "end_date": None,
            "description": None,
        }
    ]


@pytest.mark.anyio
async def test_storage_failure_does_not_parse_or_touch_database() -> None:
    session, storage, parser, resumes, profiles = _dependencies()

    storage.upload.side_effect = ResumeStorageError("private storage diagnostic")

    service = ResumeService(
        _settings(),
        storage=storage,
        parser=parser,
        resumes=resumes,
        candidate_profiles=profiles,
    )

    with pytest.raises(ApplicationError) as raised:
        await service.upload(
            session,
            owner_profile_id=uuid4(),
            upload=_upload(),
        )

    assert raised.value.code == "RESUME_STORAGE_UNAVAILABLE"
    assert raised.value.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert "diagnostic" not in raised.value.message

    parser.parse.assert_not_called()
    resumes.add.assert_not_awaited()
    profiles.add.assert_not_awaited()
    assert session.commit.await_count == 2


@pytest.mark.anyio
async def test_parser_failure_is_persisted_as_safe_parse_failed_state() -> None:
    session, storage, parser, resumes, profiles = _dependencies()

    parser_error = ApplicationError(
        "RESUME_PDF_INVALID",
        "The resume PDF could not be parsed.",
        status.HTTP_422_UNPROCESSABLE_CONTENT,
    )
    parser.parse.side_effect = parser_error

    service = ResumeService(
        _settings(),
        storage=storage,
        parser=parser,
        resumes=resumes,
        candidate_profiles=profiles,
    )

    with pytest.raises(ApplicationError) as raised:
        await service.upload(
            session,
            owner_profile_id=uuid4(),
            upload=_upload(),
        )

    assert raised.value is parser_error

    resume = resumes.add.await_args.args[1]
    assert resume.status == ResumeStatus.PARSE_FAILED
    assert resume.parse_error_code == "RESUME_PDF_INVALID"

    profiles.add.assert_not_awaited()
    assert session.flush.await_count == 2
    assert session.commit.await_count == 2
    session.rollback.assert_not_awaited()
    storage.delete.assert_not_awaited()


@pytest.mark.anyio
async def test_database_failure_rolls_back_and_deletes_uploaded_object() -> None:
    session, storage, parser, resumes, profiles = _dependencies()

    database_error = RuntimeError("database failure")
    session.commit.side_effect = [None, database_error, None]

    service = ResumeService(
        _settings(),
        storage=storage,
        parser=parser,
        resumes=resumes,
        candidate_profiles=profiles,
    )

    with pytest.raises(RuntimeError) as raised:
        await service.upload(
            session,
            owner_profile_id=uuid4(),
            upload=_upload(),
        )

    assert raised.value is database_error

    session.rollback.assert_awaited_once()
    storage.delete.assert_awaited_once()

    uploaded_key = storage.upload.await_args.kwargs["object_key"]
    deleted_key = storage.delete.await_args.kwargs["object_key"]

    assert deleted_key == uploaded_key


@pytest.mark.anyio
async def test_compensation_failure_does_not_replace_database_failure() -> None:
    session, storage, parser, resumes, profiles = _dependencies()

    database_error = RuntimeError("database failure")
    session.commit.side_effect = [None, database_error, None]
    storage.delete.side_effect = ResumeStorageError("storage cleanup failure")

    service = ResumeService(
        _settings(),
        storage=storage,
        parser=parser,
        resumes=resumes,
        candidate_profiles=profiles,
    )

    with pytest.raises(RuntimeError) as raised:
        await service.upload(
            session,
            owner_profile_id=uuid4(),
            upload=_upload(),
        )

    assert raised.value is database_error
    session.rollback.assert_awaited_once()
    storage.delete.assert_awaited_once()


@pytest.mark.anyio
async def test_parser_failure_database_failure_also_compensates_storage() -> None:
    session, storage, parser, resumes, profiles = _dependencies()

    parser.parse.side_effect = ApplicationError(
        "RESUME_PDF_INVALID",
        "The resume PDF could not be parsed.",
        status.HTTP_422_UNPROCESSABLE_CONTENT,
    )
    session.commit.side_effect = [None, RuntimeError("database failure"), None]

    service = ResumeService(
        _settings(),
        storage=storage,
        parser=parser,
        resumes=resumes,
        candidate_profiles=profiles,
    )

    with pytest.raises(RuntimeError):
        await service.upload(
            session,
            owner_profile_id=uuid4(),
            upload=_upload(),
        )

    session.rollback.assert_awaited_once()
    storage.delete.assert_awaited_once()


@pytest.mark.anyio
async def test_delete_requires_owner_scoped_lookup() -> None:
    session, storage, parser, resumes, profiles = _dependencies()
    owner_profile_id = uuid4()
    resume_id = uuid4()

    resumes.get_owned.return_value = None

    service = ResumeService(
        _settings(),
        storage=storage,
        parser=parser,
        resumes=resumes,
        candidate_profiles=profiles,
    )

    with pytest.raises(ApplicationError) as raised:
        await service.delete(
            session,
            resume_id=resume_id,
            owner_profile_id=owner_profile_id,
        )

    assert raised.value.code == "NOT_FOUND"
    assert raised.value.status_code == status.HTTP_404_NOT_FOUND

    resumes.get_owned.assert_awaited_once_with(
        session,
        resume_id=resume_id,
        owner_profile_id=owner_profile_id,
        include_deleted=True,
    )

    storage.delete.assert_not_awaited()
    session.commit.assert_not_awaited()


@pytest.mark.anyio
async def test_delete_soft_deletes_before_removing_storage() -> None:
    session, storage, parser, resumes, profiles = _dependencies()
    owner_profile_id = uuid4()

    resume = Resume(
        id=uuid4(),
        owner_profile_id=owner_profile_id,
        original_filename="resume.pdf",
        storage_bucket="resumes",
        storage_object_key=f"{owner_profile_id}/{uuid4()}.pdf",
        content_type="application/pdf",
        size_bytes=12,
        sha256="a" * 64,
        status=ResumeStatus.PARSED,
        parser_version="deterministic-v1",
    )

    resumes.get_owned.return_value = resume

    service = ResumeService(
        _settings(),
        storage=storage,
        parser=parser,
        resumes=resumes,
        candidate_profiles=profiles,
    )

    result = await service.delete(
        session,
        resume_id=resume.id,
        owner_profile_id=owner_profile_id,
    )

    assert result is resume
    assert resume.status == ResumeStatus.DELETED
    assert resume.deleted_at is not None
    assert resume.deleted_at.tzinfo is not None

    session.flush.assert_awaited_once()
    assert session.commit.await_count == 2
    session.rollback.assert_not_awaited()

    storage.delete.assert_awaited_once_with(
        object_key=resume.storage_object_key,
    )


@pytest.mark.anyio
async def test_delete_database_failure_rolls_back_without_touching_storage() -> None:
    session, storage, parser, resumes, profiles = _dependencies()
    owner_profile_id = uuid4()

    resume = Resume(
        id=uuid4(),
        owner_profile_id=owner_profile_id,
        original_filename="resume.pdf",
        storage_bucket="resumes",
        storage_object_key=f"{owner_profile_id}/{uuid4()}.pdf",
        content_type="application/pdf",
        size_bytes=12,
        sha256="a" * 64,
        status=ResumeStatus.PARSED,
        parser_version="deterministic-v1",
    )

    resumes.get_owned.return_value = resume
    database_error = RuntimeError("database failure")
    session.commit.side_effect = database_error

    service = ResumeService(
        _settings(),
        storage=storage,
        parser=parser,
        resumes=resumes,
        candidate_profiles=profiles,
    )

    with pytest.raises(RuntimeError) as raised:
        await service.delete(
            session,
            resume_id=resume.id,
            owner_profile_id=owner_profile_id,
        )

    assert raised.value is database_error

    session.rollback.assert_awaited_once()
    storage.delete.assert_not_awaited()


@pytest.mark.anyio
async def test_delete_storage_failure_keeps_resume_soft_deleted() -> None:
    session, storage, parser, resumes, profiles = _dependencies()
    owner_profile_id = uuid4()

    resume = Resume(
        id=uuid4(),
        owner_profile_id=owner_profile_id,
        original_filename="resume.pdf",
        storage_bucket="resumes",
        storage_object_key=f"{owner_profile_id}/{uuid4()}.pdf",
        content_type="application/pdf",
        size_bytes=12,
        sha256="a" * 64,
        status=ResumeStatus.PARSED,
        parser_version="deterministic-v1",
    )

    resumes.get_owned.return_value = resume
    storage.delete.side_effect = ResumeStorageError("storage diagnostic")

    service = ResumeService(
        _settings(),
        storage=storage,
        parser=parser,
        resumes=resumes,
        candidate_profiles=profiles,
    )

    with pytest.raises(ApplicationError) as raised:
        await service.delete(
            session,
            resume_id=resume.id,
            owner_profile_id=owner_profile_id,
        )

    assert raised.value.code == "RESUME_STORAGE_UNAVAILABLE"
    assert raised.value.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert "diagnostic" not in raised.value.message

    assert resume.status == ResumeStatus.DELETED
    assert resume.deleted_at is not None

    session.commit.assert_awaited_once()
    session.rollback.assert_not_awaited()


@pytest.mark.anyio
async def test_delete_retry_only_retries_storage_cleanup() -> None:
    session, storage, parser, resumes, profiles = _dependencies()
    owner_profile_id = uuid4()

    resume = Resume(
        id=uuid4(),
        owner_profile_id=owner_profile_id,
        original_filename="resume.pdf",
        storage_bucket="resumes",
        storage_object_key=f"{owner_profile_id}/{uuid4()}.pdf",
        content_type="application/pdf",
        size_bytes=12,
        sha256="a" * 64,
        status=ResumeStatus.DELETED,
        parser_version="deterministic-v1",
        deleted_at=datetime.now(UTC),
    )

    resumes.get_owned.return_value = resume

    service = ResumeService(
        _settings(),
        storage=storage,
        parser=parser,
        resumes=resumes,
        candidate_profiles=profiles,
    )

    result = await service.delete(
        session,
        resume_id=resume.id,
        owner_profile_id=owner_profile_id,
    )

    assert result is resume

    session.flush.assert_awaited_once()
    assert session.commit.await_count == 2
    session.rollback.assert_not_awaited()

    storage.delete.assert_awaited_once_with(
        object_key=resume.storage_object_key,
    )


@pytest.mark.anyio
async def test_replace_requires_owner_scoped_existing_resume() -> None:
    session, storage, parser, resumes, profiles = _dependencies()
    owner_profile_id = uuid4()
    resume_id = uuid4()

    resumes.get_owned.return_value = None

    service = ResumeService(
        _settings(),
        storage=storage,
        parser=parser,
        resumes=resumes,
        candidate_profiles=profiles,
    )

    with pytest.raises(ApplicationError) as raised:
        await service.replace(
            session,
            resume_id=resume_id,
            owner_profile_id=owner_profile_id,
            upload=_upload(),
        )

    assert raised.value.code == "NOT_FOUND"
    assert raised.value.status_code == status.HTTP_404_NOT_FOUND

    resumes.get_owned.assert_awaited_once_with(
        session,
        resume_id=resume_id,
        owner_profile_id=owner_profile_id,
    )

    storage.upload.assert_not_awaited()
    parser.parse.assert_not_called()
    resumes.add.assert_not_awaited()
    profiles.add.assert_not_awaited()


@pytest.mark.anyio
async def test_replace_persists_new_resume_and_retires_old_resume() -> None:
    session, storage, parser, resumes, profiles = _dependencies()
    owner_profile_id = uuid4()

    current = Resume(
        id=uuid4(),
        owner_profile_id=owner_profile_id,
        original_filename="old.pdf",
        storage_bucket="resumes",
        storage_object_key=f"{owner_profile_id}/{uuid4()}.pdf",
        content_type="application/pdf",
        size_bytes=10,
        sha256="b" * 64,
        status=ResumeStatus.PARSED,
        parser_version="deterministic-v1",
    )

    resumes.get_owned.return_value = current

    service = ResumeService(
        _settings(),
        storage=storage,
        parser=parser,
        resumes=resumes,
        candidate_profiles=profiles,
    )

    replacement = await service.replace(
        session,
        resume_id=current.id,
        owner_profile_id=owner_profile_id,
        upload=_upload(),
    )

    assert replacement.id != current.id
    assert replacement.owner_profile_id == owner_profile_id
    assert replacement.status == ResumeStatus.PARSED
    assert replacement.deleted_at is None

    assert current.status == ResumeStatus.DELETED
    assert current.deleted_at is not None
    assert current.deleted_at.tzinfo is not None

    parser.parse.assert_called_once_with(_upload().content)
    resumes.add.assert_awaited_once()
    profiles.add.assert_awaited_once()

    assert session.flush.await_count == 2
    assert session.commit.await_count == 3
    session.rollback.assert_not_awaited()

    uploaded_key = storage.upload.await_args.kwargs["object_key"]

    assert uploaded_key == (f"{owner_profile_id}/{replacement.id}.pdf")
    assert replacement.storage_object_key == uploaded_key

    storage.delete.assert_awaited_once_with(
        object_key=current.storage_object_key,
    )


@pytest.mark.anyio
async def test_replace_candidate_profile_belongs_to_replacement_and_owner() -> None:
    session, storage, parser, resumes, profiles = _dependencies()
    owner_profile_id = uuid4()

    current = Resume(
        id=uuid4(),
        owner_profile_id=owner_profile_id,
        original_filename="old.pdf",
        storage_bucket="resumes",
        storage_object_key=f"{owner_profile_id}/{uuid4()}.pdf",
        content_type="application/pdf",
        size_bytes=10,
        sha256="b" * 64,
        status=ResumeStatus.PARSED,
        parser_version="deterministic-v1",
    )

    resumes.get_owned.return_value = current

    service = ResumeService(
        _settings(),
        storage=storage,
        parser=parser,
        resumes=resumes,
        candidate_profiles=profiles,
    )

    replacement = await service.replace(
        session,
        resume_id=current.id,
        owner_profile_id=owner_profile_id,
        upload=_upload(),
    )

    profile = profiles.add.await_args.args[1]

    assert isinstance(profile, CandidateProfile)
    assert profile.resume_id == replacement.id
    assert profile.owner_profile_id == owner_profile_id
    assert profile.extracted_text == "Candidate resume text"
    assert profile.skills == ["Python", "FastAPI"]


@pytest.mark.anyio
async def test_replace_storage_upload_failure_leaves_old_resume_untouched() -> None:
    session, storage, parser, resumes, profiles = _dependencies()
    owner_profile_id = uuid4()

    current = Resume(
        id=uuid4(),
        owner_profile_id=owner_profile_id,
        original_filename="old.pdf",
        storage_bucket="resumes",
        storage_object_key=f"{owner_profile_id}/{uuid4()}.pdf",
        content_type="application/pdf",
        size_bytes=10,
        sha256="b" * 64,
        status=ResumeStatus.PARSED,
        parser_version="deterministic-v1",
    )

    resumes.get_owned.return_value = current
    storage.upload.side_effect = ResumeStorageError("storage diagnostic")

    service = ResumeService(
        _settings(),
        storage=storage,
        parser=parser,
        resumes=resumes,
        candidate_profiles=profiles,
    )

    with pytest.raises(ApplicationError) as raised:
        await service.replace(
            session,
            resume_id=current.id,
            owner_profile_id=owner_profile_id,
            upload=_upload(),
        )

    assert raised.value.code == "RESUME_STORAGE_UNAVAILABLE"
    assert "diagnostic" not in raised.value.message

    assert current.status == ResumeStatus.PARSED
    assert current.deleted_at is None

    parser.parse.assert_not_called()
    resumes.add.assert_not_awaited()
    profiles.add.assert_not_awaited()
    assert session.commit.await_count == 2
    storage.delete.assert_not_awaited()


@pytest.mark.anyio
async def test_replace_parser_failure_cleans_new_storage_and_keeps_old_resume() -> None:
    session, storage, parser, resumes, profiles = _dependencies()
    owner_profile_id = uuid4()

    current = Resume(
        id=uuid4(),
        owner_profile_id=owner_profile_id,
        original_filename="old.pdf",
        storage_bucket="resumes",
        storage_object_key=f"{owner_profile_id}/{uuid4()}.pdf",
        content_type="application/pdf",
        size_bytes=10,
        sha256="b" * 64,
        status=ResumeStatus.PARSED,
        parser_version="deterministic-v1",
    )

    resumes.get_owned.return_value = current

    parser_error = ApplicationError(
        "RESUME_PDF_INVALID",
        "The resume PDF could not be parsed.",
        status.HTTP_422_UNPROCESSABLE_CONTENT,
    )
    parser.parse.side_effect = parser_error

    service = ResumeService(
        _settings(),
        storage=storage,
        parser=parser,
        resumes=resumes,
        candidate_profiles=profiles,
    )

    with pytest.raises(ApplicationError) as raised:
        await service.replace(
            session,
            resume_id=current.id,
            owner_profile_id=owner_profile_id,
            upload=_upload(),
        )

    assert raised.value is parser_error

    assert current.status == ResumeStatus.PARSED
    assert current.deleted_at is None

    resumes.add.assert_not_awaited()
    profiles.add.assert_not_awaited()
    assert session.commit.await_count == 2

    new_key = storage.upload.await_args.kwargs["object_key"]

    storage.delete.assert_awaited_once_with(
        object_key=new_key,
    )


@pytest.mark.anyio
async def test_replace_database_failure_rolls_back_and_cleans_new_storage() -> None:
    session, storage, parser, resumes, profiles = _dependencies()
    owner_profile_id = uuid4()

    current = Resume(
        id=uuid4(),
        owner_profile_id=owner_profile_id,
        original_filename="old.pdf",
        storage_bucket="resumes",
        storage_object_key=f"{owner_profile_id}/{uuid4()}.pdf",
        content_type="application/pdf",
        size_bytes=10,
        sha256="b" * 64,
        status=ResumeStatus.PARSED,
        parser_version="deterministic-v1",
    )

    resumes.get_owned.return_value = current

    database_error = RuntimeError("database failure")
    session.commit.side_effect = [None, database_error, None]

    service = ResumeService(
        _settings(),
        storage=storage,
        parser=parser,
        resumes=resumes,
        candidate_profiles=profiles,
    )

    with pytest.raises(RuntimeError) as raised:
        await service.replace(
            session,
            resume_id=current.id,
            owner_profile_id=owner_profile_id,
            upload=_upload(),
        )

    assert raised.value is database_error

    session.rollback.assert_awaited_once()

    new_key = storage.upload.await_args.kwargs["object_key"]

    storage.delete.assert_awaited_once_with(
        object_key=new_key,
    )

    assert storage.delete.await_args.kwargs["object_key"] != (current.storage_object_key)


@pytest.mark.anyio
async def test_replace_old_storage_cleanup_failure_does_not_rollback_committed_database() -> None:
    session, storage, parser, resumes, profiles = _dependencies()
    owner_profile_id = uuid4()

    current = Resume(
        id=uuid4(),
        owner_profile_id=owner_profile_id,
        original_filename="old.pdf",
        storage_bucket="resumes",
        storage_object_key=f"{owner_profile_id}/{uuid4()}.pdf",
        content_type="application/pdf",
        size_bytes=10,
        sha256="b" * 64,
        status=ResumeStatus.PARSED,
        parser_version="deterministic-v1",
    )

    resumes.get_owned.return_value = current
    storage.delete.side_effect = ResumeStorageError("storage cleanup diagnostic")

    service = ResumeService(
        _settings(),
        storage=storage,
        parser=parser,
        resumes=resumes,
        candidate_profiles=profiles,
    )

    with pytest.raises(ApplicationError) as raised:
        await service.replace(
            session,
            resume_id=current.id,
            owner_profile_id=owner_profile_id,
            upload=_upload(),
        )

    assert raised.value.code == "RESUME_STORAGE_UNAVAILABLE"
    assert raised.value.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert "diagnostic" not in raised.value.message

    assert current.status == ResumeStatus.DELETED
    assert current.deleted_at is not None

    assert session.commit.await_count == 2
    session.rollback.assert_not_awaited()

    storage.delete.assert_awaited_once_with(
        object_key=current.storage_object_key,
    )


@pytest.mark.anyio
async def test_list_owned_returns_owner_scoped_page() -> None:
    session, storage, parser, resumes, profiles = _dependencies()
    owner_profile_id = uuid4()

    resume = MagicMock(spec=Resume)
    resumes.list_owned_page.return_value = ([resume], 1)

    service = ResumeService(
        _settings(),
        storage=storage,
        parser=parser,
        resumes=resumes,
        candidate_profiles=profiles,
    )

    items, total = await service.list_owned(
        session,
        owner_profile_id=owner_profile_id,
        offset=10,
        limit=25,
    )

    assert items == [resume]
    assert total == 1

    resumes.list_owned_page.assert_awaited_once_with(
        session,
        owner_profile_id=owner_profile_id,
        offset=10,
        limit=25,
    )

    storage.upload.assert_not_awaited()
    storage.delete.assert_not_awaited()
    parser.parse.assert_not_called()


@pytest.mark.anyio
async def test_get_candidate_profile_returns_owned_profile() -> None:
    session, storage, parser, resumes, profiles = _dependencies()
    owner_profile_id = uuid4()
    resume_id = uuid4()

    resume = MagicMock(spec=Resume)
    profile = MagicMock(spec=CandidateProfile)

    resumes.get_owned.return_value = resume
    profiles.get_owned_by_resume_id.return_value = profile

    service = ResumeService(
        _settings(),
        storage=storage,
        parser=parser,
        resumes=resumes,
        candidate_profiles=profiles,
    )

    result = await service.get_candidate_profile(
        session,
        resume_id=resume_id,
        owner_profile_id=owner_profile_id,
    )

    assert result is profile

    resumes.get_owned.assert_awaited_once_with(
        session,
        resume_id=resume_id,
        owner_profile_id=owner_profile_id,
    )
    profiles.get_owned_by_resume_id.assert_awaited_once_with(
        session,
        resume_id=resume_id,
        owner_profile_id=owner_profile_id,
    )


@pytest.mark.anyio
async def test_get_candidate_profile_rejects_missing_or_unowned_resume() -> None:
    session, storage, parser, resumes, profiles = _dependencies()
    owner_profile_id = uuid4()
    resume_id = uuid4()

    resumes.get_owned.return_value = None

    service = ResumeService(
        _settings(),
        storage=storage,
        parser=parser,
        resumes=resumes,
        candidate_profiles=profiles,
    )

    with pytest.raises(ApplicationError) as exc_info:
        await service.get_candidate_profile(
            session,
            resume_id=resume_id,
            owner_profile_id=owner_profile_id,
        )

    assert exc_info.value.code == "NOT_FOUND"
    assert exc_info.value.status_code == 404

    profiles.get_owned_by_resume_id.assert_not_awaited()


@pytest.mark.anyio
async def test_get_candidate_profile_rejects_missing_profile() -> None:
    session, storage, parser, resumes, profiles = _dependencies()
    owner_profile_id = uuid4()
    resume_id = uuid4()

    resumes.get_owned.return_value = MagicMock(spec=Resume)
    profiles.get_owned_by_resume_id.return_value = None

    service = ResumeService(
        _settings(),
        storage=storage,
        parser=parser,
        resumes=resumes,
        candidate_profiles=profiles,
    )

    with pytest.raises(ApplicationError) as exc_info:
        await service.get_candidate_profile(
            session,
            resume_id=resume_id,
            owner_profile_id=owner_profile_id,
        )

    assert exc_info.value.code == "NOT_FOUND"
    assert exc_info.value.status_code == 404

    profiles.get_owned_by_resume_id.assert_awaited_once_with(
        session,
        resume_id=resume_id,
        owner_profile_id=owner_profile_id,
    )


@pytest.mark.anyio
async def test_unexpected_parser_failure_returns_safe_error_and_compensates_storage() -> None:
    session, storage, parser, resumes, profiles = _dependencies()
    parse_executor = AsyncMock(spec=ResumeParseExecutor)
    parse_executor.parse.side_effect = ResumeParserExecutionError("private parser detail")
    cleanups = AsyncMock(spec=ResumeStorageCleanupRepository)
    service = ResumeService(
        _settings(),
        storage=storage,
        parser=parser,
        parse_executor=parse_executor,
        resumes=resumes,
        candidate_profiles=profiles,
        storage_cleanups=cleanups,
    )

    with pytest.raises(ApplicationError) as raised:
        await service.upload(session, owner_profile_id=uuid4(), upload=_upload())

    assert raised.value.code == "RESUME_PARSER_UNAVAILABLE"
    assert raised.value.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert "private parser detail" not in raised.value.message
    storage.delete.assert_awaited_once()
    cleanups.remove.assert_awaited_once()
    session.rollback.assert_awaited_once()


@pytest.mark.anyio
async def test_replace_optimistic_lock_conflict_returns_409_and_removes_new_object() -> None:
    session, storage, parser, resumes, profiles = _dependencies()
    owner_profile_id = uuid4()
    current = Resume(
        id=uuid4(),
        owner_profile_id=owner_profile_id,
        original_filename="old.pdf",
        storage_bucket="resumes",
        storage_object_key=f"{owner_profile_id}/{uuid4()}.pdf",
        content_type="application/pdf",
        size_bytes=10,
        sha256="b" * 64,
        status=ResumeStatus.PARSED,
        parser_version="deterministic-v1",
    )
    resumes.get_owned.return_value = current
    session.flush.side_effect = [None, StaleDataError("concurrent update")]
    cleanups = AsyncMock(spec=ResumeStorageCleanupRepository)
    service = ResumeService(
        _settings(),
        storage=storage,
        parser=parser,
        resumes=resumes,
        candidate_profiles=profiles,
        storage_cleanups=cleanups,
    )

    with pytest.raises(ApplicationError) as raised:
        await service.replace(
            session,
            resume_id=current.id,
            owner_profile_id=owner_profile_id,
            upload=_upload(),
        )

    assert raised.value.code == "CONFLICT"
    assert raised.value.status_code == status.HTTP_409_CONFLICT
    session.rollback.assert_awaited_once()
    replacement_key = storage.upload.await_args.kwargs["object_key"]
    storage.delete.assert_awaited_once_with(object_key=replacement_key)


@pytest.mark.anyio
async def test_reconcile_storage_cleanups_removes_successes_and_records_failures() -> None:
    session, storage, parser, resumes, profiles = _dependencies()
    cleanups = AsyncMock(spec=ResumeStorageCleanupRepository)
    successful = ResumeStorageCleanup(
        owner_profile_id=uuid4(),
        storage_bucket="resumes",
        storage_object_key="owner/success.pdf",
        available_at=datetime.now(UTC),
        attempts=0,
    )
    failed = ResumeStorageCleanup(
        owner_profile_id=uuid4(),
        storage_bucket="resumes",
        storage_object_key="owner/failure.pdf",
        available_at=datetime.now(UTC),
        attempts=0,
    )
    cleanups.list_due_for_update.return_value = [successful, failed]
    storage.delete.side_effect = [None, ResumeStorageError("private provider detail")]
    service = ResumeService(
        _settings(),
        storage=storage,
        parser=parser,
        resumes=resumes,
        candidate_profiles=profiles,
        storage_cleanups=cleanups,
    )

    removed, failures = await service.reconcile_storage_cleanups(session, limit=2)

    assert (removed, failures) == (1, 1)
    cleanups.remove.assert_awaited_once_with(session, successful)
    assert failed.attempts == 1
    assert failed.last_error_code == "RESUME_STORAGE_UNAVAILABLE"
    session.commit.assert_awaited_once()
