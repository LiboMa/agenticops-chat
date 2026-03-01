"""Base classes and data models for monitoring integrations."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class MetricSeries:
    """Standardized metric time series from any provider."""

    resource_id: str
    metric_name: str
    namespace: str  # e.g., AWS/EC2, datadog.agent, custom
    timestamps: list[datetime] = field(default_factory=list)
    values: list[float] = field(default_factory=list)
    unit: str = ""
    tags: dict[str, str] = field(default_factory=dict)

    @property
    def latest_value(self) -> Optional[float]:
        return self.values[-1] if self.values else None

    @property
    def count(self) -> int:
        return len(self.values)


@dataclass
class LogEntry:
    """Standardized log entry from any provider."""

    timestamp: datetime
    message: str
    level: str = ""  # error, warn, info, debug
    source: str = ""  # log group, index, etc.
    fields: dict[str, str] = field(default_factory=dict)


@dataclass
class AlertPayload:
    """Standardized alert from any monitoring system."""

    source: str  # datadog, pagerduty, grafana, cloudwatch, generic
    external_id: str  # dedup key from source
    severity: str  # critical, high, medium, low
    title: str
    description: str
    resource_hint: str  # best-effort resource ID (e.g., i-xxx, arn:..., pod name)
    tags: dict[str, str] = field(default_factory=dict)
    raw: dict = field(default_factory=dict)


class MonitoringProvider(ABC):
    """Abstract monitoring data source.

    Implementations wrap specific monitoring APIs (CloudWatch, Datadog, etc.)
    into a unified interface for cross-platform querying.
    """

    name: str

    @abstractmethod
    def query_metrics(
        self,
        resource_id: str,
        metric_names: list[str],
        start: datetime,
        end: datetime,
    ) -> list[MetricSeries]:
        """Query metric time series for a resource.

        Args:
            resource_id: AWS resource ID, hostname, or provider-specific identifier.
            metric_names: List of metric names to query.
            start: Start of time range.
            end: End of time range.

        Returns:
            List of MetricSeries with data points.
        """
        ...

    @abstractmethod
    def list_active_alerts(self) -> list[AlertPayload]:
        """List currently active/triggered alerts.

        Returns:
            List of AlertPayload for all active alerts.
        """
        ...

    @abstractmethod
    def query_logs(
        self,
        query: str,
        start: datetime,
        end: datetime,
        limit: int = 100,
    ) -> list[LogEntry]:
        """Query logs with a provider-specific query language.

        Args:
            query: Query string (CloudWatch Insights, Datadog log query, etc.).
            start: Start of time range.
            end: End of time range.
            limit: Maximum number of log entries to return.

        Returns:
            List of LogEntry results.
        """
        ...

    def health_check(self) -> bool:
        """Check if the provider is reachable and configured.

        Returns:
            True if the provider is healthy, False otherwise.
        """
        try:
            self.list_active_alerts()
            return True
        except Exception:
            return False
