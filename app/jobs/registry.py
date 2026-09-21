"""Collector interface and explicit source registry."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from app.domain.jobs import JobSource
from app.jobs.errors import SourceUnavailableError
from app.jobs.normalization import RawSourceJob
from app.jobs.targets import CollectionTarget


@runtime_checkable
class JobSourceCollector(Protocol):
    """Small source adapter contract; implementations arrive in later checkpoints."""

    source: JobSource

    async def collect(self, target: CollectionTarget) -> Sequence[RawSourceJob]: ...


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
    """Build the worker registry; Checkpoint 3 will register Dice here."""
    return CollectorRegistry()
