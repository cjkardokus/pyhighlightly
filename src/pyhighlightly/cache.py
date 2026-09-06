"""Response caching for the pyhighlightly client.

``CacheBackend`` is a public extension point, in the same spirit as
``HighlightlyBaseClient`` itself: a consuming project can plug in its own
backend (a Redis-backed cache, for instance) by satisfying this ``Protocol``
alone, without importing anything else from pyhighlightly. Structural typing
means a class doesn't even need to inherit from ``CacheBackend`` to count --
implementing ``get``/``set``/``delete`` with matching signatures is enough --
but it's provided as an explicit base too, for anyone who wants the
nominal-subtyping clarity (or a runtime ``isinstance`` check, since it's
``@runtime_checkable``).

``InMemoryCache`` is the default backend: simple, dependency-free, good
enough for a single long-lived process (a script, a notebook, a single
Airflow worker). It is not shared across processes and has no size limit --
a consuming project that needs either of those should supply its own
``CacheBackend``.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class CacheBackend(Protocol):
    """The interface a cache backend must satisfy to plug into a client.

    Cached values are already-parsed pydantic models (or plain lists of
    them) -- whatever an endpoint method returns -- not raw JSON, so a
    backend that serializes entries (e.g. to store them outside the
    process) is responsible for handling that itself.
    """

    def get(self, key: str) -> Any | None:
        """Return the cached value for ``key``, or ``None`` if absent or expired."""
        ...

    def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        """Store ``value`` under ``key``, to expire after ``ttl_seconds`` seconds."""
        ...

    def delete(self, key: str) -> None:
        """Remove any cached value for ``key``. A no-op if there isn't one."""
        ...


class InMemoryCache(CacheBackend):
    """The default ``CacheBackend``: an in-process dict with per-entry expiry.

    No size limit and no LRU eviction -- deliberately simple. Entries are
    only ever removed by expiring (checked lazily, on ``get``) or by an
    explicit ``delete``.
    """

    def __init__(self, now_fn: Callable[[], datetime] | None = None) -> None:
        """``now_fn`` is an override point for tests, mirroring
        ``HighlightlyBaseClient._now()``; it defaults to the real current
        UTC time.
        """
        self._now = now_fn or (lambda: datetime.now(timezone.utc))
        self._entries: dict[str, tuple[Any, datetime]] = {}

    def get(self, key: str) -> Any | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if self._now() >= expires_at:
            del self._entries[key]
            return None
        return value

    def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        self._entries[key] = (value, self._now() + timedelta(seconds=ttl_seconds))

    def delete(self, key: str) -> None:
        self._entries.pop(key, None)
