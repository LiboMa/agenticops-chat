"""CloudProvider ABC, capability protocols, provider registry, and session cache."""

from __future__ import annotations

import logging
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


# ── Capabilities (MVP-2.0.0) ───────────────────────────────────────
#
# Providers declare what they can do; agents check before routing.
# Not every provider supports everything: Prometheus has metrics but no
# execute; SSH has execute but only trivial inventory. Inventory and
# execution are deliberately decoupled (a host may be discovered by one
# provider and operated on by another).


class Capability(str, Enum):
    INVENTORY = "inventory"  # list/search resources
    METRICS = "metrics"      # time-series query
    LOGS = "logs"            # log search
    AUDIT = "audit"          # control-plane event history
    ALARMS = "alarms"        # read alarm/alert state
    EXECUTE = "execute"      # run commands on/against targets
    COST = "cost"            # spend query
    CLI = "cli"              # raw CLI passthrough


@dataclass(frozen=True)
class ResourceRef:
    """Uniform cross-provider resource address.

    URN form: ``urn:agops:{provider}:{account}:{region}:{service}:{rtype}:{native_id}``
    ``region`` may be empty (Azure global, ssh hosts). ``native_id`` always
    keeps the provider's own identifier verbatim (ARN / Azure resource ID /
    GCP full resource name / host:port) — never parse it, pass it back to
    the provider for any write path.
    """

    provider: str
    account: str
    region: str
    service: str
    rtype: str
    native_id: str
    name: str = ""
    labels: dict = field(default_factory=dict)

    @property
    def urn(self) -> str:
        return (
            f"urn:agops:{self.provider}:{self.account}:{self.region}"
            f":{self.service}:{self.rtype}:{self.native_id}"
        )

    def to_dict(self) -> dict:
        return {
            "urn": self.urn,
            "provider": self.provider,
            "account": self.account,
            "region": self.region,
            "service": self.service,
            "type": self.rtype,
            "native_id": self.native_id,
            "name": self.name,
            "labels": dict(self.labels),
        }


@runtime_checkable
class SupportsInventory(Protocol):
    def list_resources(
        self,
        *,
        query: str = "",
        types: list[str] | None = None,
        region: str | None = None,
        limit: int = 500,
    ) -> list[ResourceRef]: ...


@runtime_checkable
class SupportsMetrics(Protocol):
    def query_metrics(
        self,
        *,
        metric: str,
        start: str,
        end: str,
        target: ResourceRef | None = None,
        period_s: int = 300,
        stat: str = "avg",
    ) -> list[dict]: ...


@runtime_checkable
class SupportsExecute(Protocol):
    def execute(
        self,
        *,
        target: ResourceRef,
        command: str,
        timeout_s: int = 60,
    ) -> dict: ...

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

    def capabilities(self) -> set[Capability]:
        """Capability discovery — agents check this before routing work.

        Derived structurally from the optional protocols a provider
        implements; CLI is assumed for all cloud providers (the historic
        baseline) and removed by infra providers that override cli_tool
        with a no-op.
        """
        caps: set[Capability] = {Capability.CLI}
        if isinstance(self, SupportsInventory):
            caps.add(Capability.INVENTORY)
        if isinstance(self, SupportsMetrics):
            caps.add(Capability.METRICS)
        if isinstance(self, SupportsExecute):
            caps.add(Capability.EXECUTE)
        return caps


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
    from agenticops.providers.ssh import SSHProvider
    from agenticops.providers.prometheus import PrometheusProvider
    from agenticops.providers.kubernetes import KubernetesProvider

    PROVIDERS["aws"] = AWSProvider
    PROVIDERS["azure"] = AzureProvider
    PROVIDERS["gcp"] = GCPProvider
    PROVIDERS["alicloud"] = AlicloudProvider
    PROVIDERS["ssh"] = SSHProvider
    PROVIDERS["prometheus"] = PrometheusProvider
    PROVIDERS["kubernetes"] = KubernetesProvider
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


def get_all_cli_tools() -> list[Callable]:
    """Return CLI tools for all enabled cloud accounts.

    Iterates enabled accounts, resolves credentials, and returns a list of
    provider-specific CLI tool callables. Accounts that fail credential
    resolution are silently skipped.
    """
    from agenticops.models import CloudAccount, get_db_session
    from types import SimpleNamespace
    tools: list[Callable] = []
    try:
        with get_db_session() as db:
            accounts = db.query(CloudAccount).filter(CloudAccount.is_enabled == True).all()  # noqa: E712
            snapshots = [
                SimpleNamespace(
                    id=a.id, name=a.name, provider=a.provider,
                    credentials=dict(a.credentials or {}),
                    regions=list(a.regions or []), labels=dict(a.labels or {}),
                )
                for a in accounts
            ]
        for snap in snapshots:
            try:
                provider = get_provider(snap)
                if provider.resolve_credentials():
                    tools.append(provider.cli_tool())
            except Exception as e:
                logger.warning("Failed to init provider for %s: %s", snap.name, e)
    except Exception as e:
        logger.warning("Failed to load cloud accounts: %s", e)
    return tools


def get_cli_tool_for_issue(issue_account_id: int | None) -> Callable | None:
    """Resolve CLI tool from a HealthIssue's account_id.

    Returns a provider-specific CLI tool callable, or None if account not found
    or credentials fail.
    """
    if not issue_account_id:
        return None
    from agenticops.models import CloudAccount, get_db_session
    from types import SimpleNamespace
    with get_db_session() as db:
        acct = db.query(CloudAccount).filter_by(id=issue_account_id).first()
        if not acct:
            return None
        # Snapshot to avoid DetachedInstanceError
        snap = SimpleNamespace(
            id=acct.id, name=acct.name, provider=acct.provider,
            credentials=dict(acct.credentials or {}),
            regions=list(acct.regions or []), labels=dict(acct.labels or {}),
        )
    provider = get_provider(snap)
    if provider.resolve_credentials():
        return provider.cli_tool()
    return None
