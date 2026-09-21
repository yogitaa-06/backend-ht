"""Stable collection errors used to make retry policy explicit."""


class CollectionError(Exception):
    """Base error for collection orchestration."""


class SourceUnavailableError(CollectionError):
    """The requested source has no registered collector."""


class PermanentCollectionError(CollectionError):
    """A configuration or source request cannot succeed through retrying."""


class TemporaryCollectionError(CollectionError):
    """A transient source failure may succeed after bounded backoff."""

    def __init__(self, message: str, *, retry_after_seconds: int = 30) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class SourceRateLimitedError(TemporaryCollectionError):
    """A source requested slower collection."""


class SourceBlockedError(TemporaryCollectionError):
    """A source temporarily blocked collection traffic."""
