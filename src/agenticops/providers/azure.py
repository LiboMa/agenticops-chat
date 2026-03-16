"""Azure cloud provider implementation.

Uses DefaultAzureCredential for broad authentication coverage
(managed identity, CLI, VS Code, environment variables, etc.).
Falls back gracefully if azure-identity is not installed.
"""

from __future__ import annotations

import logging
from typing import Any

from .base import CloudProvider, SessionCache, register_provider

logger = logging.getLogger(__name__)

try:
    from azure.identity import DefaultAzureCredential
    from azure.mgmt.resource import ResourceManagementClient

    _AZURE_SDK_AVAILABLE = True
except ImportError:
    _AZURE_SDK_AVAILABLE = False

_session_cache = SessionCache()


@register_provider
class AzureProvider(CloudProvider):
    """Azure provider using DefaultAzureCredential."""

    provider_name = "azure"

    def __init__(self, account_id: int, credentials: dict, regions: list[str] | None = None):
        super().__init__(account_id, credentials, regions)
        if not _AZURE_SDK_AVAILABLE:
            raise ImportError(
                "Azure SDK not installed. Install with: pip install clawops[azure]"
            )
        self._subscription_id = credentials.get("subscription_id", "")

    def get_session(self, region: str | None = None) -> Any:
        """Return an Azure credential + subscription_id tuple.

        Sessions are cached by (account_id, region).
        """
        region = region or (self.regions[0] if self.regions else "eastus")
        cache_key = f"azure:{self.account_id}:{region}"

        cached = _session_cache.get(cache_key)
        if cached is not None:
            return cached

        tenant_id = self._credentials.get("tenant_id")
        client_id = self._credentials.get("client_id")
        client_secret = self._credentials.get("client_secret")

        kwargs: dict[str, Any] = {}
        if tenant_id:
            kwargs["tenant_id"] = tenant_id
        if client_id and client_secret:
            # Service principal — use ClientSecretCredential via DefaultAzureCredential
            import os
            os.environ.setdefault("AZURE_TENANT_ID", tenant_id or "")
            os.environ.setdefault("AZURE_CLIENT_ID", client_id)
            os.environ.setdefault("AZURE_CLIENT_SECRET", client_secret)

        credential = DefaultAzureCredential(**kwargs)
        session = {"credential": credential, "subscription_id": self._subscription_id, "region": region}

        _session_cache.put(cache_key, session)
        return session

    def validate_credentials(self) -> bool:
        """Validate Azure credentials by listing resource groups."""
        try:
            session = self.get_session()
            client = ResourceManagementClient(
                session["credential"], session["subscription_id"]
            )
            # Try to list one resource group
            next(iter(client.resource_groups.list()), None)
            return True
        except Exception:
            logger.warning(
                "Azure credential validation failed for account %s",
                self.account_id, exc_info=True,
            )
            return False

    def list_resources(self, region: str, resource_type: str) -> list[dict]:
        """List Azure resources using Resource Management client."""
        session = self.get_session(region)
        client = ResourceManagementClient(
            session["credential"], session["subscription_id"]
        )

        results: list[dict] = []
        filter_str = f"resourceType eq '{resource_type}'" if resource_type else None
        for resource in client.resources.list(filter=filter_str):
            if resource.location and resource.location.lower().replace(" ", "") != region.lower().replace(" ", ""):
                continue
            results.append({
                "resource_id": resource.name or "",
                "name": resource.name or "",
                "status": "active",
                "azure_id": resource.id or "",
                "tags": dict(resource.tags) if resource.tags else {},
            })
        return results


def get_session_cache() -> SessionCache:
    """Expose module session cache for testing."""
    return _session_cache


def is_sdk_available() -> bool:
    """Check if Azure SDK is installed."""
    return _AZURE_SDK_AVAILABLE
