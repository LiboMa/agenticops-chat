"""Additional tests for pipeline/orchestrator.py — preset pipeline step execution.

Targets coverage from 69% → 85%+ by exercising the inner step functions
of FullScanPipeline, MonitoringPipeline, and DailyReportPipeline.

NOTE: The pipeline factory functions (FullScanPipeline, etc.) perform imports
at call-time and capture references in closures.  Therefore, patches MUST be
active *before* the pipeline is constructed so the closures capture mocks.
"""

import asyncio
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from contextlib import contextmanager

from agenticops.pipeline.orchestrator import (
    FullScanPipeline,
    MonitoringPipeline,
    DailyReportPipeline,
    Pipeline,
    StepStatus,
)


def _make_account():
    account = MagicMock()
    account.id = 1
    account.name = "test"
    account.provider = "aws"
    account.regions = ["us-east-1"]
    return account


def _make_scan_result(success=True, count=10):
    r = MagicMock()
    r.success = success
    r.count = count
    return r


@contextmanager
def _fake_db(mock_session):
    """Helper to build a fake get_db_session context manager."""
    yield mock_session


# ============================================================================
# FullScanPipeline — execute step functions
# ============================================================================

class TestFullScanPipelineExecution:
    @pytest.mark.asyncio
    async def test_scan_step(self):
        account = _make_account()

        mock_scanner = MagicMock()
        mock_scanner.scan_all_services.return_value = [
            _make_scan_result(True, 10),
            _make_scan_result(True, 5),
            _make_scan_result(False, 0),
        ]
        mock_scanner.save_results.return_value = "/tmp/results"

        with patch("agenticops.scan.AWSScanner", return_value=mock_scanner), \
             patch("agenticops.detect.AnomalyDetector"), \
             patch("agenticops.analyze.RCAEngine"), \
             patch("agenticops.report.ReportGenerator"):
            p = FullScanPipeline(account)
            scan_func = p.steps[0].func
            result = scan_func(account)
            assert result["total_scanned"] == 15
            assert result["saved"] == "/tmp/results"
            assert result["errors"] == 1

    @pytest.mark.asyncio
    async def test_detect_step(self):
        account = _make_account()

        mock_detector = MagicMock()
        mock_detector.detect_all.return_value = {"ec2": [1, 2], "s3": [3]}

        with patch("agenticops.scan.AWSScanner"), \
             patch("agenticops.detect.AnomalyDetector", return_value=mock_detector), \
             patch("agenticops.analyze.RCAEngine"), \
             patch("agenticops.report.ReportGenerator"):
            p = FullScanPipeline(account)
            detect_func = p.steps[1].func
            result = detect_func(account)
            assert result["total_anomalies"] == 3
            assert result["by_resource"] == {"ec2": 2, "s3": 1}

    @pytest.mark.asyncio
    async def test_analyze_step_no_anomalies(self):
        account = _make_account()

        with patch("agenticops.scan.AWSScanner"), \
             patch("agenticops.detect.AnomalyDetector"), \
             patch("agenticops.analyze.RCAEngine"), \
             patch("agenticops.report.ReportGenerator"):
            p = FullScanPipeline(account)
            analyze_func = p.steps[2].func
            result = analyze_func(account, detect={"total_anomalies": 0})
            assert result == {"analyzed": 0}

    @pytest.mark.asyncio
    async def test_analyze_step_with_anomalies(self):
        account = _make_account()

        mock_anomaly = MagicMock()
        mock_anomaly.id = 1

        mock_session = MagicMock()
        mock_session.query.return_value.filter_by.return_value.order_by.return_value.limit.return_value.all.return_value = [mock_anomaly]

        mock_rca = MagicMock()

        with patch("agenticops.scan.AWSScanner"), \
             patch("agenticops.detect.AnomalyDetector"), \
             patch("agenticops.analyze.RCAEngine", return_value=mock_rca), \
             patch("agenticops.report.ReportGenerator"), \
             patch("agenticops.pipeline.orchestrator.get_db_session", lambda: _fake_db(mock_session)):
            p = FullScanPipeline(account)
            analyze_func = p.steps[2].func
            result = analyze_func(account, detect={"total_anomalies": 5})
            assert result["analyzed"] == 1
            mock_rca.analyze_with_metrics.assert_called_once_with(mock_anomaly)

    @pytest.mark.asyncio
    async def test_analyze_step_exception_in_analysis(self):
        account = _make_account()

        mock_anomaly = MagicMock()
        mock_anomaly.id = 99

        mock_session = MagicMock()
        mock_session.query.return_value.filter_by.return_value.order_by.return_value.limit.return_value.all.return_value = [mock_anomaly]

        mock_rca = MagicMock()
        mock_rca.analyze_with_metrics.side_effect = RuntimeError("analysis failed")

        with patch("agenticops.scan.AWSScanner"), \
             patch("agenticops.detect.AnomalyDetector"), \
             patch("agenticops.analyze.RCAEngine", return_value=mock_rca), \
             patch("agenticops.report.ReportGenerator"), \
             patch("agenticops.pipeline.orchestrator.get_db_session", lambda: _fake_db(mock_session)):
            p = FullScanPipeline(account)
            analyze_func = p.steps[2].func
            result = analyze_func(account, detect={"total_anomalies": 1})
            assert result["analyzed"] == 0

    @pytest.mark.asyncio
    async def test_report_step(self):
        account = _make_account()

        mock_gen = MagicMock()
        mock_gen.generate_daily_report.return_value = "Report content here"

        with patch("agenticops.scan.AWSScanner"), \
             patch("agenticops.detect.AnomalyDetector"), \
             patch("agenticops.analyze.RCAEngine"), \
             patch("agenticops.report.ReportGenerator", return_value=mock_gen):
            p = FullScanPipeline(account)
            report_func = p.steps[3].func
            result = report_func(account, scan={}, detect={})
            assert result["report_generated"] is True
            assert result["content_length"] == len("Report content here")


# ============================================================================
# MonitoringPipeline — execute step functions
# ============================================================================

class TestMonitoringPipelineExecution:
    @pytest.mark.asyncio
    async def test_monitor_step_success(self):
        account = _make_account()

        mock_collector = MagicMock()
        mock_collector.collect_all_metrics.return_value = [1, 2, 3]

        with patch("agenticops.detect.AnomalyDetector"), \
             patch("agenticops.monitor.MetricsCollector", return_value=mock_collector):
            p = MonitoringPipeline(account)
            monitor_func = p.steps[0].func
            result = monitor_func(account)
            assert result["metrics_collected"] == 3

    @pytest.mark.asyncio
    async def test_monitor_step_exception(self):
        account = _make_account()

        mock_collector = MagicMock()
        mock_collector.collect_all_metrics.side_effect = RuntimeError("timeout")

        with patch("agenticops.detect.AnomalyDetector"), \
             patch("agenticops.monitor.MetricsCollector", return_value=mock_collector):
            p = MonitoringPipeline(account)
            monitor_func = p.steps[0].func
            result = monitor_func(account)
            assert result["metrics_collected"] == 0

    @pytest.mark.asyncio
    async def test_detect_step_with_critical(self):
        account = _make_account()

        critical_anomaly = MagicMock()
        critical_anomaly.severity = "critical"
        normal_anomaly = MagicMock()
        normal_anomaly.severity = "warning"

        mock_detector = MagicMock()
        mock_detector.detect_all.return_value = {
            "ec2": [critical_anomaly, normal_anomaly],
            "rds": [critical_anomaly],
        }

        with patch("agenticops.detect.AnomalyDetector", return_value=mock_detector), \
             patch("agenticops.monitor.MetricsCollector"):
            p = MonitoringPipeline(account)
            detect_func = p.steps[1].func
            result = detect_func(account)
            assert result["total_anomalies"] == 3
            assert result["critical_anomalies"] == 2

    @pytest.mark.asyncio
    async def test_notify_step_with_critical(self):
        account = _make_account()

        with patch("agenticops.detect.AnomalyDetector"), \
             patch("agenticops.monitor.MetricsCollector"):
            p = MonitoringPipeline(account)
            notify_func = p.steps[2].func
            result = notify_func(detect={"critical_anomalies": 3})
            assert result["notifications_sent"] == 3

    @pytest.mark.asyncio
    async def test_notify_step_no_critical(self):
        account = _make_account()

        with patch("agenticops.detect.AnomalyDetector"), \
             patch("agenticops.monitor.MetricsCollector"):
            p = MonitoringPipeline(account)
            notify_func = p.steps[2].func
            result = notify_func(detect={"critical_anomalies": 0})
            assert result["notifications_sent"] == 0


# ============================================================================
# DailyReportPipeline — execute step functions
# ============================================================================

class TestDailyReportPipelineExecution:
    @pytest.mark.asyncio
    async def test_scan_step(self):
        account = _make_account()

        mock_scanner = MagicMock()
        mock_scanner.scan_all_services.return_value = [
            _make_scan_result(True, 20),
        ]
        mock_scanner.save_results.return_value = 1

        with patch("agenticops.scan.AWSScanner", return_value=mock_scanner), \
             patch("agenticops.detect.AnomalyDetector"), \
             patch("agenticops.report.ReportGenerator"):
            p = DailyReportPipeline(account)
            scan_func = p.steps[0].func
            result = scan_func(account)
            assert result["total_scanned"] == 20
            assert result["saved"] == 1

    @pytest.mark.asyncio
    async def test_detect_step(self):
        account = _make_account()

        mock_detector = MagicMock()
        mock_detector.detect_all.return_value = {"lambda": [1]}

        with patch("agenticops.scan.AWSScanner"), \
             patch("agenticops.detect.AnomalyDetector", return_value=mock_detector), \
             patch("agenticops.report.ReportGenerator"):
            p = DailyReportPipeline(account)
            detect_func = p.steps[1].func
            result = detect_func(account)
            assert result["total_anomalies"] == 1

    @pytest.mark.asyncio
    async def test_analyze_step_with_anomalies(self):
        account = _make_account()

        mock_anomaly = MagicMock()
        mock_session = MagicMock()
        mock_session.query.return_value.filter_by.return_value.order_by.return_value.limit.return_value.all.return_value = [mock_anomaly]

        mock_rca = MagicMock()

        with patch("agenticops.scan.AWSScanner"), \
             patch("agenticops.detect.AnomalyDetector"), \
             patch("agenticops.analyze.RCAEngine", return_value=mock_rca), \
             patch("agenticops.report.ReportGenerator"), \
             patch("agenticops.pipeline.orchestrator.get_db_session", lambda: _fake_db(mock_session)):
            p = DailyReportPipeline(account)
            analyze_func = p.steps[2].func
            result = analyze_func(account)
            assert result["analyzed"] == 1

    @pytest.mark.asyncio
    async def test_analyze_step_exception_swallowed(self):
        account = _make_account()

        mock_anomaly = MagicMock()
        mock_session = MagicMock()
        mock_session.query.return_value.filter_by.return_value.order_by.return_value.limit.return_value.all.return_value = [mock_anomaly]

        mock_rca = MagicMock()
        mock_rca.analyze_with_metrics.side_effect = Exception("oops")

        with patch("agenticops.scan.AWSScanner"), \
             patch("agenticops.detect.AnomalyDetector"), \
             patch("agenticops.analyze.RCAEngine", return_value=mock_rca), \
             patch("agenticops.report.ReportGenerator"), \
             patch("agenticops.pipeline.orchestrator.get_db_session", lambda: _fake_db(mock_session)):
            p = DailyReportPipeline(account)
            analyze_func = p.steps[2].func
            result = analyze_func(account)
            assert result["analyzed"] == 0

    @pytest.mark.asyncio
    async def test_daily_report_step(self):
        account = _make_account()

        mock_gen = MagicMock()
        mock_gen.generate_daily_report.return_value = "Daily summary"

        with patch("agenticops.scan.AWSScanner"), \
             patch("agenticops.detect.AnomalyDetector"), \
             patch("agenticops.report.ReportGenerator", return_value=mock_gen), \
             patch("agenticops.config.settings") as mock_settings:
            mock_settings.reports_dir = "/tmp/reports"
            p = DailyReportPipeline(account)
            report_func = p.steps[3].func
            result = report_func(account)
            assert result["report_generated"] is True
