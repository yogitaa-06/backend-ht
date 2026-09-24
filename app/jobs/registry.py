"""Collector interface and explicit source registry."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.domain.jobs import JobSource
from app.jobs.errors import SourceUnavailableError


@runtime_checkable
class JobSourceCollector(Protocol):
    """Registered source adapter; coordinators feature-detect collection methods."""

    source: JobSource


class CollectorRegistry:
    """Process-local mapping of validated source adapters."""

    def __init__(self) -> None:
        self._collectors: dict[JobSource, JobSourceCollector] = {}

    def register(self, collector: JobSourceCollector) -> None:
        if collector.source in self._collectors:
            raise ValueError(f"collector already registered for {collector.source.value}")
        self._collectors[collector.source] = collector

    def resolve(self, source: JobSource) -> JobSourceCollector:
        try:
            return self._collectors[source]
        except KeyError:
            raise SourceUnavailableError(
                f"no collector is registered for source {source.value}"
            ) from None

    def is_registered(self, source: JobSource) -> bool:
        return source in self._collectors

    @property
    def sources(self) -> frozenset[JobSource]:
        return frozenset(self._collectors)


def build_collector_registry() -> CollectorRegistry:
    """Build the worker registry with implemented source collectors."""
    from app.jobs.sources.dice import DiceCollector
    from app.jobs.sources.glassdoor import GlassdoorCollector
    from app.jobs.sources.linkedin import LinkedInCollector

    registry = CollectorRegistry()
    registry.register(DiceCollector())
    registry.register(LinkedInCollector())
    registry.register(GlassdoorCollector())
    return registry
