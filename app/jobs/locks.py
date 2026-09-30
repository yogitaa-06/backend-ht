"""Compatibility imports for collection locking."""

from app.queue.locks import (
    CollectionLease,
    CollectionLockManager,
    RedisCollectionLease,
    RedisCollectionLockManager,
)

__all__ = [
    "CollectionLease",
    "CollectionLockManager",
    "RedisCollectionLease",
    "RedisCollectionLockManager",
]
