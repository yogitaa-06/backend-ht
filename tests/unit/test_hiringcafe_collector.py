"""Unit tests for the HiringCafe global-job collector."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domain.jobs import JobSource
from app.jobs.errors import SourceBlockedError
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


class MockLink:
    def __init__(self, href):
        self.href = href
    async def get_attribute(self, attr):
        return self.href

class MockLocator:
    def __init__(self, links):
        self.links = links
    async def all(self):
        return self.links

class MockPage:
    def __init__(self, links=None, title_val="Title at Co"):
        self.links = links or []
        self.title_val = title_val
    async def goto(self, url, **kwargs):
        res = MagicMock()
        res.status = 200
        return res
    async def evaluate(self, script):
        return "Normal text"
    def locator(self, sel):
        return MockLocator(self.links)
    async def title(self):
        return self.title_val
    async def wait_for_timeout(self, ms):
        pass
    async def close(self):
        pass

class MockContext:
    def __init__(self, search_page, job_pages):
        self.pages = [search_page] + job_pages
        self.idx = 0
    async def new_page(self):
        if self.idx < len(self.pages):
            p = self.pages[self.idx]
            self.idx += 1
            return p
        return MockPage()
    async def close(self):
        pass

class MockBrowser:
    def __init__(self, context):
        self.context = context
    async def new_context(self, **kwargs):
        return self.context
    async def close(self):
        pass

class MockPlaywright:
    def __init__(self, browser):
        self.chromium = MagicMock()
        self.chromium.launch = AsyncMock(return_value=browser)
    async def __aenter__(self):
        return self
    async def __aexit__(self, *args):
        pass


@pytest.mark.anyio
@patch("app.jobs.sources.hiringcafe.async_playwright")
async def test_hiringcafe_collector_respects_max_jobs(mock_pw) -> None:
    links = [MockLink(f"/job/software-engineer-{i}") for i in range(5)]
    search_page = MockPage(links=links)
    job_page = MockPage(title_val="Software Engineer at Mock Co — New York, NY")
    
    ctx = MockContext(search_page, [job_page, job_page, job_page, job_page, job_page])
    browser = MockBrowser(ctx)
    mock_pw.return_value = MockPlaywright(browser)
    
    collector = HiringCafeCollector()
    target = _target(max_jobs=2)
    jobs = await collector.collect(target)
    
    # Even though 5 links were found, only 2 should be returned
    assert len(jobs) == 2
    assert jobs[0].external_job_id == "0"
    assert jobs[1].external_job_id == "1"


@pytest.mark.anyio
@patch("app.jobs.sources.hiringcafe.async_playwright")
async def test_hiringcafe_collector_stable_external_job_id(mock_pw) -> None:
    links = [MockLink("/job/software-engineer-some-company-location-s49f4qknvosl8nko")]
    search_page = MockPage(links=links)
    job_page = MockPage(title_val="Job Title at Some Co")
    
    ctx = MockContext(search_page, [job_page])
    browser = MockBrowser(ctx)
    mock_pw.return_value = MockPlaywright(browser)
    
    collector = HiringCafeCollector()
    jobs = await collector.collect(_target(max_jobs=1))
    
    assert len(jobs) == 1
    # Extract the stable hash part
    assert jobs[0].external_job_id == "s49f4qknvosl8nko"


@pytest.mark.anyio
@patch("app.jobs.sources.hiringcafe.async_playwright")
async def test_hiringcafe_collector_extracts_title_company_location_url(mock_pw) -> None:
    links = [MockLink("/job/test-123")]
    search_page = MockPage(links=links)
    # Format: "Title at Company — Location | HiringCafe"
    job_page = MockPage(title_val="Senior Software Engineer at ACME Corp — San Francisco, CA | HiringCafe")
    
    ctx = MockContext(search_page, [job_page])
    browser = MockBrowser(ctx)
    mock_pw.return_value = MockPlaywright(browser)
    
    collector = HiringCafeCollector()
    jobs = await collector.collect(_target(max_jobs=1))
    
    assert len(jobs) == 1
    assert jobs[0].title == "Senior Software Engineer"
    assert jobs[0].company == "ACME Corp"
    assert jobs[0].location == "San Francisco, CA"
    assert jobs[0].url == "https://hiringcafe.com/job/test-123"


@pytest.mark.anyio
@patch("app.jobs.sources.hiringcafe.async_playwright")
async def test_hiringcafe_collector_handles_malformed_job(mock_pw) -> None:
    links = [MockLink("/job/test-123")]
    search_page = MockPage(links=links)
    job_page = MockPage(title_val="Just a job title")
    
    ctx = MockContext(search_page, [job_page])
    browser = MockBrowser(ctx)
    mock_pw.return_value = MockPlaywright(browser)
    
    collector = HiringCafeCollector()
    jobs = await collector.collect(_target(max_jobs=1))
    
    assert len(jobs) == 1
    assert jobs[0].title == "Unknown Title"
    assert jobs[0].company == "Unknown Company"
    assert jobs[0].location == "Unknown Location"


@pytest.mark.anyio
@patch("app.jobs.sources.hiringcafe.async_playwright")
async def test_hiringcafe_collector_handles_duplicate_discovery(mock_pw) -> None:
    links = [MockLink("/job/test-123"), MockLink("/job/test-123")]
    search_page = MockPage(links=links)
    job_page = MockPage(title_val="Title at Co")
    
    ctx = MockContext(search_page, [job_page, job_page])
    browser = MockBrowser(ctx)
    mock_pw.return_value = MockPlaywright(browser)
    
    collector = HiringCafeCollector()
    jobs = await collector.collect(_target(max_jobs=2))
    
    assert len(jobs) == 1


def test_hiringcafe_collector_is_registered() -> None:
    registry = build_collector_registry()
    assert registry.is_registered(JobSource.HIRINGCAFE)
