"""Alicloud provider implementation — CLI-only for MVP.

Uses subprocess calls to `aliyun` CLI rather than the Python SDK,
which is less mature than AWS/Azure/GCP SDKs.
No external Python dependencies required.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from typing import Any

from .base import CloudProvider, SessionCache, register_provider

logger = logging.getLogger(__name__)

_session_cache = SessionCache()


def _cli_available() -> bool:
    """Check if aliyun CLI is on PATH."""
    return shutil.which("aliyun") is not None


@register_provider
class AlicloudProvider(CloudProvider):
    """Alicloud provider using aliyun CLI subprocess calls."""

    provider_name = "alicloud"

    def __init__(self, account_id: int, credentials: dict, regions: list[str] | None = None):
        super().__init__(account_id, credentials, regions)
        # CLI-only: no SDK dependency, but warn if CLI missing
        if not _cli_available():
            logger.warning(
                "aliyun CLI not found on PATH. Alicloud operations will fail. "
                "Install: https://github.com/aliyun/aliyun-cli"
            )

    def get_session(self, region: str | None = None) -> Any:
        """Return a session dict with region and credential info.

        For CLI-based provider, 'session' is just context for subprocess calls.
        """
        region = region or (self.regions[0] if self.regions else "cn-hangzhou")
        cache_key = f"alicloud:{self.account_id}:{region}"

        cached = _session_cache.get(cache_key)
        if cached is not None:
            return cached

        session = {
            "region": region,
            "access_key_id": self._credentials.get("access_key_id", ""),
            "access_key_secret": self._credentials.get("access_key_secret", ""),
            "profile": self._credentials.get("profile", "default"),
        }
        _session_cache.put(cache_key, session)
        return session

    def _run_cli(self, service: str, action: str, region: str, **params: str) -> dict:
        """Execute an aliyun CLI command and return parsed JSON output."""
        session = self.get_session(region)
        cmd = [
            "aliyun", service, action,
            "--region", region,
            "--output", "json",
        ]
        if session.get("access_key_id"):
            cmd.extend(["--access-key-id", session["access_key_id"]])
            cmd.extend(["--access-key-secret", session["access_key_secret"]])
        elif session.get("profile") != "default":
            cmd.extend(["--profile", session["profile"]])

        for k, v in params.items():
            cmd.extend([f"--{k}", v])

        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(f"aliyun CLI error: {result.stderr.strip()}")
        return json.loads(result.stdout) if result.stdout.strip() else {}

    def validate_credentials(self) -> bool:
        """Validate Alicloud credentials via STS GetCallerIdentity."""
        try:
            self._run_cli("sts", "GetCallerIdentity", self.regions[0] if self.regions else "cn-hangzhou")
            return True
        except Exception:
            logger.warning(
                "Alicloud credential validation failed for account %s",
                self.account_id, exc_info=True,
            )
            return False

    def list_resources(self, region: str, resource_type: str) -> list[dict]:
        """List Alicloud resources via CLI.

        Maps common resource types to aliyun CLI commands.
        """
        type_map = {
            "ecs": ("ecs", "DescribeInstances"),
            "rds": ("rds", "DescribeDBInstances"),
            "slb": ("slb", "DescribeLoadBalancers"),
            "oss": ("oss", "ListBuckets"),
        }
        service, action = type_map.get(resource_type, (resource_type, "Describe"))

        try:
            data = self._run_cli(service, action, region)
            # Extract instances from typical Alicloud response structures
            instances = (
                data.get("Instances", {}).get("Instance", [])
                or data.get("Items", {}).get("DBInstance", [])
                or data.get("LoadBalancers", {}).get("LoadBalancer", [])
                or data.get("Buckets", {}).get("Bucket", [])
                or []
            )
            results: list[dict] = []
            for inst in instances:
                results.append({
                    "resource_id": inst.get("InstanceId") or inst.get("DBInstanceId") or inst.get("LoadBalancerId") or inst.get("Name", ""),
                    "name": inst.get("InstanceName") or inst.get("DBInstanceDescription") or inst.get("LoadBalancerName") or inst.get("Name", ""),
                    "status": inst.get("Status", "unknown").lower(),
                    "tags": inst.get("Tags", {}),
                })
            return results
        except Exception:
            logger.warning("Alicloud list_resources failed for %s/%s", region, resource_type, exc_info=True)
            return []


def get_session_cache() -> SessionCache:
    """Expose module session cache for testing."""
    return _session_cache
