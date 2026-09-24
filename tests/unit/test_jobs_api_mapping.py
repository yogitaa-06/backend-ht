from datetime import UTC, datetime
from uuid import uuid4

from app.api.v1.routes.jobs import _response
from app.repositories.canonical_jobs import CanonicalJobRead


def test_job_response_serializes_complete_canonical_metadata() -> None:
    observed_at = datetime(2026, 9, 24, tzinfo=UTC)
    posted_at = datetime(2026, 9, 11, 14, 32, 19, tzinfo=UTC)
    row = CanonicalJobRead(
        id=uuid4(),
        source="dice",
        external_job_id="detail-1",
        job_title="Senior Security Engineer",
        role_family="security",
        company="Example Corp",
        location="New York, NY, US",
        job_url="https://www.dice.com/job-detail/detail-1",
        description="Protect services.",
        salary_text="USD 150000 per year",
        employment_type="FULL_TIME",
        remote=False,
        skills=["aws", "python"],
        posted_at=posted_at,
        source_updated_at=posted_at,
        first_seen_at=observed_at,
        last_seen_at=observed_at,
        scraped_at=observed_at,
        experience_min_years=5,
        experience_max_years=None,
        experience_text="5+ years",
        is_active=True,
    )

    response = _response(row)

    assert response.company == "Example Corp"
    assert response.location == "New York, NY, US"
    assert response.description == "Protect services."
    assert response.employment_type == "FULL_TIME"
    assert response.remote is False
    assert response.skills == ["aws", "python"]
    assert response.posted_at == posted_at
    assert response.source_updated_at == posted_at
    assert response.first_seen_at == observed_at
    assert response.last_seen_at == observed_at
    assert response.scraped_at == observed_at
