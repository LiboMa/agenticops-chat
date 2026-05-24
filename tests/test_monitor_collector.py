"""Tests for agenticops.monitor.collector — targeting uncovered lines (23% → higher)."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, PropertyMock

import pytest


def _make_account():
    acct = MagicMock()
    acct.id = 1
    acct.credentials = {"account_id": "123456789012", "role_arn": "arn:x"}
    return acct


def _make_resource(resource_type="EC2", resource_id="i-abc", region="us-east-1"):
    r = MagicMock()
    r.resource_type = resource_type
    r.resource_id = resource_id
    r.region = region
    return r


# ── collect_for_resource ────────────────────────────────────────────

class TestCollectForResource:
    @patch("agenticops.monitor.collector.CloudWatchMonitor")
    def test_collect_and_save(self, MockCW):
        monitor = MagicMock()
        monitor.get_service_metrics.return_value = {"CPUUtilization": [{"value": 50}]}
        monitor.save_metric_data.return_value = 1
        MockCW.return_value = monitor

        from agenticops.monitor.collector import MetricsCollector
        c = MetricsCollector(_make_account())
        c.monitor = monitor

        result = c.collect_for_resource(_make_resource())
        assert "CPUUtilization" in result
        monitor.save_metric_data.assert_called_once()

    @patch("agenticops.monitor.collector.CloudWatchMonitor")
    def test_collect_no_save(self, MockCW):
        monitor = MagicMock()
        monitor.get_service_metrics.return_value = {"CPUUtilization": [{"value": 50}]}
        MockCW.return_value = monitor

        from agenticops.monitor.collector import MetricsCollector
        c = MetricsCollector(_make_account())
        c.monitor = monitor

        result = c.collect_for_resource(_make_resource(), save=False)
        assert "CPUUtilization" in result
        monitor.save_metric_data.assert_not_called()

    @patch("agenticops.monitor.collector.CloudWatchMonitor")
    def test_collect_empty_metrics_no_save(self, MockCW):
        monitor = MagicMock()
        monitor.get_service_metrics.return_value = {}
        MockCW.return_value = monitor

        from agenticops.monitor.collector import MetricsCollector
        c = MetricsCollector(_make_account())
        c.monitor = monitor

        result = c.collect_for_resource(_make_resource(), save=True)
        assert result == {}
        monitor.save_metric_data.assert_not_called()


# ── collect_for_service ─────────────────────────────────────────────

class TestCollectForService:
    @patch("agenticops.monitor.collector.get_session")
    @patch("agenticops.monitor.collector.CloudWatchMonitor")
    def test_collects_for_all_resources(self, MockCW, mock_get_session):
        monitor = MagicMock()
        monitor.get_service_metrics.return_value = {"CPUUtilization": [{"value": 50}]}
        monitor.save_metric_data.return_value = 1
        MockCW.return_value = monitor

        session = MagicMock()
        r1 = _make_resource(resource_id="i-111")
        r2 = _make_resource(resource_id="i-222")
        session.query.return_value.filter_by.return_value.all.return_value = [r1, r2]
        mock_get_session.return_value = session

        from agenticops.monitor.collector import MetricsCollector
        c = MetricsCollector(_make_account())
        c.monitor = monitor

        result = c.collect_for_service("EC2")
        assert "i-111" in result
        assert "i-222" in result
        session.close.assert_called_once()

    @patch("agenticops.monitor.collector.get_session")
    @patch("agenticops.monitor.collector.CloudWatchMonitor")
    def test_with_region_filter(self, MockCW, mock_get_session):
        monitor = MagicMock()
        monitor.get_service_metrics.return_value = {}
        MockCW.return_value = monitor

        session = MagicMock()
        session.query.return_value.filter_by.return_value.filter_by.return_value.all.return_value = []
        mock_get_session.return_value = session

        from agenticops.monitor.collector import MetricsCollector
        c = MetricsCollector(_make_account())
        c.monitor = monitor

        result = c.collect_for_service("EC2", region="us-west-2")
        assert result == {}
        session.close.assert_called_once()

    @patch("agenticops.monitor.collector.get_session")
    @patch("agenticops.monitor.collector.CloudWatchMonitor")
    def test_individual_resource_failure(self, MockCW, mock_get_session):
        monitor = MagicMock()
        monitor.get_service_metrics.side_effect = RuntimeError("timeout")
        monitor.save_metric_data.return_value = 0
        MockCW.return_value = monitor

        session = MagicMock()
        r = _make_resource()
        session.query.return_value.filter_by.return_value.all.return_value = [r]
        mock_get_session.return_value = session

        from agenticops.monitor.collector import MetricsCollector
        c = MetricsCollector(_make_account())
        c.monitor = monitor

        result = c.collect_for_service("EC2")
        assert result == {}  # failed resource not included
        session.close.assert_called_once()


# ── collect_all ─────────────────────────────────────────────────────

class TestCollectAll:
    @patch("agenticops.monitor.collector.get_session")
    @patch("agenticops.monitor.collector.CloudWatchMonitor")
    def test_collects_all_enabled_configs(self, MockCW, mock_get_session):
        monitor = MagicMock()
        monitor.get_service_metrics.return_value = {"Metric1": [{"value": 1}]}
        monitor.save_metric_data.return_value = 1
        MockCW.return_value = monitor

        config1 = MagicMock()
        config1.service_type = "EC2"
        config2 = MagicMock()
        config2.service_type = "Lambda"

        session = MagicMock()
        session.query.return_value.filter_by.return_value.all.side_effect = [
            [config1, config2],  # configs query
            [_make_resource()],  # EC2 resources
            [_make_resource(resource_type="Lambda", resource_id="func-1")],  # Lambda resources
        ]
        mock_get_session.return_value = session

        from agenticops.monitor.collector import MetricsCollector
        c = MetricsCollector(_make_account())
        c.monitor = monitor

        # Patch collect_for_service to avoid nested session issues
        c.collect_for_service = MagicMock(return_value={"res-1": {"Metric1": []}})
        result = c.collect_all()
        assert "EC2" in result
        assert "Lambda" in result
        session.close.assert_called_once()

    @patch("agenticops.monitor.collector.get_session")
    @patch("agenticops.monitor.collector.CloudWatchMonitor")
    def test_no_configs(self, MockCW, mock_get_session):
        session = MagicMock()
        session.query.return_value.filter_by.return_value.all.return_value = []
        mock_get_session.return_value = session

        from agenticops.monitor.collector import MetricsCollector
        c = MetricsCollector(_make_account())

        result = c.collect_all()
        assert result == {}
        session.close.assert_called_once()


# ── get_collection_summary ──────────────────────────────────────────

class TestGetCollectionSummary:
    @patch("agenticops.monitor.collector.get_session")
    @patch("agenticops.monitor.collector.CloudWatchMonitor")
    def test_summary_with_data(self, MockCW, mock_get_session):
        session = MagicMock()
        row = MagicMock()
        row.resource_id = "i-abc"
        row.count = 42
        row.earliest = datetime(2025, 1, 1, tzinfo=timezone.utc)
        row.latest = datetime(2025, 1, 2, tzinfo=timezone.utc)
        session.query.return_value.group_by.return_value.all.return_value = [row]
        mock_get_session.return_value = session

        from agenticops.monitor.collector import MetricsCollector
        c = MetricsCollector(_make_account())

        summary = c.get_collection_summary()
        assert summary["total_resources"] == 1
        assert summary["resources"][0]["data_points"] == 42
        session.close.assert_called_once()

    @patch("agenticops.monitor.collector.get_session")
    @patch("agenticops.monitor.collector.CloudWatchMonitor")
    def test_summary_empty(self, MockCW, mock_get_session):
        session = MagicMock()
        session.query.return_value.group_by.return_value.all.return_value = []
        mock_get_session.return_value = session

        from agenticops.monitor.collector import MetricsCollector
        c = MetricsCollector(_make_account())

        summary = c.get_collection_summary()
        assert summary["total_resources"] == 0
        assert summary["resources"] == []

    @patch("agenticops.monitor.collector.get_session")
    @patch("agenticops.monitor.collector.CloudWatchMonitor")
    def test_summary_null_timestamps(self, MockCW, mock_get_session):
        session = MagicMock()
        row = MagicMock()
        row.resource_id = "i-xyz"
        row.count = 5
        row.earliest = None
        row.latest = None
        session.query.return_value.group_by.return_value.all.return_value = [row]
        mock_get_session.return_value = session

        from agenticops.monitor.collector import MetricsCollector
        c = MetricsCollector(_make_account())

        summary = c.get_collection_summary()
        assert summary["resources"][0]["earliest"] is None
        assert summary["resources"][0]["latest"] is None
