"""Tests for the Datadog monitoring provider."""

import logging
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from agenticops.integrations.base import AlertPayload, LogEntry, MetricSeries
from agenticops.integrations.datadog_provider import (
    DatadogProvider,
    _INSTANCE_ID_RE,
    _STATE_SEVERITY_MAP,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def provider():
    """Return a DatadogProvider with test credentials."""
    return DatadogProvider(api_key="test-api-key", app_key="test-app-key")


@pytest.fixture
def custom_site_provider():
    """Return a DatadogProvider pointed at a custom site."""
    return DatadogProvider(api_key="k", app_key="a", site="us5.datadoghq.com")


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------

class TestInit:
    def test_default_site(self, provider: DatadogProvider):
        assert provider.base_url == "https://api.datadoghq.com"
        assert provider._headers["DD-API-KEY"] == "test-api-key"
        assert provider._headers["DD-APPLICATION-KEY"] == "test-app-key"
        assert provider.name == "datadog"

    def test_custom_site(self, custom_site_provider: DatadogProvider):
        assert custom_site_provider.base_url == "https://api.us5.datadoghq.com"

    def test_missing_httpx_raises(self):
        with patch("agenticops.integrations.datadog_provider.httpx", None):
            with pytest.raises(ImportError, match="httpx is required"):
                DatadogProvider(api_key="k", app_key="a")


# ---------------------------------------------------------------------------
# _resource_filter
# ---------------------------------------------------------------------------

class TestResourceFilter:
    def test_ec2_instance_id(self):
        assert DatadogProvider._resource_filter("i-0abc1234def56789a") == "instance:i-0abc1234def56789a"

    def test_hostname(self):
        assert DatadogProvider._resource_filter("web-server-01") == "host:web-server-01"

    def test_short_instance_id(self):
        assert DatadogProvider._resource_filter("i-01234567") == "instance:i-01234567"

    def test_instance_id_regex_no_match(self):
        # Should not match (too short / wrong prefix)
        assert not _INSTANCE_ID_RE.match("x-0abc1234")
        assert not _INSTANCE_ID_RE.match("i-short")


# ---------------------------------------------------------------------------
# _request helper
# ---------------------------------------------------------------------------

class TestRequest:
    def test_success(self, provider: DatadogProvider):
        mock_response = MagicMock()
        mock_response.json.return_value = {"ok": True}
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.request.return_value = mock_response

        with patch("agenticops.integrations.datadog_provider.httpx") as mock_httpx:
            mock_httpx.Client.return_value = mock_client
            mock_httpx.HTTPStatusError = Exception
            mock_httpx.HTTPError = Exception
            result = provider._request("GET", "/api/v1/validate")

        assert result == {"ok": True}
        mock_client.request.assert_called_once()

    def test_http_status_error(self, provider: DatadogProvider):
        import httpx as real_httpx

        mock_response = MagicMock()
        mock_response.status_code = 403
        error = real_httpx.HTTPStatusError("forbidden", request=MagicMock(), response=mock_response)
        mock_response.raise_for_status.side_effect = error

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.request.return_value = mock_response

        with patch("agenticops.integrations.datadog_provider.httpx") as mock_httpx:
            mock_httpx.Client.return_value = mock_client
            mock_httpx.HTTPStatusError = real_httpx.HTTPStatusError
            mock_httpx.HTTPError = real_httpx.HTTPError
            with pytest.raises(real_httpx.HTTPStatusError):
                provider._request("GET", "/api/v1/validate")


# ---------------------------------------------------------------------------
# health_check
# ---------------------------------------------------------------------------

class TestHealthCheck:
    def test_healthy(self, provider: DatadogProvider):
        with patch.object(provider, "_request", return_value={"valid": True}):
            assert provider.health_check() is True

    def test_unhealthy(self, provider: DatadogProvider):
        with patch.object(provider, "_request", side_effect=Exception("boom")):
            assert provider.health_check() is False


# ---------------------------------------------------------------------------
# list_active_alerts
# ---------------------------------------------------------------------------

class TestListActiveAlerts:
    def test_returns_alerts(self, provider: DatadogProvider):
        monitors = [
            {
                "id": 12345,
                "name": "High CPU",
                "overall_state": "Alert",
                "message": "CPU > 90%",
                "tags": ["host:web-1", "env:prod"],
            },
            {
                "id": 67890,
                "name": "Disk Warning",
                "overall_state": "Warn",
                "message": "Disk > 80%",
                "tags": ["instance:i-0abc1234def56789a", "team:infra"],
            },
        ]
        with patch.object(provider, "_request", return_value=monitors):
            alerts = provider.list_active_alerts()

        assert len(alerts) == 2
        assert isinstance(alerts[0], AlertPayload)
        assert alerts[0].severity == "critical"
        assert alerts[0].resource_hint == "web-1"
        assert alerts[0].title == "High CPU"
        assert alerts[0].tags["env"] == "prod"

        assert alerts[1].severity == "high"
        assert alerts[1].resource_hint == "i-0abc1234def56789a"

    def test_dict_response(self, provider: DatadogProvider):
        """API may return monitors wrapped in a dict."""
        resp = {"monitors": [{"id": 1, "name": "test", "overall_state": "OK", "message": "", "tags": []}]}
        with patch.object(provider, "_request", return_value=resp):
            alerts = provider.list_active_alerts()
        assert len(alerts) == 1

    def test_empty_on_error(self, provider: DatadogProvider):
        with patch.object(provider, "_request", side_effect=Exception("fail")):
            assert provider.list_active_alerts() == []

    def test_no_tags(self, provider: DatadogProvider):
        monitors = [{"id": 1, "name": "x", "overall_state": "No Data", "message": "", "tags": []}]
        with patch.object(provider, "_request", return_value=monitors):
            alerts = provider.list_active_alerts()
        assert alerts[0].severity == "medium"
        assert alerts[0].resource_hint == ""


# ---------------------------------------------------------------------------
# query_metrics
# ---------------------------------------------------------------------------

class TestQueryMetrics:
    def test_single_metric(self, provider: DatadogProvider):
        api_response = {
            "data": {
                "attributes": {
                    "series": [
                        {"unit": [{"name": "percent"}], "values": [10.0, 20.0, 30.0]}
                    ],
                    "times": [1000000, 2000000, 3000000],
                }
            }
        }
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        end = datetime(2026, 1, 2, tzinfo=timezone.utc)

        with patch.object(provider, "_request", return_value=api_response):
            results = provider.query_metrics("web-1", ["system.cpu.user"], start, end)

        assert len(results) == 1
        assert results[0].metric_name == "system.cpu.user"
        assert results[0].values == [10.0, 20.0, 30.0]
        assert results[0].unit == "percent"
        assert results[0].namespace == "datadog"

    def test_empty_series(self, provider: DatadogProvider):
        api_response = {"data": {"attributes": {"series": [], "times": []}}}
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        end = datetime(2026, 1, 2, tzinfo=timezone.utc)

        with patch.object(provider, "_request", return_value=api_response):
            results = provider.query_metrics("web-1", ["system.cpu.user"], start, end)

        assert len(results) == 1
        assert results[0].values == []

    def test_metric_error_returns_empty_series(self, provider: DatadogProvider):
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        end = datetime(2026, 1, 2, tzinfo=timezone.utc)

        with patch.object(provider, "_request", side_effect=Exception("timeout")):
            results = provider.query_metrics("web-1", ["bad.metric"], start, end)

        assert len(results) == 1
        assert results[0].metric_name == "bad.metric"
        assert results[0].values == []

    def test_multiple_metrics(self, provider: DatadogProvider):
        api_response = {"data": {"attributes": {"series": [{"unit": [], "values": [1.0]}], "times": [1000]}}}
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        end = datetime(2026, 1, 2, tzinfo=timezone.utc)

        with patch.object(provider, "_request", return_value=api_response):
            results = provider.query_metrics("web-1", ["m1", "m2"], start, end)

        assert len(results) == 2

    def test_none_values_treated_as_zero(self, provider: DatadogProvider):
        api_response = {
            "data": {
                "attributes": {
                    "series": [{"unit": [], "values": [None, 5.0, None]}],
                    "times": [1000, 2000, 3000],
                }
            }
        }
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        end = datetime(2026, 1, 2, tzinfo=timezone.utc)

        with patch.object(provider, "_request", return_value=api_response):
            results = provider.query_metrics("web-1", ["m1"], start, end)

        assert results[0].values == [0.0, 5.0, 0.0]

    def test_ec2_instance_id_filter(self, provider: DatadogProvider):
        """Ensure instance ID is passed as instance: tag filter."""
        api_response = {"data": {"attributes": {"series": [], "times": []}}}
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        end = datetime(2026, 1, 2, tzinfo=timezone.utc)

        with patch.object(provider, "_request", return_value=api_response) as mock_req:
            provider.query_metrics("i-0abc1234def56789a", ["m1"], start, end)

        call_kwargs = mock_req.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        query_str = payload["data"]["attributes"]["queries"][0]["query"]
        assert "instance:i-0abc1234def56789a" in query_str


# ---------------------------------------------------------------------------
# query_logs
# ---------------------------------------------------------------------------

class TestQueryLogs:
    def test_returns_logs(self, provider: DatadogProvider):
        api_response = {
            "data": [
                {
                    "attributes": {
                        "timestamp": "2026-01-01T00:00:00Z",
                        "message": "Error occurred",
                        "status": "error",
                        "service": "web-api",
                        "host": "web-1",
                        "source": "nginx",
                    }
                },
            ]
        }
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        end = datetime(2026, 1, 2, tzinfo=timezone.utc)

        with patch.object(provider, "_request", return_value=api_response):
            logs = provider.query_logs("service:web-api status:error", start, end)

        assert len(logs) == 1
        assert isinstance(logs[0], LogEntry)
        assert logs[0].message == "Error occurred"
        assert logs[0].level == "error"
        assert logs[0].source == "web-api"
        assert logs[0].fields["host"] == "web-1"

    def test_numeric_timestamp(self, provider: DatadogProvider):
        api_response = {
            "data": [
                {"attributes": {"timestamp": 1735689600000, "message": "hello", "status": "info", "service": "s"}}
            ]
        }
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        end = datetime(2026, 1, 2, tzinfo=timezone.utc)

        with patch.object(provider, "_request", return_value=api_response):
            logs = provider.query_logs("*", start, end)

        assert len(logs) == 1
        assert isinstance(logs[0].timestamp, datetime)

    def test_empty_on_error(self, provider: DatadogProvider):
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        end = datetime(2026, 1, 2, tzinfo=timezone.utc)

        with patch.object(provider, "_request", side_effect=Exception("fail")):
            assert provider.query_logs("*", start, end) == []

    def test_limit_capped(self, provider: DatadogProvider):
        api_response = {"data": []}
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        end = datetime(2026, 1, 2, tzinfo=timezone.utc)

        with patch.object(provider, "_request", return_value=api_response) as mock_req:
            provider.query_logs("*", start, end, limit=500)

        call_kwargs = mock_req.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert payload["page"]["limit"] == 100


# ---------------------------------------------------------------------------
# State severity mapping
# ---------------------------------------------------------------------------

class TestSeverityMapping:
    def test_all_states_mapped(self):
        assert _STATE_SEVERITY_MAP["Alert"] == "critical"
        assert _STATE_SEVERITY_MAP["Warn"] == "high"
        assert _STATE_SEVERITY_MAP["No Data"] == "medium"
        assert _STATE_SEVERITY_MAP["OK"] == "low"
