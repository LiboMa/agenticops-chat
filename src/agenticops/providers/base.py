"""CloudProvider ABC, provider registry, and session cache."""

from __future__ import annotations

import logging
import threading
from abc import ABC, abstractmethod
from typing import Any, Callable

logger = logging.getLogger(__name__)

# ── Session cache (thread-safe) ────────────────────────────────────

_session_cache: dict[str, Any] = {}
_session_lock = threading.Lock()


def get_cached_session(key: str) -> Any | None:
    """Get a cached session by key. Key format: '{provider}:{account_id}:{region}'."""
    with _session_lock:
        return _session_cache.get(key)


def set_cached_session(key: str, session: Any) -> None:
    """Cache a session. Key format: '{provider}:{account_id}:{region}'."""
    with _session_lock:
        _session_cache[key] = session


def clear_session_cache() -> None:
    """Clear all cached sessions."""
    with _session_lock:
        _session_cache.clear()


# ── CloudProvider ABC ───────────────────────────────────────────────


class CloudProvider(ABC):
    """Base class for all cloud providers."""

    def __init__(self, account: Any) -> None:
        self.account = account

    @abstractmethod
    def resolve_credentials(self) -> bool:
        """Resolve and validate credentials. Returns True if successful."""
        ...

    @abstractmethod
    def cli_tool(self) -> Callable:
        """Return a callable that executes the provider's CLI commands."""
        ...

    @abstractmethod
    def sdk_session(self) -> Any:
        """Return an authenticated SDK session/client for this provider."""
        ...

    @property
    @abstractmethod
    def provider_type(self) -> str:
        """Return the provider type string (e.g., 'aws', 'azure', 'gcp', 'alicloud')."""
        ...


# ── Provider registry (lazy-loaded) ────────────────────────────────

PROVIDERS: dict[str, type[CloudProvider]] = {}
_providers_loaded = False


def _load_providers() -> None:
    """Lazily load provider implementations to avoid circular imports."""
    global _providers_loaded
    if _providers_loaded:
        return

    from agenticops.providers.aws import AWSProvider
    from agenticops.providers.azure import AzureProvider
    from agenticops.providers.gcp import GCPProvider
    from agenticops.providers.alicloud import AlicloudProvider

    PROVIDERS["aws"] = AWSProvider
    PROVIDERS["azure"] = AzureProvider
    PROVIDERS["gcp"] = GCPProvider
    PROVIDERS["alicloud"] = AlicloudProvider
    _providers_loaded = True


def get_provider(account: Any) -> CloudProvider:
    """Return the correct CloudProvider instance for the given account.

    Args:
        account: A CloudAccount instance with .provider attribute.

    Returns:
        CloudProvider instance for the account's provider type.

    Raises:
        ValueError: If the provider type is not supported.
    """
    _load_providers()
    provider_type = account.provider.lower()
    if provider_type not in PROVIDERS:
        supported = ", ".join(sorted(PROVIDERS.keys()))
        raise ValueError(
            f"Unsupported provider '{provider_type}'. Supported: {supported}"
        )
    return PROVIDERS[provider_type](account)
