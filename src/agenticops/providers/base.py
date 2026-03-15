"""Cloud provider abstraction layer.

Defines the CloudProvider ABC and a thread-safe registry with session caching.
Session cache entries expire after TTL (default 50 min, under STS 1h limit).
"""

from __future__ import annotations

import logging
import threading
import time
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)

# Default session cache TTL: 50 minutes (STS tokens expire at 60 min)
_DEFAULT_TTL_SECONDS = 50 * 60


class CloudProvider(ABC):
    """Abstract base class for cloud providers."""

    # Subclasses must set this
    provider_name: str = ""

    def __init__(self, account_id: int, credentials: dict, regions: list[str] | None = None):
        self.account_id = account_id
        self._credentials = credentials
        self.regions = regions or []

    @abstractmethod
    def get_session(self, region: str | None = None) -> Any:
        """Return an authenticated cloud SDK session/client for the given region."""

    @abstractmethod
    def validate_credentials(self) -> bool:
        """Validate that the stored credentials are still functional.

        Returns True if credentials work, False otherwise.
        """

    @abstractmethod
    def list_resources(self, region: str, resource_type: str) -> list[dict]:
        """List resources of a given type in a region.

        Returns list of dicts with at minimum: resource_id, name, status.
        """


# ---------------------------------------------------------------------------
# Session cache with TTL
# ---------------------------------------------------------------------------

class _CacheEntry:
    __slots__ = ("session", "expires_at")

    def __init__(self, session: Any, ttl: float):
        self.session = session
        self.expires_at = time.monotonic() + ttl


class SessionCache:
    """Thread-safe session cache with per-entry TTL expiry."""

    def __init__(self, ttl_seconds: float = _DEFAULT_TTL_SECONDS):
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._cache: dict[str, _CacheEntry] = {}

    def get(self, key: str) -> Any | None:
        """Get a cached session, or None if missing/expired."""
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            if time.monotonic() > entry.expires_at:
                del self._cache[key]
                return None
            return entry.session

    def put(self, key: str, session: Any) -> None:
        """Cache a session with TTL."""
        with self._lock:
            self._cache[key] = _CacheEntry(session, self._ttl)

    def invalidate(self, key: str) -> None:
        """Remove a specific entry."""
        with self._lock:
            self._cache.pop(key, None)

    def clear(self) -> None:
        """Clear all entries."""
        with self._lock:
            self._cache.clear()

    def prune_expired(self) -> int:
        """Remove all expired entries. Returns count removed."""
        now = time.monotonic()
        with self._lock:
            expired = [k for k, v in self._cache.items() if now > v.expires_at]
            for k in expired:
                del self._cache[k]
            return len(expired)

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._cache)


# ---------------------------------------------------------------------------
# Provider registry
# ---------------------------------------------------------------------------

_registry_lock = threading.Lock()
_registry: dict[str, type[CloudProvider]] = {}


def register_provider(cls: type[CloudProvider]) -> type[CloudProvider]:
    """Decorator to register a CloudProvider subclass."""
    name = cls.provider_name
    if not name:
        raise ValueError(f"{cls.__name__} must set provider_name")
    with _registry_lock:
        if name in _registry:
            logger.warning("Overwriting provider registration: %s", name)
        _registry[name] = cls
    return cls


def get_provider_class(name: str) -> type[CloudProvider] | None:
    """Look up a registered provider class by name."""
    with _registry_lock:
        return _registry.get(name)


def registered_providers() -> list[str]:
    """Return list of registered provider names."""
    with _registry_lock:
        return list(_registry.keys())
