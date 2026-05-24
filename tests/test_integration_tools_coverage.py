"""Targeted tests for src/agenticops/tools/integration_tools.py — covering low-coverage paths."""

import json
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# _truncate helper
# ---------------------------------------------------------------------------

class TestTruncate:
    def test_short_text_unchanged(self):
        from agenticops.tools.integration_tools import _truncate
        assert _truncate("hello", 100) == "hello"

    def test_long_text_truncated(self):
        from agenticops.tools.integration_tools import _truncate
        result = _truncate("a" * 200, 50)
        assert len(result) < 200
        assert "truncated" in result


# ---------------------------------------------------------------------------
# _store_metrics helper
# ---------------------------------------------------------------------------

class TestStoreMetrics:
    @patch("agenticops.models.get_db_session")
    @patch("agenticops.models.MetricDataPoint")
    def test_stores_points(self, mock_mdp, mock_get_session):
        from agenticops.tools.integration_tools import _store_metrics

        mock_session = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_session)
        mock_ctx.__exit__ = MagicMock(return_value=False)
        mock_get_session.return_value = mock_ctx

        series = MagicMock()
        series.resource_id = "r-1"
        series.namespace = "AWS/EC2"
        series.metric_name = "CPU"
        series.timestamps = [datetime(2025, 1, 1, tzinfo=timezone.utc)]
        series.values = [42.0]
        series.unit = "Percent"

        _store_metrics([series])
        mock_session.add.assert_called_once()

    @patch("agenticops.models.get_db_session", side_effect=Exception("db fail"))
    def test_failure_logged_not_raised(self, mock_get):
        from agenticops.tools.integration_tools import _store_metrics
        # Should not raise
        _store_metrics([MagicMock()])


# ---------------------------------------------------------------------------
# query_provider_metrics
# ---------------------------------------------------------------------------

class TestQueryProviderMetrics:
    @patch("agenticops.integrations.list_provider_names")
    @patch("agenticops.integrations.get_provider")
    def test_provider_not_found(self, mock_get, mock_list):
        mock_get.return_value = None
        mock_list.return_value = [{"name": "datadog", "status": "active"}]

        from agenticops.tools.integration_tools import query_provider_metrics
        result = json.loads(query_provider_metrics.__wrapped__(
            provider="unknown", resource_id="r-1", metric_names="CPU"
        ))
        assert "error" in result
        assert "datadog" in result["available_providers"]

    @patch("agenticops.tools.integration_tools.settings")
    @patch("agenticops.integrations.get_provider")
    def test_successful_query(self, mock_get, mock_settings):
        mock_settings.metric_storage_enabled = False

        series = MagicMock()
        series.resource_id = "r-1"
        series.metric_name = "CPU"
        series.namespace = "AWS/EC2"
        series.unit = "Percent"
        series.count = 1
        series.latest_value = 50.0
        series.timestamps = [datetime(2025, 1, 1, tzinfo=timezone.utc)]
        series.values = [50.0]
        series.tags = {}

        prov = MagicMock()
        prov.query_metrics.return_value = [series]
        mock_get.return_value = prov

        from agenticops.tools.integration_tools import query_provider_metrics
        result = json.loads(query_provider_metrics.__wrapped__(
            provider="cw", resource_id="r-1", metric_names="CPU", hours=1
        ))
        assert len(result) == 1
        assert result[0]["metric_name"] == "CPU"

    @patch("agenticops.tools.integration_tools._store_metrics")
    @patch("agenticops.tools.integration_tools.settings")
    @patch("agenticops.integrations.get_provider")
    def test_with_storage_enabled(self, mock_get, mock_settings, mock_store):
        mock_settings.metric_storage_enabled = True

        series = MagicMock()
        series.resource_id = "r-1"
        series.metric_name = "CPU"
        series.namespace = "NS"
        series.unit = "Count"
        series.count = 0
        series.latest_value = 10
        series.timestamps = []
        series.values = []
        series.tags = {}

        prov = MagicMock()
        prov.query_metrics.return_value = [series]
        mock_get.return_value = prov

        from agenticops.tools.integration_tools import query_provider_metrics
        query_provider_metrics.__wrapped__(
            provider="cw", resource_id="r-1", metric_names="CPU"
        )
        mock_store.assert_called_once()

    @patch("agenticops.integrations.get_provider", side_effect=Exception("boom"))
    def test_exception_handling(self, mock_get):
        from agenticops.tools.integration_tools import query_provider_metrics
        result = json.loads(query_provider_metrics.__wrapped__(
            provider="cw", resource_id="r-1", metric_names="CPU"
        ))
        assert "error" in result


# ---------------------------------------------------------------------------
# query_provider_logs
# ---------------------------------------------------------------------------

class TestQueryProviderLogs:
    @patch("agenticops.integrations.list_provider_names")
    @patch("agenticops.integrations.get_provider")
    def test_provider_not_found(self, mock_get, mock_list):
        mock_get.return_value = None
        mock_list.return_value = []

        from agenticops.tools.integration_tools import query_provider_logs
        result = json.loads(query_provider_logs.__wrapped__(
            provider="unknown", query="error"
        ))
        assert "error" in result

    @patch("agenticops.integrations.get_provider")
    def test_successful_query(self, mock_get):
        entry = MagicMock()
        entry.timestamp = datetime(2025, 1, 1, tzinfo=timezone.utc)
        entry.message = "test log"
        entry.level = "ERROR"
        entry.source = "app"
        entry.fields = {}

        prov = MagicMock()
        prov.query_logs.return_value = [entry]
        mock_get.return_value = prov

        from agenticops.tools.integration_tools import query_provider_logs
        result = json.loads(query_provider_logs.__wrapped__(
            provider="datadog", query="error", hours=2, limit=10
        ))
        assert len(result) == 1
        assert result[0]["level"] == "ERROR"

    @patch("agenticops.integrations.get_provider", side_effect=Exception("crash"))
    def test_exception_handling(self, mock_get):
        from agenticops.tools.integration_tools import query_provider_logs
        result = json.loads(query_provider_logs.__wrapped__(
            provider="x", query="q"
        ))
        assert "error" in result


# ---------------------------------------------------------------------------
# list_provider_alerts
# ---------------------------------------------------------------------------

class TestListProviderAlerts:
    @patch("agenticops.integrations.get_providers")
    def test_all_providers(self, mock_get_all):
        alert = MagicMock()
        alert.external_id = "a-1"
        alert.severity = "critical"
        alert.title = "CPU spike"
        alert.description = "CPU > 90%"
        alert.resource_hint = "i-123"
        alert.tags = {}

        prov = MagicMock()
        prov.name = "datadog"
        prov.list_active_alerts.return_value = [alert]
        mock_get_all.return_value = [prov]

        from agenticops.tools.integration_tools import list_provider_alerts
        result = json.loads(list_provider_alerts.__wrapped__(provider="all"))
        assert len(result) == 1
        assert result[0]["severity"] == "critical"

    @patch("agenticops.integrations.get_providers")
    def test_all_providers_with_failure(self, mock_get_all):
        prov = MagicMock()
        prov.name = "broken"
        prov.list_active_alerts.side_effect = RuntimeError("timeout")
        mock_get_all.return_value = [prov]

        from agenticops.tools.integration_tools import list_provider_alerts
        result = json.loads(list_provider_alerts.__wrapped__(provider="all"))
        assert any("error" in a for a in result)

    @patch("agenticops.integrations.list_provider_names")
    @patch("agenticops.integrations.get_provider")
    def test_specific_provider_not_found(self, mock_get, mock_list):
        mock_get.return_value = None
        mock_list.return_value = [{"name": "cw", "status": "active"}]

        from agenticops.tools.integration_tools import list_provider_alerts
        result = json.loads(list_provider_alerts.__wrapped__(provider="missing"))
        assert "error" in result

    @patch("agenticops.integrations.get_provider")
    def test_specific_provider_success(self, mock_get):
        alert = MagicMock()
        alert.external_id = "x-1"
        alert.severity = "warning"
        alert.title = "Disk"
        alert.description = "low"
        alert.resource_hint = "vol-1"
        alert.tags = {}

        prov = MagicMock()
        prov.name = "cw"
        prov.list_active_alerts.return_value = [alert]
        mock_get.return_value = prov

        from agenticops.tools.integration_tools import list_provider_alerts
        result = json.loads(list_provider_alerts.__wrapped__(provider="cw"))
        assert len(result) == 1

    @patch("agenticops.integrations.get_provider", side_effect=Exception("fail"))
    def test_exception_handling(self, mock_get):
        from agenticops.tools.integration_tools import list_provider_alerts
        result = json.loads(list_provider_alerts.__wrapped__(provider="x"))
        assert "error" in result


# ---------------------------------------------------------------------------
# list_monitoring_providers
# ---------------------------------------------------------------------------

class TestListMonitoringProviders:
    @patch("agenticops.integrations.list_provider_names")
    def test_success(self, mock_list):
        mock_list.return_value = [{"name": "datadog", "status": "active"}]
        from agenticops.tools.integration_tools import list_monitoring_providers
        result = json.loads(list_monitoring_providers.__wrapped__())
        assert result[0]["name"] == "datadog"

    @patch("agenticops.integrations.list_provider_names", side_effect=Exception("boom"))
    def test_exception(self, mock_list):
        from agenticops.tools.integration_tools import list_monitoring_providers
        result = json.loads(list_monitoring_providers.__wrapped__())
        assert "error" in result


# ---------------------------------------------------------------------------
# store_metric_snapshot
# ---------------------------------------------------------------------------

class TestStoreMetricSnapshot:
    @patch("agenticops.models.get_db_session")
    @patch("agenticops.models.MetricDataPoint")
    def test_success(self, mock_mdp, mock_get_session):
        mock_session = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_session)
        mock_ctx.__exit__ = MagicMock(return_value=False)
        mock_get_session.return_value = mock_ctx

        from agenticops.tools.integration_tools import store_metric_snapshot
        result = json.loads(store_metric_snapshot.__wrapped__(
            resource_id="r-1", metric_name="CPU", value=75.0,
            namespace="AWS/EC2", unit="Percent"
        ))
        assert result["status"] == "stored"
        assert result["value"] == 75.0

    @patch("agenticops.models.get_db_session", side_effect=Exception("db fail"))
    def test_failure(self, mock_get):
        from agenticops.tools.integration_tools import store_metric_snapshot
        result = json.loads(store_metric_snapshot.__wrapped__(
            resource_id="r-1", metric_name="CPU", value=10.0
        ))
        assert "error" in result
