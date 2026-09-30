"""Compatibility imports for the collector registry.

New code should import the registry from :mod:`app.jobs.sources.registry`.
"""

from app.jobs.sources.base import JobSourceCollector
from app.jobs.sources.registry import CollectorRegistry, build_collector_registry

__all__ = ["CollectorRegistry", "JobSourceCollector", "build_collector_registry"]
