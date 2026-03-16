"""GCP cloud provider implementation.

Uses google.auth.default() with cloud-platform scope for broad API access.
Falls back gracefully if google-auth is not installed.
"""

from __future__ import annotations

import logging
from typing import Any

from .base import CloudProvider, SessionCache, register_provider

logger = logging.getLogger(__name__)

_GCP_SCOPE = "https://www.googleapis.com/auth/cloud-platform"

try:
    import google.auth
    import google.auth.credentials

    _GCP_SDK_AVAILABLE = True
except ImportError:
    _GCP_SDK_AVAILABLE = False

_session_cache = SessionCache()


@register_provider
class GCPProvider(CloudProvider):
    """GCP provider using Application Default Credentials."""

    provider_name = "gcp"

    def __init__(self, account_id: int, credentials: dict, regions: list[str] | None = None):
        super().__init__(account_id, credentials, regions)
        if not _GCP_SDK_AVAILABLE:
            raise ImportError(
                "GCP SDK not installed. Install with: pip install clawops[gcp]"
            )
        self._project_id = credentials.get("project_id", "")

    def get_session(self, region: str | None = None) -> Any:
        """Return GCP credentials + project_id dict.

        Uses google.auth.default() with cloud-platform scope.
        Sessions are cached by (account_id, region).
        """
        region = region or (self.regions[0] if self.regions else "us-central1")
        cache_key = f"gcp:{self.account_id}:{region}"

        cached = _session_cache.get(cache_key)
        if cached is not None:
            return cached

        service_account_info = self._credentials.get("service_account_json")
        if service_account_info:
            from google.oauth2 import service_account
            cred = service_account.Credentials.from_service_account_info(
                service_account_info,
                scopes=[_GCP_SCOPE],
            )
            project = service_account_info.get("project_id", self._project_id)
        else:
            cred, project = google.auth.default(scopes=[_GCP_SCOPE])
            project = project or self._project_id

        session = {"credentials": cred, "project_id": project, "region": region}
        _session_cache.put(cache_key, session)
        return session

    def validate_credentials(self) -> bool:
        """Validate GCP credentials by refreshing the token."""
        try:
            session = self.get_session()
            cred = session["credentials"]
            # Refresh triggers actual auth check
            from google.auth.transport.requests import Request
            cred.refresh(Request())
            return True
        except Exception:
            logger.warning(
                "GCP credential validation failed for account %s",
                self.account_id, exc_info=True,
            )
            return False

    def list_resources(self, region: str, resource_type: str) -> list[dict]:
        """List GCP resources using Cloud Asset API.

        Note: Requires google-cloud-asset package for full implementation.
        Returns empty list if not available — placeholder for MVP.
        """
        try:
            from google.cloud import asset_v1
            session = self.get_session(region)
            client = asset_v1.AssetServiceClient(credentials=session["credentials"])

            request = asset_v1.ListAssetsRequest(
                parent=f"projects/{session['project_id']}",
                asset_types=[resource_type] if resource_type else [],
            )
            results: list[dict] = []
            for asset in client.list_assets(request=request):
                results.append({
                    "resource_id": asset.name.split("/")[-1] if asset.name else "",
                    "name": asset.name or "",
                    "status": "active",
                    "asset_type": asset.asset_type or "",
                })
            return results
        except ImportError:
            logger.info("google-cloud-asset not installed, list_resources returns empty")
            return []
        except Exception:
            logger.warning("GCP list_resources failed", exc_info=True)
            return []


def get_session_cache() -> SessionCache:
    """Expose module session cache for testing."""
    return _session_cache


def is_sdk_available() -> bool:
    """Check if GCP SDK is installed."""
    return _GCP_SDK_AVAILABLE
