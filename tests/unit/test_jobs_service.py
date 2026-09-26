from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.domain.resumes import CandidateProfile
from app.jobs.matching import Candidate, MatchableJob
from app.jobs.service import JobService


@pytest.fixture
def mock_job_repo() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def mock_candidate_repo() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def job_service(mock_job_repo: AsyncMock, mock_candidate_repo: AsyncMock) -> JobService:
    return JobService(job_repository=mock_job_repo, candidate_repository=mock_candidate_repo)


@pytest.mark.anyio
async def test_search_delegates_to_job_repo(
    job_service: JobService, mock_job_repo: AsyncMock
) -> None:
    session = AsyncMock()
    search_res: tuple[list[MatchableJob], int] = ([], 0)
    mock_job_repo.search.return_value = search_res

    rows, total = await job_service.search(
        session,
        query="python",
        role="engineer",
        location="NY",
        remote=True,
        employment_type="FULL_TIME",
        page=2,
        page_size=10,
    )

    assert rows == []
    assert total == 0
    mock_job_repo.search.assert_called_once_with(
        session,
        query="python",
        role="engineer",
        location="NY",
        remote=True,
        employment_type="FULL_TIME",
        source=None,
        page=2,
        page_size=10,
    )


@pytest.mark.anyio
async def test_get_recommendations_returns_empty_when_no_candidate_profile(
    job_service: JobService, mock_candidate_repo: AsyncMock
) -> None:
    session = AsyncMock()
    owner_id = uuid4()
    mock_candidate_repo.get_latest_owned.return_value = None

    rows, total = await job_service.get_recommendations(session, owner_profile_id=owner_id)

    assert rows == []
    assert total == 0
    mock_candidate_repo.get_latest_owned.assert_called_once_with(
        session,
        owner_profile_id=owner_id,
    )


@pytest.mark.anyio
@patch("app.jobs.service.rank_job")
@patch("app.jobs.service.is_eligible")
async def test_get_recommendations_ranks_and_paginates(
    mock_is_eligible: AsyncMock,
    mock_rank_job: AsyncMock,
    job_service: JobService,
    mock_candidate_repo: AsyncMock,
    mock_job_repo: AsyncMock,
) -> None:
    session = AsyncMock()
    owner_id = uuid4()

    mock_candidate = CandidateProfile(
        id=uuid4(),
        resume_id=uuid4(),
        owner_profile_id=owner_id,
        current_title="Software Engineer",
        years_of_experience=3,
        skills=["python", "pytest"],
    )
    mock_candidate_repo.get_latest_owned.return_value = mock_candidate

    from unittest.mock import MagicMock

    job1 = MagicMock(id=uuid4())
    job2 = MagicMock(id=uuid4())
    job3 = MagicMock(id=uuid4())

    mock_job_repo.search.return_value = ([job1, job2, job3], 3)

    # Only job1 and job2 are eligible
    mock_is_eligible.side_effect = lambda candidate, job: job.id in (job1.id, job2.id)

    # Rank job2 higher than job1
    def fake_rank(candidate: Candidate, job: MatchableJob) -> dict[str, float]:
        if job.id == job1.id:
            return {"match_score": 10.0}
        if job.id == job2.id:
            return {"match_score": 20.0}
        return {"match_score": 0.0}

    mock_rank_job.side_effect = fake_rank

    rows, total = await job_service.get_recommendations(
        session,
        owner_profile_id=owner_id,
        page=1,
        page_size=1,
    )

    assert total == 2  # 2 eligible jobs
    assert len(rows) == 1
    # job2 should be first because it has a higher score
    assert rows[0][0].id == job2.id
    assert rows[0][1] == {"match_score": 20.0}
