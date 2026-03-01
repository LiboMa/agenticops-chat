"""Integration tools — cross-platform monitoring data access for agents."""

import json
import logging
from datetime import datetime, timedelta

from strands import tool

from agenticops.config import settings

logger = logging.getLogger(__name__)

MAX_RESULT_CHARS = 4000
MAX_LIST_RESULT_CHARS = 6000


def _truncate(text: str, limit: int = MAX_RESULT_CHARS) -> str:
    """Truncate tool output to prevent agent context overflow."""
    if len(text) <= limit:
        return text
    return text[:limit] + "\n... (output truncated)"


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _store_metrics(series_list):
    """Store metric series to MetricDataPoint table for trend analysis."""
    from agenticops.models import MetricDataPoint, get_db_session

    try:
        with get_db_session() as session:
            count = 0
            for series in series_list:
                for ts, val in zip(series.timestamps, series.values):
                    point = MetricDataPoint(
                        resource_id=series.resource_id,
                        metric_namespace=series.namespace,
                        metric_name=series.metric_name,
                        timestamp=ts,
                        value=val,
                        unit=series.unit,
                    )
                    session.add(point)
                    count += 1
            logger.info("Stored %d metric data points", count)
    except Exception:
        logger.warning("Failed to store metric data points", exc_info=True)


# ---------------------------------------------------------------------------
# @tool functions
# ---------------------------------------------------------------------------


@tool
def query_provider_metrics(
    provider: str,
    resource_id: str,
    metric_names: str,
    hours: int = 1,
) -> str:
    """Query metrics from an external monitoring provider (datadog, cloudwatch, etc.).

    Args:
        provider: Provider name (e.g. 'cloudwatch', 'datadog').
        resource_id: AWS resource ID, hostname, or provider-specific identifier.
        metric_names: Comma-separated metric names (e.g. 'CPUUtilization,NetworkIn').
        hours: Number of hours of data to retrieve (default 1).

    Returns:
        JSON array of metric series with timestamps, values, and metadata.
    """
    try:
        from agenticops.integrations import get_provider, list_provider_names

        prov = get_provider(provider)
        if prov is None:
            available = [p["name"] for p in list_provider_names() if p["status"] == "active"]
            return json.dumps({
                "error": f"Provider '{provider}' not found.",
                "available_providers": available,
            })

        metric_list = [m.strip() for m in metric_names.split(",") if m.strip()]
        end = datetime.utcnow()
        start = end - timedelta(hours=hours)

        series_list = prov.query_metrics(resource_id, metric_list, start, end)

        # Convert to JSON-serializable format
        results = []
        for series in series_list:
            results.append({
                "resource_id": series.resource_id,
                "metric_name": series.metric_name,
                "namespace": series.namespace,
                "unit": series.unit,
                "count": series.count,
                "latest_value": series.latest_value,
                "timestamps": [ts.isoformat() for ts in series.timestamps],
                "values": series.values,
                "tags": series.tags,
            })

        # Optionally persist for trend analysis
        if settings.metric_storage_enabled:
            _store_metrics(series_list)

        return _truncate(json.dumps(results, default=str), MAX_LIST_RESULT_CHARS)
    except Exception as e:
        logger.error("query_provider_metrics failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@tool
def query_provider_logs(
    provider: str,
    query: str,
    hours: int = 1,
    limit: int = 50,
) -> str:
    """Query logs from an external monitoring provider.

    Args:
        provider: Provider name (e.g. 'cloudwatch', 'datadog').
        query: Query string in the provider's query language.
        hours: Number of hours of logs to search (default 1).
        limit: Maximum number of log entries to return (default 50).

    Returns:
        JSON array of log entries with timestamp, message, level, and source.
    """
    try:
        from agenticops.integrations import get_provider, list_provider_names

        prov = get_provider(provider)
        if prov is None:
            available = [p["name"] for p in list_provider_names() if p["status"] == "active"]
            return json.dumps({
                "error": f"Provider '{provider}' not found.",
                "available_providers": available,
            })

        end = datetime.utcnow()
        start = end - timedelta(hours=hours)

        entries = prov.query_logs(query, start, end, limit=limit)

        results = []
        for entry in entries:
            results.append({
                "timestamp": entry.timestamp.isoformat(),
                "message": entry.message,
                "level": entry.level,
                "source": entry.source,
                "fields": entry.fields,
            })

        return _truncate(json.dumps(results, default=str), MAX_LIST_RESULT_CHARS)
    except Exception as e:
        logger.error("query_provider_logs failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@tool
def list_provider_alerts(provider: str = "all") -> str:
    """List active alerts from external monitoring providers.

    Args:
        provider: Provider name, or 'all' to query every configured provider (default 'all').

    Returns:
        JSON array of active alerts with source, severity, title, and description.
    """
    try:
        from agenticops.integrations import get_provider, get_providers, list_provider_names

        alerts = []

        if provider == "all":
            for prov in get_providers():
                try:
                    for alert in prov.list_active_alerts():
                        alerts.append({
                            "provider": prov.name,
                            "external_id": alert.external_id,
                            "severity": alert.severity,
                            "title": alert.title,
                            "description": alert.description,
                            "resource_hint": alert.resource_hint,
                            "tags": alert.tags,
                        })
                except Exception as e:
                    logger.warning("Failed to fetch alerts from %s: %s", prov.name, e)
                    alerts.append({
                        "provider": prov.name,
                        "error": str(e),
                    })
        else:
            prov = get_provider(provider)
            if prov is None:
                available = [p["name"] for p in list_provider_names() if p["status"] == "active"]
                return json.dumps({
                    "error": f"Provider '{provider}' not found.",
                    "available_providers": available,
                })

            for alert in prov.list_active_alerts():
                alerts.append({
                    "provider": prov.name,
                    "external_id": alert.external_id,
                    "severity": alert.severity,
                    "title": alert.title,
                    "description": alert.description,
                    "resource_hint": alert.resource_hint,
                    "tags": alert.tags,
                })

        return _truncate(json.dumps(alerts, default=str), MAX_LIST_RESULT_CHARS)
    except Exception as e:
        logger.error("list_provider_alerts failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@tool
def list_monitoring_providers() -> str:
    """List configured monitoring providers and their status.

    Returns:
        JSON array of providers with name and configuration status.
    """
    try:
        from agenticops.integrations import list_provider_names

        providers = list_provider_names()
        return json.dumps(providers, default=str)
    except Exception as e:
        logger.error("list_monitoring_providers failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@tool
def store_metric_snapshot(
    resource_id: str,
    metric_name: str,
    value: float,
    namespace: str = "",
    unit: str = "",
) -> str:
    """Store a metric data point for trend analysis.

    Args:
        resource_id: AWS resource ID, hostname, or provider-specific identifier.
        metric_name: Name of the metric (e.g. 'CPUUtilization').
        value: Numeric metric value.
        namespace: Metric namespace (e.g. 'AWS/EC2', 'custom').
        unit: Unit of measurement (e.g. 'Percent', 'Count').

    Returns:
        Confirmation message with stored data point details.
    """
    try:
        from agenticops.models import MetricDataPoint, get_db_session

        with get_db_session() as session:
            point = MetricDataPoint(
                resource_id=resource_id,
                metric_namespace=namespace,
                metric_name=metric_name,
                timestamp=datetime.utcnow(),
                value=value,
                unit=unit,
            )
            session.add(point)

        return json.dumps({
            "status": "stored",
            "resource_id": resource_id,
            "metric_name": metric_name,
            "value": value,
            "namespace": namespace,
            "unit": unit,
        })
    except Exception as e:
        logger.error("store_metric_snapshot failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})
