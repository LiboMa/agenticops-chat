"""Monitoring integrations — provider registry and data models."""

import logging
from typing import Optional

from agenticops.config import settings
from agenticops.integrations.base import (
    AlertPayload,
    LogEntry,
    MetricSeries,
    MonitoringProvider,
)

logger = logging.getLogger(__name__)

__all__ = [
    "AlertPayload",
    "LogEntry",
    "MetricSeries",
    "MonitoringProvider",
    "get_provider",
    "get_providers",
    "list_provider_names",
]

# Lazy-initialized provider cache
_provider_cache: dict[str, MonitoringProvider] = {}


def _init_providers() -> None:
    """Initialize providers based on config."""
    global _provider_cache

    if _provider_cache:
        return  # already initialized

    configured = [
        p.strip().lower()
        for p in settings.monitoring_providers.split(",")
        if p.strip()
    ]

    # CloudWatch is always available (uses existing AWS credentials)
    if "cloudwatch" in configured or not configured:
        try:
            from agenticops.integrations.cloudwatch_provider import CloudWatchProvider

            _provider_cache["cloudwatch"] = CloudWatchProvider()
            logger.info("CloudWatch monitoring provider initialized")
        except Exception as e:
            logger.warning("Failed to initialize CloudWatch provider: %s", e)

    # Datadog — requires API keys
    if "datadog" in configured and settings.datadog_api_key:
        try:
            from agenticops.integrations.datadog_provider import DatadogProvider

            _provider_cache["datadog"] = DatadogProvider(
                api_key=settings.datadog_api_key,
                app_key=settings.datadog_app_key,
                site=settings.datadog_site,
            )
            logger.info("Datadog monitoring provider initialized")
        except Exception as e:
            logger.warning("Failed to initialize Datadog provider: %s", e)


def get_providers() -> list[MonitoringProvider]:
    """Get all configured and active monitoring providers."""
    _init_providers()
    return list(_provider_cache.values())


def get_provider(name: str) -> Optional[MonitoringProvider]:
    """Get a specific provider by name."""
    _init_providers()
    return _provider_cache.get(name.lower())


def list_provider_names() -> list[dict[str, str]]:
    """List all providers with their configuration status."""
    _init_providers()

    results = []
    # CloudWatch
    cw_status = "active" if "cloudwatch" in _provider_cache else "not_configured"
    results.append({"name": "cloudwatch", "status": cw_status})

    # Datadog
    if settings.datadog_api_key:
        dd_status = "active" if "datadog" in _provider_cache else "error"
    else:
        dd_status = "not_configured"
    results.append({"name": "datadog", "status": dd_status})

    return results


def reset_providers() -> None:
    """Reset provider cache (useful for testing or config reload)."""
    global _provider_cache
    _provider_cache = {}
