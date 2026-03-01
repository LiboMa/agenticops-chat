"""Datadog monitoring provider — queries Datadog API v2 via httpx."""

import logging
import re
from datetime import datetime
from typing import Any

from agenticops.integrations.base import AlertPayload, LogEntry, MetricSeries, MonitoringProvider

logger = logging.getLogger(__name__)

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore[assignment]

# Severity mapping from Datadog monitor states to standardized levels
_STATE_SEVERITY_MAP: dict[str, str] = {
    "Alert": "critical",
    "Warn": "high",
    "No Data": "medium",
    "OK": "low",
}

# Pattern to detect AWS instance IDs (e.g., i-0abc1234def56789a)
_INSTANCE_ID_RE = re.compile(r"^i-[0-9a-f]{8,17}$")


class DatadogProvider(MonitoringProvider):
    """Monitoring provider that queries Datadog API v2 via httpx.

    Requires ``httpx`` to be installed (``pip install httpx``).
    Authentication uses DD-API-KEY and DD-APPLICATION-KEY headers.
    """

    name: str = "datadog"

    def __init__(self, api_key: str, app_key: str, site: str = "datadoghq.com") -> None:
        if httpx is None:
            raise ImportError(
                "httpx is required for the Datadog provider. "
                "Install it with: pip install httpx"
            )
        self.api_key = api_key
        self.app_key = app_key
        self.base_url = f"https://api.{site}"
        self._headers = {
            "DD-API-KEY": api_key,
            "DD-APPLICATION-KEY": app_key,
            "Content-Type": "application/json",
        }

    # ------------------------------------------------------------------
    # Internal HTTP helper
    # ------------------------------------------------------------------

    def _request(self, method: str, path: str, **kwargs: Any) -> dict:
        """Execute an HTTP request against the Datadog API.

        Args:
            method: HTTP method (GET, POST, etc.).
            path: API path (e.g., ``/api/v2/query/timeseries``).
            **kwargs: Forwarded to ``httpx.Client.request``.

        Returns:
            Parsed JSON response body.

        Raises:
            httpx.HTTPStatusError: On 4xx/5xx responses.
            httpx.HTTPError: On connection/timeout errors.
        """
        url = f"{self.base_url}{path}"
        try:
            with httpx.Client(timeout=30) as client:
                response = client.request(
                    method,
                    url,
                    headers=self._headers,
                    **kwargs,
                )
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError:
            logger.error(
                "Datadog API error: %s %s returned %s",
                method,
                path,
                response.status_code,  # type: ignore[possibly-undefined]
            )
            raise
        except httpx.HTTPError as exc:
            logger.error("Datadog API request failed: %s %s — %s", method, path, exc)
            raise

    # ------------------------------------------------------------------
    # Resource filter helper
    # ------------------------------------------------------------------

    @staticmethod
    def _resource_filter(resource_id: str) -> str:
        """Build a Datadog tag filter expression for a resource.

        If the resource_id looks like an AWS EC2 instance ID (``i-...``),
        uses ``instance:<id>``; otherwise assumes it is a hostname and
        uses ``host:<id>``.
        """
        if _INSTANCE_ID_RE.match(resource_id):
            return f"instance:{resource_id}"
        return f"host:{resource_id}"

    # ------------------------------------------------------------------
    # MonitoringProvider interface
    # ------------------------------------------------------------------

    def query_metrics(
        self,
        resource_id: str,
        metric_names: list[str],
        start: datetime,
        end: datetime,
    ) -> list[MetricSeries]:
        """Query Datadog Metrics API v2 for time series data.

        Makes one request per metric name.  Returns an empty list if any
        individual metric query fails (logged as a warning).
        """
        start_ms = int(start.timestamp() * 1000)
        end_ms = int(end.timestamp() * 1000)
        resource_filter = self._resource_filter(resource_id)

        results: list[MetricSeries] = []

        for metric_name in metric_names:
            try:
                payload = {
                    "data": {
                        "type": "timeseries_request",
                        "attributes": {
                            "formulas": [{"formula": "a"}],
                            "from": start_ms,
                            "to": end_ms,
                            "queries": [
                                {
                                    "data_source": "metrics",
                                    "name": "a",
                                    "query": f"avg:{metric_name}{{{resource_filter}}}",
                                }
                            ],
                        },
                    }
                }

                resp = self._request("POST", "/api/v2/query/timeseries", json=payload)

                # Parse response — Datadog v2 timeseries response structure:
                # data.attributes.series[].{unit, values[], times[]}
                series_list = (
                    resp.get("data", {})
                    .get("attributes", {})
                    .get("series", [])
                )

                for series_data in series_list:
                    unit = ""
                    unit_info = series_data.get("unit")
                    if unit_info and isinstance(unit_info, list) and len(unit_info) > 0:
                        unit = unit_info[0].get("name", "") if isinstance(unit_info[0], dict) else str(unit_info[0])

                    # Datadog returns times as epoch milliseconds and values
                    # nested under series → each group has values list
                    timestamps: list[datetime] = []
                    values: list[float] = []

                    times_raw = resp.get("data", {}).get("attributes", {}).get("times", [])
                    # Values are per-series; pick the first group's pointlist
                    group_values = series_data.get("values", [])

                    for i, ts_ms in enumerate(times_raw):
                        ts = datetime.fromtimestamp(ts_ms / 1000)
                        timestamps.append(ts)
                        if i < len(group_values):
                            val = group_values[i]
                            values.append(float(val) if val is not None else 0.0)

                    results.append(
                        MetricSeries(
                            resource_id=resource_id,
                            metric_name=metric_name,
                            namespace="datadog",
                            timestamps=timestamps,
                            values=values,
                            unit=unit,
                        )
                    )

                # If no series were returned, add an empty MetricSeries
                if not series_list:
                    results.append(
                        MetricSeries(
                            resource_id=resource_id,
                            metric_name=metric_name,
                            namespace="datadog",
                        )
                    )

            except Exception:
                logger.warning(
                    "Failed to query Datadog metric %s for %s",
                    metric_name,
                    resource_id,
                    exc_info=True,
                )
                # Return empty series for this metric so the caller knows it was attempted
                results.append(
                    MetricSeries(
                        resource_id=resource_id,
                        metric_name=metric_name,
                        namespace="datadog",
                    )
                )

        return results

    def list_active_alerts(self) -> list[AlertPayload]:
        """List active Datadog monitors in Alert or Warn state.

        Uses the v1 Monitor API (``GET /api/v1/monitor``) filtered to
        Alert and Warn states.  Returns at most 100 monitors.
        """
        try:
            monitors = self._request(
                "GET",
                "/api/v1/monitor",
                params={
                    "monitor_tags": "*",
                    "states": "Alert,Warn",
                    "page_size": 100,
                },
            )

            # Response is a list of monitor objects at top level
            if not isinstance(monitors, list):
                monitors = monitors.get("monitors", [])

            alerts: list[AlertPayload] = []
            for monitor in monitors[:100]:
                state = monitor.get("overall_state", "")
                severity = _STATE_SEVERITY_MAP.get(state, "medium")

                # Extract resource hint from tags (look for host: or instance: tags)
                resource_hint = ""
                tags = monitor.get("tags", [])
                for tag in tags:
                    if isinstance(tag, str):
                        if tag.startswith("host:") or tag.startswith("instance:"):
                            resource_hint = tag.split(":", 1)[1]
                            break

                alerts.append(
                    AlertPayload(
                        source="datadog",
                        external_id=str(monitor.get("id", "")),
                        severity=severity,
                        title=monitor.get("name", "Untitled Monitor"),
                        description=monitor.get("message", ""),
                        resource_hint=resource_hint,
                        tags={
                            t.split(":", 1)[0]: t.split(":", 1)[1]
                            for t in tags
                            if isinstance(t, str) and ":" in t
                        },
                        raw=monitor,
                    )
                )

            return alerts

        except Exception:
            logger.error("Failed to list active Datadog alerts", exc_info=True)
            return []

    def query_logs(
        self,
        query: str,
        start: datetime,
        end: datetime,
        limit: int = 100,
    ) -> list[LogEntry]:
        """Search Datadog logs using the v2 Log Events API.

        Args:
            query: Datadog log query string.
            start: Start of time range.
            end: End of time range.
            limit: Maximum number of log entries (capped at 100).

        Returns:
            List of LogEntry results, sorted by timestamp descending.
        """
        try:
            payload = {
                "filter": {
                    "query": query,
                    "from": start.isoformat(),
                    "to": end.isoformat(),
                },
                "sort": "-timestamp",
                "page": {"limit": min(limit, 100)},
            }

            resp = self._request("POST", "/api/v2/logs/events/search", json=payload)

            logs: list[LogEntry] = []
            for entry in resp.get("data", []):
                attrs = entry.get("attributes", {})

                # Parse timestamp
                ts_raw = attrs.get("timestamp")
                if isinstance(ts_raw, str):
                    try:
                        ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
                    except ValueError:
                        ts = datetime.now()
                elif isinstance(ts_raw, (int, float)):
                    ts = datetime.fromtimestamp(ts_raw / 1000)
                else:
                    ts = datetime.now()

                message = attrs.get("message") or attrs.get("content", "")
                level = attrs.get("status", "").lower()
                source = attrs.get("service", "")

                # Collect additional fields for context
                fields: dict[str, str] = {}
                for key in ("host", "service", "source", "status"):
                    val = attrs.get(key)
                    if val:
                        fields[key] = str(val)

                logs.append(
                    LogEntry(
                        timestamp=ts,
                        message=str(message),
                        level=level,
                        source=source,
                        fields=fields,
                    )
                )

            return logs

        except Exception:
            logger.error("Failed to query Datadog logs", exc_info=True)
            return []

    def health_check(self) -> bool:
        """Validate Datadog API credentials.

        Uses the v1 validate endpoint (``GET /api/v1/validate``).
        Returns True if the API key is valid, False otherwise.
        """
        try:
            self._request("GET", "/api/v1/validate")
            return True
        except Exception:
            logger.warning("Datadog health check failed", exc_info=True)
            return False
