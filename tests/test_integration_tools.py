"""Tests for agenticops.tools.integration_tools — targeting uncovered lines."""

import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

from agenticops.tools.integration_tools import (
    _truncate,
    _store_metrics,
    query_provider_metrics,
    query_provider_logs,
    list_provider_alerts,
    list_monitoring_providers,
    store_metric_snapshot,
)


# ---------------------------------------------------------------------------
# _truncate
# ---------------------------------------------------------------------------


class TestTruncate:
    def test_short_text_unchanged(self):
        assert _truncate("hello", 100) == "hello"

    def test_exact_limit_unchanged(self):
        text = "a" * 100
        assert _truncate(text, 100) == text

    def test_long_text_truncated(self):
        text = "a" * 200
        result = _truncate(text, 100)
        assert result.startswith("a" * 100)
        assert "truncated" in result


# ---------------------------------------------------------------------------
# _store_metrics
# ---------------------------------------------------------------------------


class TestStoreMetrics:
    @patch("agenticops.tools.integration_tools.logger")
    def test_store_metrics_success(self, mock_logger):
        """Storing metrics with valid series list."""
        mock_series = MagicMock()
        mock_series.timestamps = [datetime(2025, 1, 1), datetime(2025, 1, 2)]
        mock_series.values = [10.0, 20.0]
        mock_series.resource_id = "i-12345"
        mock_series.namespace = "AWS/EC2"
        mock_series.metric_name = "CPUUtilization"
        mock_series.unit = "Percent"

        mock_session = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_session)
        mock_ctx.__exit__ = MagicMock(return_value=False)

        with patch("agenticops.models.get_db_session", return_value=mock_ctx):
            with patch("agenticops.models.MetricDataPoint") as MockPoint:
                _store_metrics([mock_series])
                assert MockPoint.call_count == 2
                assert mock_session.add.call_count == 2

    @patch("agenticops.tools.integration_tools.logger")
    def test_store_metrics_failure_logs_warning(self, mock_logger):
        """Failed storage logs warning but doesn't raise."""
        # Simulate db error by patching get_db_session to raise
        with patch(
            "agenticops.models.get_db_session",
            side_effect=Exception("db connection failed"),
        ):
            mock_series = MagicMock()
            mock_series.timestamps = [datetime(2025, 1, 1)]
            mock_series.values = [10.0]
            mock_series.resource_id = "i-1"
            mock_series.namespace = "AWS/EC2"
            mock_series.metric_name = "CPU"
            mock_series.unit = "Percent"
            # Should not raise
            _store_metrics([mock_series])
            mock_logger.warning.assert_called()


# ---------------------------------------------------------------------------
# query_provider_metrics
# ---------------------------------------------------------------------------


class TestQueryProviderMetrics:
    @patch("agenticops.tools.integration_tools.settings")
    def test_provider_not_found(self, mock_settings):
        """Returns error when provider doesn't exist."""
        mock_settings.metric_storage_enabled = False
        with patch(
            "agenticops.integrations.get_provider", return_value=None
        ), patch(
            "agenticops.integrations.list_provider_names",
            return_value=[{"name": "cloudwatch", "status": "active"}],
        ):
            result = query_provider_metrics(
                provider="nonexistent",
                resource_id="i-123",
                metric_names="CPUUtilization",
                hours=1,
            )
            data = json.loads(result)
            assert "error" in data
            assert "nonexistent" in data["error"]
            assert "cloudwatch" in data["available_providers"]

    @patch("agenticops.tools.integration_tools.settings")
    def test_successful_query(self, mock_settings):
        """Successful metric query returns formatted results."""
        mock_settings.metric_storage_enabled = False

        mock_series = MagicMock()
        mock_series.resource_id = "i-123"
        mock_series.metric_name = "CPUUtilization"
        mock_series.namespace = "AWS/EC2"
        mock_series.unit = "Percent"
        mock_series.count = 2
        mock_series.latest_value = 45.0
        mock_series.timestamps = [datetime(2025, 1, 1, 0, 0), datetime(2025, 1, 1, 1, 0)]
        mock_series.values = [40.0, 45.0]
        mock_series.tags = {"env": "prod"}

        mock_provider = MagicMock()
        mock_provider.query_metrics.return_value = [mock_series]

        with patch(
            "agenticops.integrations.get_provider", return_value=mock_provider
        ):
            result = query_provider_metrics(
                provider="cloudwatch",
                resource_id="i-123",
                metric_names="CPUUtilization",
                hours=1,
            )
            data = json.loads(result)
            assert len(data) == 1
            assert data[0]["metric_name"] == "CPUUtilization"
            assert data[0]["latest_value"] == 45.0

    @patch("agenticops.tools.integration_tools.settings")
    def test_successful_query_with_storage(self, mock_settings):
        """Metrics stored when metric_storage_enabled is True."""
        mock_settings.metric_storage_enabled = True

        mock_series = MagicMock()
        mock_series.resource_id = "i-123"
        mock_series.metric_name = "CPUUtilization"
        mock_series.namespace = "AWS/EC2"
        mock_series.unit = "Percent"
        mock_series.count = 1
        mock_series.latest_value = 50.0
        mock_series.timestamps = [datetime(2025, 1, 1)]
        mock_series.values = [50.0]
        mock_series.tags = {}

        mock_provider = MagicMock()
        mock_provider.query_metrics.return_value = [mock_series]

        with patch(
            "agenticops.integrations.get_provider", return_value=mock_provider
        ), patch(
            "agenticops.tools.integration_tools._store_metrics"
        ) as mock_store:
            result = query_provider_metrics(
                provider="cloudwatch",
                resource_id="i-123",
                metric_names="CPUUtilization",
                hours=1,
            )
            mock_store.assert_called_once_with([mock_series])

    def test_exception_returns_error(self):
        """Exceptions are caught and returned as error JSON."""
        with patch(
            "agenticops.integrations.get_provider",
            side_effect=RuntimeError("connection failed"),
        ):
            result = query_provider_metrics(
                provider="datadog",
                resource_id="host1",
                metric_names="cpu",
                hours=1,
            )
            data = json.loads(result)
            assert "error" in data
            assert "connection failed" in data["error"]


# ---------------------------------------------------------------------------
# query_provider_logs
# ---------------------------------------------------------------------------


class TestQueryProviderLogs:
    def test_provider_not_found(self):
        with patch(
            "agenticops.integrations.get_provider", return_value=None
        ), patch(
            "agenticops.integrations.list_provider_names",
            return_value=[{"name": "datadog", "status": "active"}],
        ):
            result = query_provider_logs(
                provider="splunk", query="error", hours=1, limit=10
            )
            data = json.loads(result)
            assert "error" in data
            assert "splunk" in data["error"]

    def test_successful_log_query(self):
        mock_entry = MagicMock()
        mock_entry.timestamp = datetime(2025, 1, 1, 12, 0)
        mock_entry.message = "Something went wrong"
        mock_entry.level = "ERROR"
        mock_entry.source = "/var/log/app.log"
        mock_entry.fields = {"trace_id": "abc123"}

        mock_provider = MagicMock()
        mock_provider.query_logs.return_value = [mock_entry]

        with patch(
            "agenticops.integrations.get_provider", return_value=mock_provider
        ):
            result = query_provider_logs(
                provider="cloudwatch", query="ERROR", hours=2, limit=50
            )
            data = json.loads(result)
            assert len(data) == 1
            assert data[0]["level"] == "ERROR"
            assert data[0]["message"] == "Something went wrong"

    def test_exception_returns_error(self):
        with patch(
            "agenticops.integrations.get_provider",
            side_effect=Exception("timeout"),
        ):
            result = query_provider_logs(
                provider="cloudwatch", query="*", hours=1, limit=10
            )
            data = json.loads(result)
            assert "error" in data


# ---------------------------------------------------------------------------
# list_provider_alerts
# ---------------------------------------------------------------------------


class TestListProviderAlerts:
    def test_all_providers(self):
        mock_alert = MagicMock()
        mock_alert.external_id = "alert-1"
        mock_alert.severity = "critical"
        mock_alert.title = "High CPU"
        mock_alert.description = "CPU > 90%"
        mock_alert.resource_hint = "i-123"
        mock_alert.tags = {"env": "prod"}

        mock_provider = MagicMock()
        mock_provider.name = "cloudwatch"
        mock_provider.list_active_alerts.return_value = [mock_alert]

        with patch(
            "agenticops.integrations.get_providers", return_value=[mock_provider]
        ):
            result = list_provider_alerts(provider="all")
            data = json.loads(result)
            assert len(data) == 1
            assert data[0]["title"] == "High CPU"
            assert data[0]["provider"] == "cloudwatch"

    def test_all_providers_with_failure(self):
        """One provider fails, others succeed."""
        mock_provider_ok = MagicMock()
        mock_provider_ok.name = "cloudwatch"
        mock_provider_ok.list_active_alerts.return_value = []

        mock_provider_fail = MagicMock()
        mock_provider_fail.name = "datadog"
        mock_provider_fail.list_active_alerts.side_effect = Exception("auth error")

        with patch(
            "agenticops.integrations.get_providers",
            return_value=[mock_provider_ok, mock_provider_fail],
        ):
            result = list_provider_alerts(provider="all")
            data = json.loads(result)
            assert len(data) == 1  # error entry from datadog
            assert data[0]["provider"] == "datadog"
            assert "error" in data[0]

    def test_specific_provider_not_found(self):
        with patch(
            "agenticops.integrations.get_provider", return_value=None
        ), patch(
            "agenticops.integrations.list_provider_names",
            return_value=[{"name": "cloudwatch", "status": "active"}],
        ):
            result = list_provider_alerts(provider="unknown")
            data = json.loads(result)
            assert "error" in data

    def test_specific_provider_alerts(self):
        mock_alert = MagicMock()
        mock_alert.external_id = "a-1"
        mock_alert.severity = "warning"
        mock_alert.title = "Disk Space"
        mock_alert.description = "Low disk"
        mock_alert.resource_hint = "vol-123"
        mock_alert.tags = {}

        mock_provider = MagicMock()
        mock_provider.name = "cloudwatch"
        mock_provider.list_active_alerts.return_value = [mock_alert]

        with patch(
            "agenticops.integrations.get_provider", return_value=mock_provider
        ):
            result = list_provider_alerts(provider="cloudwatch")
            data = json.loads(result)
            assert len(data) == 1
            assert data[0]["severity"] == "warning"

    def test_exception_returns_error(self):
        with patch(
            "agenticops.integrations.get_providers",
            side_effect=RuntimeError("module error"),
        ):
            result = list_provider_alerts(provider="all")
            data = json.loads(result)
            assert "error" in data


# ---------------------------------------------------------------------------
# list_monitoring_providers
# ---------------------------------------------------------------------------


class TestListMonitoringProviders:
    def test_success(self):
        providers = [
            {"name": "cloudwatch", "status": "active"},
            {"name": "datadog", "status": "inactive"},
        ]
        with patch(
            "agenticops.integrations.list_provider_names", return_value=providers
        ):
            result = list_monitoring_providers()
            data = json.loads(result)
            assert len(data) == 2
            assert data[0]["name"] == "cloudwatch"

    def test_exception_returns_error(self):
        with patch(
            "agenticops.integrations.list_provider_names",
            side_effect=ImportError("no module"),
        ):
            result = list_monitoring_providers()
            data = json.loads(result)
            assert "error" in data


# ---------------------------------------------------------------------------
# store_metric_snapshot
# ---------------------------------------------------------------------------


class TestStoreMetricSnapshot:
    def test_success(self):
        mock_session = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_session)
        mock_ctx.__exit__ = MagicMock(return_value=False)

        with patch("agenticops.models.get_db_session", return_value=mock_ctx), patch(
            "agenticops.models.MetricDataPoint"
        ):
            result = store_metric_snapshot(
                resource_id="i-123",
                metric_name="CPUUtilization",
                value=75.5,
                namespace="AWS/EC2",
                unit="Percent",
            )
            data = json.loads(result)
            assert data["status"] == "stored"
            assert data["value"] == 75.5

    def test_exception_returns_error(self):
        with patch(
            "agenticops.models.get_db_session",
            side_effect=Exception("db error"),
        ):
            result = store_metric_snapshot(
                resource_id="i-123",
                metric_name="CPUUtilization",
                value=50.0,
            )
            data = json.loads(result)
            assert "error" in data
