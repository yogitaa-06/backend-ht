"""Public contract implemented by every source integration."""

from typing import Protocol, runtime_checkable

from app.domain.jobs import JobSource


@runtime_checkable
class JobSourceCollector(Protocol):
    """Registered source adapter discovered by the collection coordinator."""

    source: JobSource
