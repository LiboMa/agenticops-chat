"""AWS cloud provider implementation.

Uses boto3 STS assume_role for cross-account access. Falls back to default
credentials if no role_arn is provided.
"""

from __future__ import annotations

import logging
from typing import Any

import boto3

from .base import CloudProvider, SessionCache, register_provider

logger = logging.getLogger(__name__)

# Module-level session cache shared across all AWSProvider instances
_session_cache = SessionCache()


@register_provider
class AWSProvider(CloudProvider):
    """AWS provider using boto3 sessions."""

    provider_name = "aws"

    def get_session(self, region: str | None = None) -> Any:
        """Return a boto3.Session, using STS assume_role if role_arn is set.

        Sessions are cached by (account_id, region) with TTL expiry.
        """
        region = region or (self.regions[0] if self.regions else "us-east-1")
        cache_key = f"aws:{self.account_id}:{region}"

        cached = _session_cache.get(cache_key)
        if cached is not None:
            return cached

        role_arn = self._credentials.get("role_arn")
        if role_arn:
            sts = boto3.client("sts", region_name=region)
            params: dict[str, Any] = {
                "RoleArn": role_arn,
                "RoleSessionName": f"clawops-{self.account_id}",
            }
            external_id = self._credentials.get("external_id")
            if external_id:
                params["ExternalId"] = external_id

            resp = sts.assume_role(**params)
            creds = resp["Credentials"]
            session = boto3.Session(
                aws_access_key_id=creds["AccessKeyId"],
                aws_secret_access_key=creds["SecretAccessKey"],
                aws_session_token=creds["SessionToken"],
                region_name=region,
            )
        else:
            # Fallback: default credentials (local dev, EC2 instance role, etc.)
            session = boto3.Session(region_name=region)

        _session_cache.put(cache_key, session)
        return session

    def validate_credentials(self) -> bool:
        """Validate AWS credentials via STS get_caller_identity."""
        try:
            session = self.get_session()
            sts = session.client("sts")
            sts.get_caller_identity()
            return True
        except Exception:
            logger.warning("AWS credential validation failed for account %s", self.account_id, exc_info=True)
            return False

    def list_resources(self, region: str, resource_type: str) -> list[dict]:
        """List AWS resources using resource groups tagging API.

        Returns list of dicts: {resource_id, name, status, arn}.
        """
        session = self.get_session(region)
        client = session.client("resourcegroupstaggingapi", region_name=region)

        results: list[dict] = []
        paginator = client.get_paginator("get_resources")
        filters = {"ResourceTypeFilters": [resource_type]} if resource_type else {}

        for page in paginator.paginate(**filters):
            for resource in page.get("ResourceTagMappingList", []):
                arn = resource.get("ResourceARN", "")
                tags = {t["Key"]: t["Value"] for t in resource.get("Tags", [])}
                results.append({
                    "resource_id": arn.split("/")[-1] if "/" in arn else arn.split(":")[-1],
                    "name": tags.get("Name", ""),
                    "status": "active",
                    "arn": arn,
                    "tags": tags,
                })
        return results


def get_session_cache() -> SessionCache:
    """Expose module session cache for testing."""
    return _session_cache
