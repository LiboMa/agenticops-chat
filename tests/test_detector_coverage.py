"""Extended tests for anomaly detector - covers AnomalyDetector helper methods."""

import pytest
from unittest.mock import MagicMock, patch
import numpy as np

from agenticops.detect.detector import (
    AnomalyDetectionResult,
    AnomalyDetector,
    StatisticalDetector,
)
from agenticops.detect.rules import RuleResult, RuleSeverity
from agenticops.models import AnomalySeverity, CloudAccount, CloudResource


# ---------------------------------------------------------------------------
# AnomalyDetectionResult dataclass
# ---------------------------------------------------------------------------


class TestAnomalyDetectionResult:
    def test_defaults(self):
        r = AnomalyDetectionResult(
            is_anomaly=True,
            anomaly_type="spike",
            severity="high",
            title="Test",
            description="A test anomaly",
        )
        assert r.raw_data == {}
        assert r.confidence == 0.0
        assert r.metric_name is None

    def test_post_init_preserves_raw_data(self):
        r = AnomalyDetectionResult(
            is_anomaly=False,
            anomaly_type="x",
            severity="low",
            title="T",
            description="D",
            raw_data={"key": "value"},
        )
        assert r.raw_data == {"key": "value"}


# ---------------------------------------------------------------------------
# StatisticalDetector edge cases
# ---------------------------------------------------------------------------


class TestStatisticalDetectorEdge:
    def test_zscore_constant_values(self):
        """Constant values => std=0 => no anomalies."""
        det = StatisticalDetector()
        assert det.zscore_detect([5, 5, 5, 5, 5]) == []

    def test_iqr_with_exactly_4_values(self):
        """Minimum data size for IQR."""
        det = StatisticalDetector()
        # All same => iqr=0, no outliers unless deviation logic fires
        result = det.iqr_detect([1, 1, 1, 1])
        assert result == []

    def test_iqr_lower_outlier(self):
        """Detect a lower outlier."""
        det = StatisticalDetector()
        # Need actual spread so IQR > 0
        values = [5, 8, 10, 12, 15, 9, 11, 13, 7, -100]
        anomalies = det.iqr_detect(values, multiplier=1.5)
        indices = [a[0] for a in anomalies]
        assert 9 in indices
        # Lower outlier should have negative deviation
        for idx, dev in anomalies:
            if idx == 9:
                assert dev < 0

    def test_moving_average_constant_window_deviation(self):
        """When window is constant but next value differs."""
        det = StatisticalDetector()
        # 5 constant values then a spike: std=0 in window, so special branch
        values = [10, 10, 10, 10, 10, 20]
        anomalies = det.moving_average_detect(values, window=5, threshold_multiplier=2.0)
        assert len(anomalies) > 0
        indices = [a[0] for a in anomalies]
        assert 5 in indices

    def test_moving_average_constant_window_zero_mean(self):
        """When window is all zeros and next value is nonzero."""
        det = StatisticalDetector()
        values = [0, 0, 0, 0, 0, 5]
        anomalies = det.moving_average_detect(values, window=5, threshold_multiplier=2.0)
        # deviation = inf (division by 0 mean), so should detect
        assert len(anomalies) > 0


# ---------------------------------------------------------------------------
# AnomalyDetector helper methods (unit tests with mocks)
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_account():
    account = MagicMock(spec=CloudAccount)
    account.id = "acc-123"
    account.provider = "aws"
    account.account_id = "123456789012"
    return account


@pytest.fixture
def mock_resource():
    resource = MagicMock(spec=CloudResource)
    resource.resource_id = "i-abc123"
    resource.resource_type = "ec2"
    resource.region = "us-east-1"
    return resource


class TestAnomalyDetectorHelpers:
    @patch("agenticops.detect.detector.CloudWatchMonitor")
    def test_rule_to_detection_result(self, mock_cw, mock_account, mock_resource):
        detector = AnomalyDetector(mock_account)

        rule_result = RuleResult(
            triggered=True,
            rule_name="HighCPU",
            severity=RuleSeverity.HIGH,
            message="CPU > 90%",
            actual_value=95.0,
            threshold_value=90.0,
            metadata={"context": "test"},
        )

        result = detector._rule_to_detection_result(
            rule_result, mock_resource, "CPUUtilization", 95.0
        )

        assert result.is_anomaly is True
        assert result.anomaly_type == "threshold_breach"
        assert result.severity == AnomalySeverity.HIGH.value
        assert "HighCPU" in result.title
        assert result.metric_name == "CPUUtilization"
        assert result.actual_value == 95.0
        assert result.expected_value == 90.0
        assert result.confidence == 0.95
        # deviation_percent = (95 - 90) / 90 * 100 ≈ 5.56
        assert abs(result.deviation_percent - 5.556) < 0.1

    @patch("agenticops.detect.detector.CloudWatchMonitor")
    def test_rule_to_detection_result_zero_threshold(self, mock_cw, mock_account, mock_resource):
        """When threshold_value is 0, deviation should be None."""
        detector = AnomalyDetector(mock_account)

        rule_result = RuleResult(
            triggered=True,
            rule_name="ZeroCheck",
            severity=RuleSeverity.LOW,
            message="zero threshold",
            actual_value=5.0,
            threshold_value=0,
            metadata={},
        )

        result = detector._rule_to_detection_result(
            rule_result, mock_resource, "metric", 5.0
        )
        assert result.deviation_percent is None

    @patch("agenticops.detect.detector.CloudWatchMonitor")
    def test_rule_to_detection_result_no_threshold(self, mock_cw, mock_account, mock_resource):
        """When threshold_value is None."""
        detector = AnomalyDetector(mock_account)

        rule_result = RuleResult(
            triggered=True,
            rule_name="Pattern",
            severity=RuleSeverity.CRITICAL,
            message="pattern detected",
            actual_value=100.0,
            threshold_value=None,
            metadata={},
        )

        result = detector._rule_to_detection_result(
            rule_result, mock_resource, "metric", 100.0
        )
        assert result.deviation_percent is None
        assert result.severity == AnomalySeverity.CRITICAL.value

    @patch("agenticops.detect.detector.CloudWatchMonitor")
    def test_create_statistical_result_critical(self, mock_cw, mock_account, mock_resource):
        """Test statistical result with high deviation => CRITICAL."""
        detector = AnomalyDetector(mock_account)

        result = detector._create_statistical_result(
            resource=mock_resource,
            metric_name="NetworkIn",
            anomaly_type="zscore_spike",
            value=500.0,
            expected=100.0,
            deviation=5.0,  # > 4 => CRITICAL
            values=[100, 100, 100, 100, 100, 100, 100, 100, 100, 500],
        )

        assert result.is_anomaly is True
        assert result.severity == AnomalySeverity.CRITICAL.value
        assert result.actual_value == 500.0
        assert result.expected_value == 100.0
        assert abs(result.deviation_percent - 400.0) < 0.1
        assert result.confidence <= 0.99
        assert result.raw_data["z_score"] == 5.0
        assert result.raw_data["sample_size"] == 10

    @patch("agenticops.detect.detector.CloudWatchMonitor")
    def test_create_statistical_result_high(self, mock_cw, mock_account, mock_resource):
        """Test statistical result with deviation > 3 => HIGH."""
        detector = AnomalyDetector(mock_account)

        result = detector._create_statistical_result(
            resource=mock_resource,
            metric_name="CPUUtilization",
            anomaly_type="zscore_spike",
            value=40.0,
            expected=10.0,
            deviation=3.5,
            values=[10] * 10 + [40],
        )

        assert result.severity == AnomalySeverity.HIGH.value

    @patch("agenticops.detect.detector.CloudWatchMonitor")
    def test_create_statistical_result_medium(self, mock_cw, mock_account, mock_resource):
        """Test statistical result with deviation <= 3 => MEDIUM."""
        detector = AnomalyDetector(mock_account)

        result = detector._create_statistical_result(
            resource=mock_resource,
            metric_name="CPUUtilization",
            anomaly_type="zscore_spike",
            value=15.0,
            expected=10.0,
            deviation=2.5,
            values=[10] * 10 + [15],
        )

        assert result.severity == AnomalySeverity.MEDIUM.value

    @patch("agenticops.detect.detector.CloudWatchMonitor")
    def test_create_statistical_result_zero_expected(self, mock_cw, mock_account, mock_resource):
        """When expected is 0, deviation_pct should be 0."""
        detector = AnomalyDetector(mock_account)

        result = detector._create_statistical_result(
            resource=mock_resource,
            metric_name="Errors",
            anomaly_type="zscore_spike",
            value=5.0,
            expected=0.0,
            deviation=4.5,
            values=[0] * 10 + [5],
        )

        assert result.deviation_percent == 0

    @patch("agenticops.detect.detector.get_session")
    @patch("agenticops.detect.detector.CloudWatchMonitor")
    def test_save_anomalies(self, mock_cw, mock_get_session, mock_account, mock_resource):
        """Test _save_anomalies persists to DB session."""
        mock_session = MagicMock()
        mock_get_session.return_value = mock_session

        detector = AnomalyDetector(mock_account)

        results = [
            AnomalyDetectionResult(
                is_anomaly=True,
                anomaly_type="spike",
                severity="high",
                title="Test",
                description="desc",
                metric_name="CPU",
                expected_value=50.0,
                actual_value=99.0,
                deviation_percent=98.0,
            ),
            AnomalyDetectionResult(
                is_anomaly=False,  # Should be skipped
                anomaly_type="none",
                severity="low",
                title="No anomaly",
                description="ok",
            ),
        ]

        detector._save_anomalies(mock_resource, results)

        # Only 1 anomaly added (the one with is_anomaly=True)
        assert mock_session.add.call_count == 1
        mock_session.commit.assert_called_once()
        mock_session.close.assert_called_once()

    @patch("agenticops.detect.detector.get_session")
    @patch("agenticops.detect.detector.CloudWatchMonitor")
    def test_save_anomalies_rollback_on_error(self, mock_cw, mock_get_session, mock_account, mock_resource):
        """Test _save_anomalies rolls back on exception."""
        mock_session = MagicMock()
        mock_session.commit.side_effect = Exception("DB error")
        mock_get_session.return_value = mock_session

        detector = AnomalyDetector(mock_account)

        results = [
            AnomalyDetectionResult(
                is_anomaly=True,
                anomaly_type="spike",
                severity="high",
                title="Test",
                description="desc",
            ),
        ]

        with pytest.raises(Exception, match="DB error"):
            detector._save_anomalies(mock_resource, results)

        mock_session.rollback.assert_called_once()
        mock_session.close.assert_called_once()

    @patch("agenticops.detect.detector.get_session")
    @patch("agenticops.detect.detector.CloudWatchMonitor")
    def test_get_open_anomalies(self, mock_cw, mock_get_session, mock_account):
        """Test get_open_anomalies query."""
        mock_session = MagicMock()
        mock_query = MagicMock()
        mock_session.query.return_value = mock_query
        mock_query.filter_by.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = []
        mock_get_session.return_value = mock_session

        detector = AnomalyDetector(mock_account)
        results = detector.get_open_anomalies(severity="high", limit=50)

        assert results == []
        mock_session.close.assert_called_once()

    @patch("agenticops.detect.detector.get_session")
    @patch("agenticops.detect.detector.CloudWatchMonitor")
    def test_detect_all_filters(self, mock_cw, mock_get_session, mock_account):
        """Test detect_all with service_types and region filters."""
        mock_session = MagicMock()
        mock_query = MagicMock()
        mock_session.query.return_value = mock_query
        mock_query.filter_by.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = []
        mock_get_session.return_value = mock_session

        detector = AnomalyDetector(mock_account)
        results = detector.detect_all(
            service_types=["ec2", "rds"],
            region="us-west-2",
            hours=2,
            save=False,
        )

        assert results == {}
        mock_session.close.assert_called_once()

    @patch("agenticops.detect.detector.get_session")
    @patch("agenticops.detect.detector.CloudWatchMonitor")
    def test_detect_for_resource_with_data(self, mock_cw_cls, mock_get_session, mock_account, mock_resource):
        """Test detect_for_resource with metric data."""
        mock_session = MagicMock()
        mock_get_session.return_value = mock_session

        mock_monitor = MagicMock()
        mock_cw_cls.return_value = mock_monitor

        # Return metric data with enough points for statistical detection
        # Need z-score > 3.0: use 19 baseline + 1 extreme spike
        values = [10.0] * 19 + [200.0]  # last point is a big spike
        data_points = [{"value": v, "timestamp": "2026-01-01T00:00:00"} for v in values]
        mock_monitor.get_service_metrics.return_value = {"CPUUtilization": data_points}

        detector = AnomalyDetector(mock_account)
        # Mock rule engine to return no results (focus on statistical)
        detector.rule_engine = MagicMock()
        detector.rule_engine.evaluate_metric.return_value = []

        results = detector.detect_for_resource(mock_resource, hours=1, save=False)

        # The z-score method should detect the spike at last index
        assert len(results) > 0
        assert results[0].anomaly_type == "zscore_spike"
        assert results[0].actual_value == 200.0
