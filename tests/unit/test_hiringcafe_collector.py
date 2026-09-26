"""Unit tests for the HiringCafe global-job collector."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domain.jobs import JobSource
from app.jobs.registry import build_collector_registry
from app.jobs.sources.hiringcafe import HiringCafeCollector
from app.jobs.targets import CollectionTarget


def _target(max_jobs: int = 10) -> CollectionTarget:
    return CollectionTarget(
        source=JobSource.HIRINGCAFE,
        query="Software Engineer",
        location="United States",
        max_jobs=max_jobs,
    )


def create_fake_next_data(hits: list[dict[str, Any]]) -> str:
    return json.dumps({"props": {"pageProps": {"ssrHits": hits}}})


class MockPage:
    def __init__(
        self,
        next_data_hits: list[dict[str, Any]] | None = None,
        page_text: str = "Normal content",
    ) -> None:
        self.next_data_hits = next_data_hits if next_data_hits is not None else []
        self.page_text = page_text

    async def goto(self, url: str, **kwargs: Any) -> MagicMock:
        res = MagicMock()
        res.status = 200
        return res

    async def evaluate(self, script: str) -> Any:
        if "__NEXT_DATA__" in script:
            if self.next_data_hits is None:
                raise Exception("Element not found")
            return create_fake_next_data(self.next_data_hits)
        return self.page_text

    async def wait_for_timeout(self, ms: int | float) -> None:
        pass

    async def close(self) -> None:
        pass

    def locator(self, *args: Any, **kwargs: Any) -> AsyncMock:
        return AsyncMock()


class MockContext:
    def __init__(self, search_page: MockPage) -> None:
        self.page = search_page

    async def new_page(self) -> MockPage:
        return self.page

    async def close(self) -> None:
        pass


class MockBrowser:
    def __init__(self, context: MockContext) -> None:
        self.context = context

    async def new_context(self, **kwargs: Any) -> MockContext:
        return self.context

    async def close(self) -> None:
        pass


class MockPlaywright:
    def __init__(self, browser: MockBrowser) -> None:
        self.chromium = MagicMock()
        self.chromium.launch = AsyncMock(return_value=browser)

    async def __aenter__(self) -> MockPlaywright:
        return self

    async def __aexit__(self, *args: Any) -> None:
        pass


@pytest.mark.anyio
@patch("app.jobs.sources.hiringcafe.async_playwright")
async def test_hiringcafe_collector_respects_max_jobs(mock_pw: MagicMock) -> None:
    hits = [{"id": f"job-{i}", "job_information": {"title": f"Title {i}"}} for i in range(5)]
    search_page = MockPage(next_data_hits=hits)

    ctx = MockContext(search_page)
    browser = MockBrowser(ctx)
    mock_pw.return_value = MockPlaywright(browser)

    collector = HiringCafeCollector()
    target = _target(max_jobs=2)
    jobs = await collector.collect(target)

    assert len(jobs) == 2
    assert jobs[0].external_job_id == "job-0"
    assert jobs[1].external_job_id == "job-1"


@pytest.mark.anyio
@patch("app.jobs.sources.hiringcafe.async_playwright")
async def test_hiringcafe_collector_extracts_all_fields(mock_pw: MagicMock) -> None:
    hits = [
        {
            "id": "test-123",
            "apply_url": "https://company.com/jobs/123",
            "job_information": {"title": "Senior Software Engineer"},
            "v5_processed_job_data": {
                "company_name": "ACME Corp",
                "formatted_workplace_location": "San Francisco, CA",
                "commitment": ["Full Time"],
                "technical_tools": ["Python", "FastAPI"],
                "requirements_summary": "Must know Python.",
                "role_activities": ["Write code", "Review PRs"],
                "estimated_publish_date_millis": 1700000000000,
            },
        }
    ]
    search_page = MockPage(next_data_hits=hits)

    ctx = MockContext(search_page)
    browser = MockBrowser(ctx)
    mock_pw.return_value = MockPlaywright(browser)

    collector = HiringCafeCollector()
    jobs = await collector.collect(_target(max_jobs=1))

    assert len(jobs) == 1
    assert jobs[0].external_job_id == "test-123"
    assert jobs[0].title == "Senior Software Engineer"
    assert jobs[0].company == "ACME Corp"
    assert jobs[0].location == "San Francisco, CA"
    assert jobs[0].url == "https://company.com/jobs/123"
    assert jobs[0].employment_type == "Full Time"
    assert set(jobs[0].skills) == {"Python", "FastAPI"}
    assert jobs[0].description is not None
    assert "Requirements:\nMust know Python." in jobs[0].description
    assert "Activities:\n- Write code\n- Review PRs" in jobs[0].description
    assert jobs[0].posted_at is not None
    assert jobs[0].posted_at.year == 2023


@pytest.mark.anyio
@patch("app.jobs.sources.hiringcafe.async_playwright")
async def test_hiringcafe_collector_handles_malformed_job(mock_pw: MagicMock) -> None:
    hits: list[dict[str, Any]] = [
        {"v5_processed_job_data": {}},
        {"id": "test-valid", "job_information": {"title": "Valid"}},
    ]
    search_page = MockPage(next_data_hits=hits)

    ctx = MockContext(search_page)
    browser = MockBrowser(ctx)
    mock_pw.return_value = MockPlaywright(browser)

    collector = HiringCafeCollector()
    jobs = await collector.collect(_target(max_jobs=2))

    assert len(jobs) == 1
    assert jobs[0].external_job_id == "test-valid"


def test_hiringcafe_collector_is_registered() -> None:
    registry = build_collector_registry()
    assert registry.is_registered(JobSource.HIRINGCAFE)
