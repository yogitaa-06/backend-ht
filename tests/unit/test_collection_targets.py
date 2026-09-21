import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.domain.jobs import JobSource
from app.jobs.registry import CollectorRegistry
from app.jobs.targets import DEFAULT_ROLE_QUERIES, CollectionTarget


class FakeCollector:
    source = JobSource.DICE

    async def collect(self, target: CollectionTarget) -> list[object]:
        del target
        return []


def test_default_targets_cover_required_roles() -> None:
    settings = Settings(_env_file=None)

    assert {target.query for target in settings.job_collection_targets} == set(DEFAULT_ROLE_QUERIES)
    assert all(target.source is JobSource.DICE for target in settings.job_collection_targets)


def test_target_normalizes_text_and_has_stable_identity() -> None:
    target = CollectionTarget(
        source=JobSource.DICE,
        query="  DevOps   Engineer ",
        location=" United   States ",
    )

    assert target.query == "DevOps Engineer"
    assert target.location == "United States"
    assert target.identity == target.model_copy().identity
    assert not hasattr(target, "user_id")


def test_target_rejects_unknown_or_blank_fields() -> None:
    with pytest.raises(ValidationError):
        CollectionTarget(source=JobSource.DICE, query=" ")
    with pytest.raises(ValidationError):
        CollectionTarget(source=JobSource.DICE, query="DevOps", user_id="unsafe")  # type: ignore[call-arg]


def test_registry_resolves_registered_collector_and_rejects_duplicates() -> None:
    registry = CollectorRegistry()
    collector = FakeCollector()
    registry.register(collector)

    assert registry.resolve(JobSource.DICE) is collector
    assert registry.is_registered(JobSource.DICE)
    with pytest.raises(ValueError, match="already registered"):
        registry.register(collector)


def test_registry_reports_unregistered_source() -> None:
    registry = CollectorRegistry()

    with pytest.raises(Exception, match="no collector is registered"):
        registry.resolve(JobSource.LINKEDIN)
