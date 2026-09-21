"""Unit tests for mandatory owner-scoped resume repositories."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from app.domain.resumes import CandidateProfile, Resume, ResumeStorageCleanup
from app.repositories.resumes import (
    CandidateProfileRepository,
    ResumeRepository,
    ResumeStorageCleanupRepository,
)


def _statement_text(statement: Select[Any]) -> str:
    return str(statement).lower()


def _statement_parameters(statement: Select[Any]) -> Sequence[object]:
    compiled = statement.compile()
    return tuple(compiled.params.values())


def _mock_session() -> AsyncMock:
    return AsyncMock(spec=AsyncSession)


@pytest.mark.anyio
async def test_get_owned_scopes_by_resume_and_owner() -> None:
    session = _mock_session()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    session.execute.return_value = result

    resume_id = uuid4()
    owner_profile_id = uuid4()

    repository = ResumeRepository()

    found = await repository.get_owned(
        session,
        resume_id=resume_id,
        owner_profile_id=owner_profile_id,
    )

    assert found is None

    statement = session.execute.await_args.args[0]
    text = _statement_text(statement)
    parameters = _statement_parameters(statement)

    assert "resumes.id" in text
    assert "resumes.owner_profile_id" in text
    assert "resumes.status" in text
    assert resume_id in parameters
    assert owner_profile_id in parameters


@pytest.mark.anyio
async def test_get_owned_can_explicitly_include_deleted() -> None:
    session = _mock_session()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    session.execute.return_value = result

    resume_id = uuid4()
    owner_profile_id = uuid4()

    repository = ResumeRepository()

    await repository.get_owned(
        session,
        resume_id=resume_id,
        owner_profile_id=owner_profile_id,
        include_deleted=True,
    )

    statement = session.execute.await_args.args[0]
    text = _statement_text(statement)
    parameters = _statement_parameters(statement)

    assert "resumes.id" in text
    assert "resumes.owner_profile_id" in text
    assert "resumes.status !=" not in text
    assert resume_id in parameters
    assert owner_profile_id in parameters


@pytest.mark.anyio
async def test_get_owned_by_sha256_requires_owner_scope() -> None:
    session = _mock_session()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    session.execute.return_value = result

    owner_profile_id = uuid4()
    digest = "a" * 64

    repository = ResumeRepository()

    await repository.get_owned_by_sha256(
        session,
        owner_profile_id=owner_profile_id,
        sha256=digest,
    )

    statement = session.execute.await_args.args[0]
    text = _statement_text(statement)
    parameters = _statement_parameters(statement)

    assert "resumes.owner_profile_id" in text
    assert "resumes.sha256" in text
    assert "resumes.status" in text
    assert owner_profile_id in parameters
    assert digest in parameters


@pytest.mark.anyio
async def test_list_owned_page_scopes_rows_and_count_to_owner() -> None:
    session = _mock_session()
    owner_profile_id = uuid4()

    scalar_rows = MagicMock()
    scalar_rows.__iter__.return_value = iter([])
    session.scalars.return_value = scalar_rows
    session.scalar.return_value = 0

    repository = ResumeRepository()

    items, total = await repository.list_owned_page(
        session,
        owner_profile_id=owner_profile_id,
        offset=0,
        limit=20,
    )

    assert items == []
    assert total == 0

    rows_statement = session.scalars.await_args.args[0]
    count_statement = session.scalar.await_args.args[0]

    rows_text = _statement_text(rows_statement)
    count_text = _statement_text(count_statement)

    assert "resumes.owner_profile_id" in rows_text
    assert "resumes.status" in rows_text
    assert "resumes.owner_profile_id" in count_text
    assert "resumes.status" in count_text

    assert owner_profile_id in _statement_parameters(rows_statement)
    assert owner_profile_id in _statement_parameters(count_statement)


@pytest.mark.anyio
async def test_candidate_profile_lookup_requires_resume_and_owner() -> None:
    session = _mock_session()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    session.execute.return_value = result

    resume_id = uuid4()
    owner_profile_id = uuid4()

    repository = CandidateProfileRepository()

    found = await repository.get_owned_by_resume_id(
        session,
        resume_id=resume_id,
        owner_profile_id=owner_profile_id,
    )

    assert found is None

    statement = session.execute.await_args.args[0]
    text = _statement_text(statement)
    parameters = _statement_parameters(statement)

    assert "candidate_profiles.resume_id" in text
    assert "candidate_profiles.owner_profile_id" in text
    assert resume_id in parameters
    assert owner_profile_id in parameters


@pytest.mark.anyio
async def test_resume_add_stages_supplied_model() -> None:
    session = _mock_session()
    repository = ResumeRepository()

    resume = MagicMock(spec=Resume)

    await repository.add(session, resume)

    session.add.assert_called_once_with(resume)


@pytest.mark.anyio
async def test_candidate_profile_add_stages_supplied_model() -> None:
    session = _mock_session()
    repository = CandidateProfileRepository()

    profile = MagicMock(spec=CandidateProfile)

    await repository.add(session, profile)

    session.add.assert_called_once_with(profile)


@pytest.mark.anyio
async def test_cleanup_batch_is_due_ordered_bounded_and_locked() -> None:
    session = _mock_session()
    rows = MagicMock()
    rows.__iter__.return_value = iter([])
    session.scalars.return_value = rows

    result = await ResumeStorageCleanupRepository().list_due_for_update(
        session,
        now=datetime.now(UTC),
        limit=25,
    )

    assert result == []
    statement = session.scalars.await_args.args[0]
    statement_text = str(
        statement.compile(dialect=postgresql.dialect())  # type: ignore[no-untyped-call]
    ).lower()
    assert "resume_storage_cleanups.available_at <=" in statement_text
    assert "order by" in statement_text
    assert "limit" in statement_text
    assert "for update" in statement_text
    assert "skip locked" in statement_text


@pytest.mark.anyio
async def test_cleanup_add_and_remove_stage_supplied_model() -> None:
    session = _mock_session()
    repository = ResumeStorageCleanupRepository()
    cleanup = MagicMock(spec=ResumeStorageCleanup)

    await repository.add(session, cleanup)
    await repository.remove(session, cleanup)

    session.add.assert_called_once_with(cleanup)
    session.delete.assert_awaited_once_with(cleanup)


def test_repository_public_lookup_methods_require_owner_argument() -> None:
    """Guard against accidentally making owner scope optional later."""
    import inspect

    resume_repository = ResumeRepository
    candidate_repository = CandidateProfileRepository

    methods = (
        resume_repository.get_owned,
        resume_repository.get_owned_by_sha256,
        resume_repository.list_owned_page,
        candidate_repository.get_owned_by_resume_id,
    )

    for method in methods:
        signature = inspect.signature(method)
        owner = signature.parameters["owner_profile_id"]

        assert owner.default is inspect.Parameter.empty
        assert owner.annotation in {UUID, "UUID"}
