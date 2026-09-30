"""Source-independent job ingestion pipeline."""

from app.jobs.ingestion.service import (
    CanonicalJobIngestionService,
    IngestionAction,
    IngestionResult,
)

__all__ = ["CanonicalJobIngestionService", "IngestionAction", "IngestionResult"]
