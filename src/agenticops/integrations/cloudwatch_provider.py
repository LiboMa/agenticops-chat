"""CloudWatch monitoring provider — wraps existing AWS CloudWatch into unified interface."""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any

import boto3
from botocore.exceptions import ClientError

from agenticops.config import settings
from agenticops.integrations.base import AlertPayload, LogEntry, MetricSeries, MonitoringProvider

logger = logging.getLogger(__name__)

# Namespace inference: resource-ID prefix → (namespace, dimension_name)
_NAMESPACE_MAP: dict[str, tuple[str, str]] = {
    "i-": ("AWS/EC2", "InstanceId"),
    "db-": ("AWS/RDS", "DBInstanceIdentifier"),
    "vol-": ("AWS/EBS", "VolumeId"),
    "arn:aws:lambda": ("AWS/Lambda", "FunctionName"),
    "arn:aws:sqs": ("AWS/SQS", "QueueName"),
    "arn:aws:sns": ("AWS/SNS", "TopicName"),
    "arn:aws:elasticache": ("AWS/ElastiCache", "CacheClusterId"),
    "arn:aws:dynamodb": ("AWS/DynamoDB", "TableName"),
}

# If the resource_id contains these substrings, override namespace detection
_NAMESPACE_HINTS: dict[str, tuple[str, str]] = {
    "rds": ("AWS/RDS", "DBInstanceIdentifier"),
    "lambda": ("AWS/Lambda", "FunctionName"),
    "elasticache": ("AWS/ElastiCache", "CacheClusterId"),
    "ecs": ("AWS/ECS", "ClusterName"),
    "eks": ("AWS/EKS", "ClusterName"),
}

# Default fallback
_DEFAULT_NAMESPACE = "AWS/EC2"
_DEFAULT_DIMENSION = "InstanceId"

_QUERY_POLL_INTERVAL = 1.0  # seconds between CloudWatch Insights polling
_QUERY_MAX_WAIT = 60.0  # max seconds to wait for Insights query completion
_MAX_ALARMS_TO_FETCH = 100


def _infer_namespace(resource_id: str) -> tuple[str, str]:
    """Infer CloudWatch namespace and dimension name from a resource identifier.

    Returns:
        Tuple of (namespace, dimension_name).
    """
    # Check prefix-based mapping first (most specific)
    for prefix, (namespace, dim) in _NAMESPACE_MAP.items():
        if resource_id.startswith(prefix):
            return namespace, dim

    # Check substring hints (less specific)
    rid_lower = resource_id.lower()
    for hint, (namespace, dim) in _NAMESPACE_HINTS.items():
        if hint in rid_lower:
            return namespace, dim

    return _DEFAULT_NAMESPACE, _DEFAULT_DIMENSION


class CloudWatchProvider(MonitoringProvider):
    """AWS CloudWatch implementation of :class:`MonitoringProvider`.

    Reuses assumed-role sessions from the existing ``aws_tools._session_cache``
    when available, falling back to default boto3 credentials.
    """

    def __init__(self, region: str = "") -> None:
        self.name = "cloudwatch"
        self.region = region or settings.bedrock_region
        self._clients: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_client(self, service: str) -> Any:
        """Return a boto3 client, reusing assumed-role sessions when possible.

        Lookup order:
        1. Locally cached client for this service.
        2. Active assumed-role session from ``aws_tools._session_cache``.
        3. Default boto3 session for the configured region.
        """
        if service in self._clients:
            return self._clients[service]

        session: boto3.Session | None = None

        # Try to reuse an existing assumed-role session for our region
        try:
            from agenticops.tools.aws_tools import _session_cache

            for key, cached_session in _session_cache.items():
                if key.endswith(f":{self.region}"):
                    session = cached_session
                    break
        except Exception:
            # aws_tools may not be importable in all environments
            pass

        if session is None:
            session = boto3.Session(region_name=self.region)

        client = session.client(service, region_name=self.region)
        self._clients[service] = client
        return client

    # ------------------------------------------------------------------
    # MonitoringProvider implementation
    # ------------------------------------------------------------------

    def query_metrics(
        self,
        resource_id: str,
        metric_names: list[str],
        start: datetime,
        end: datetime,
    ) -> list[MetricSeries]:
        """Query CloudWatch metric statistics for a resource.

        Infers the CloudWatch namespace and dimension from the resource ID
        (e.g. ``i-0abc`` maps to ``AWS/EC2`` / ``InstanceId``).
        """
        client = self._get_client("cloudwatch")
        namespace, dimension_name = _infer_namespace(resource_id)
        results: list[MetricSeries] = []

        for metric_name in metric_names:
            try:
                response = client.get_metric_statistics(
                    Namespace=namespace,
                    MetricName=metric_name,
                    Dimensions=[{"Name": dimension_name, "Value": resource_id}],
                    StartTime=start,
                    EndTime=end,
                    Period=300,
                    Statistics=["Average"],
                )

                datapoints = sorted(
                    response.get("Datapoints", []),
                    key=lambda dp: dp["Timestamp"],
                )

                series = MetricSeries(
                    resource_id=resource_id,
                    metric_name=metric_name,
                    namespace=namespace,
                    timestamps=[dp["Timestamp"] for dp in datapoints],
                    values=[dp["Average"] for dp in datapoints],
                    unit=datapoints[0]["Unit"] if datapoints else "",
                    tags={"dimension": dimension_name},
                )
                results.append(series)

            except ClientError as exc:
                logger.warning(
                    "CloudWatch get_metric_statistics failed for %s/%s: %s",
                    namespace,
                    metric_name,
                    exc,
                )
            except Exception as exc:
                logger.error(
                    "Unexpected error querying metric %s for %s: %s",
                    metric_name,
                    resource_id,
                    exc,
                )

        return results

    def list_active_alerts(self) -> list[AlertPayload]:
        """List all CloudWatch alarms currently in ALARM state.

        Paginates with NextToken up to ``_MAX_ALARMS_TO_FETCH`` alarms.
        """
        client = self._get_client("cloudwatch")
        alerts: list[AlertPayload] = []

        try:
            kwargs: dict[str, Any] = {"StateValue": "ALARM", "MaxRecords": 100}
            fetched = 0

            while fetched < _MAX_ALARMS_TO_FETCH:
                response = client.describe_alarms(**kwargs)

                for alarm in response.get("MetricAlarms", []):
                    # Build resource hint from dimensions
                    dimensions = alarm.get("Dimensions", [])
                    resource_hint = ""
                    if dimensions:
                        resource_hint = dimensions[0].get("Value", "")

                    description_parts = []
                    if alarm.get("AlarmDescription"):
                        description_parts.append(alarm["AlarmDescription"])
                    if alarm.get("StateReason"):
                        description_parts.append(alarm["StateReason"])

                    alerts.append(
                        AlertPayload(
                            source="cloudwatch",
                            external_id=alarm.get("AlarmArn", alarm["AlarmName"]),
                            severity=_severity_from_alarm(alarm),
                            title=alarm["AlarmName"],
                            description=" | ".join(description_parts),
                            resource_hint=resource_hint,
                            tags={
                                "namespace": alarm.get("Namespace", ""),
                                "metric": alarm.get("MetricName", ""),
                                "region": self.region,
                            },
                            raw=alarm,
                        )
                    )
                    fetched += 1
                    if fetched >= _MAX_ALARMS_TO_FETCH:
                        break

                next_token = response.get("NextToken")
                if not next_token:
                    break
                kwargs["NextToken"] = next_token

        except ClientError as exc:
            logger.warning("CloudWatch describe_alarms failed: %s", exc)
        except Exception as exc:
            logger.error("Unexpected error listing CloudWatch alarms: %s", exc)

        return alerts

    def query_logs(
        self,
        query: str,
        start: datetime,
        end: datetime,
        limit: int = 100,
    ) -> list[LogEntry]:
        """Run a CloudWatch Logs Insights query.

        If *query* begins with ``/`` it is treated as a log group name followed
        by a query string (separated by the first space).  Otherwise the query
        is run against a default ``/aws/agenticops`` log group.

        Example::

            provider.query_logs(
                "/ecs/my-service fields @timestamp, @message | filter @message like /ERROR/",
                start, end,
            )
        """
        client = self._get_client("logs")

        # Parse log group from query if provided
        if query.startswith("/"):
            parts = query.split(" ", 1)
            if len(parts) == 2:
                log_group = parts[0]
                query_string = parts[1]
            else:
                log_group = parts[0]
                query_string = "fields @timestamp, @message | sort @timestamp desc"
        else:
            log_group = "/aws/agenticops"
            query_string = query

        try:
            start_response = client.start_query(
                logGroupName=log_group,
                startTime=int(start.timestamp()),
                endTime=int(end.timestamp()),
                queryString=query_string,
                limit=limit,
            )
            query_id = start_response["queryId"]
        except ClientError as exc:
            logger.warning(
                "CloudWatch start_query failed for %s: %s", log_group, exc
            )
            return []
        except Exception as exc:
            logger.error("Unexpected error starting log query: %s", exc)
            return []

        # Poll until the query completes
        entries: list[LogEntry] = []
        elapsed = 0.0

        while elapsed < _QUERY_MAX_WAIT:
            try:
                result = client.get_query_results(queryId=query_id)
            except ClientError as exc:
                logger.warning("CloudWatch get_query_results failed: %s", exc)
                return []

            status = result.get("status", "")
            if status in ("Complete", "Failed", "Cancelled", "Timeout"):
                if status != "Complete":
                    logger.warning(
                        "CloudWatch Insights query %s ended with status: %s",
                        query_id,
                        status,
                    )
                break

            time.sleep(_QUERY_POLL_INTERVAL)
            elapsed += _QUERY_POLL_INTERVAL

        if elapsed >= _QUERY_MAX_WAIT:
            logger.warning(
                "CloudWatch Insights query %s timed out after %.0fs",
                query_id,
                _QUERY_MAX_WAIT,
            )

        # Parse results into LogEntry objects
        for row in result.get("results", []):
            fields: dict[str, str] = {}
            message = ""
            timestamp_val = None

            for field_entry in row:
                name = field_entry.get("field", "")
                value = field_entry.get("value", "")

                if name == "@message":
                    message = value
                elif name == "@timestamp":
                    try:
                        timestamp_val = datetime.fromisoformat(
                            value.replace("Z", "+00:00")
                        )
                    except (ValueError, TypeError):
                        timestamp_val = datetime.now()
                elif name == "@ptr":
                    # Internal pointer field — skip
                    continue
                else:
                    fields[name] = value

            # Infer log level from message content
            level = _infer_log_level(message)

            entries.append(
                LogEntry(
                    timestamp=timestamp_val or datetime.now(),
                    message=message,
                    level=level,
                    source=log_group,
                    fields=fields,
                )
            )

        return entries

    def health_check(self) -> bool:
        """Verify CloudWatch connectivity by describing alarm history."""
        try:
            client = self._get_client("cloudwatch")
            client.describe_alarms(MaxRecords=1)
            return True
        except Exception:
            return False


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------


def _severity_from_alarm(alarm: dict) -> str:
    """Derive a severity level from alarm metadata.

    Heuristic: check alarm name and description for severity keywords.
    Falls back to ``"high"`` since an alarm in ALARM state is inherently
    significant.
    """
    searchable = (
        alarm.get("AlarmName", "") + " " + alarm.get("AlarmDescription", "")
    ).lower()

    if "critical" in searchable or "pager" in searchable:
        return "critical"
    if "low" in searchable or "info" in searchable:
        return "low"
    if "medium" in searchable or "warn" in searchable:
        return "medium"
    return "high"


def _infer_log_level(message: str) -> str:
    """Best-effort log level inference from message content."""
    upper = message.upper()
    if "ERROR" in upper or "FATAL" in upper or "EXCEPTION" in upper:
        return "error"
    if "WARN" in upper:
        return "warn"
    if "DEBUG" in upper or "TRACE" in upper:
        return "debug"
    if "INFO" in upper:
        return "info"
    return ""
