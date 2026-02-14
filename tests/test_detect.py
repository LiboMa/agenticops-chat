"""Tests for anomaly detection module."""

import pytest
from agenticops.detect.rules import (
    ThresholdRule,
    RangeRule,
    RuleEngine,
    RuleOperator,
    RuleSeverity,
)
from agenticops.detect.detector import StatisticalDetector


class TestThresholdRule:
    """Tests for threshold-based rules."""

    def test_greater_than_rule_triggers(self):
        """Test that GT rule triggers when value exceeds threshold."""
        rule = ThresholdRule(
            name="test_cpu_high",
            description="CPU is high",
            metric_name="CPUUtilization",
            operator=RuleOperator.GT,
            threshold=80.0,
            severity=RuleSeverity.HIGH,
        )

        result = rule.evaluate(90.0)
        assert result.triggered is True
        assert result.severity == RuleSeverity.HIGH

    def test_greater_than_rule_not_triggers(self):
        """Test that GT rule doesn't trigger when value is below threshold."""
        rule = ThresholdRule(
            name="test_cpu_high",
            description="CPU is high",
            metric_name="CPUUtilization",
            operator=RuleOperator.GT,
            threshold=80.0,
            severity=RuleSeverity.HIGH,
        )

        result = rule.evaluate(70.0)
        assert result.triggered is False

    def test_less_than_rule(self):
        """Test LT operator."""
        rule = ThresholdRule(
            name="test_storage_low",
            description="Storage is low",
            metric_name="FreeStorage",
            operator=RuleOperator.LT,
            threshold=1000.0,
            severity=RuleSeverity.CRITICAL,
        )

        result = rule.evaluate(500.0)
        assert result.triggered is True
        assert result.severity == RuleSeverity.CRITICAL


class TestRangeRule:
    """Tests for range-based rules."""

    def test_range_below_min(self):
        """Test range rule triggers when below minimum."""
        rule = RangeRule(
            name="test_range",
            description="Value out of range",
            metric_name="TestMetric",
            min_value=10.0,
            max_value=100.0,
        )

        result = rule.evaluate(5.0)
        assert result.triggered is True

    def test_range_above_max(self):
        """Test range rule triggers when above maximum."""
        rule = RangeRule(
            name="test_range",
            description="Value out of range",
            metric_name="TestMetric",
            min_value=10.0,
            max_value=100.0,
        )

        result = rule.evaluate(150.0)
        assert result.triggered is True

    def test_range_within(self):
        """Test range rule doesn't trigger when within range."""
        rule = RangeRule(
            name="test_range",
            description="Value out of range",
            metric_name="TestMetric",
            min_value=10.0,
            max_value=100.0,
        )

        result = rule.evaluate(50.0)
        assert result.triggered is False


class TestRuleEngine:
    """Tests for rule engine."""

    def test_default_rules_loaded(self):
        """Test that default rules are loaded."""
        engine = RuleEngine()
        assert len(engine.rules) > 0
        assert "ec2_high_cpu" in engine.rules

    def test_evaluate_metric(self):
        """Test evaluating rules for a metric."""
        engine = RuleEngine()
        results = engine.evaluate_metric("CPUUtilization", 95.0)

        # Should trigger both ec2_high_cpu and ec2_elevated_cpu
        assert len(results) >= 1
        assert any(r.rule_name == "ec2_high_cpu" for r in results)


class TestStatisticalDetector:
    """Tests for statistical anomaly detection."""

    def test_zscore_detect_anomaly(self):
        """Test Z-score detection finds anomalies."""
        # Normal values around 50, with one outlier
        values = [50, 51, 49, 52, 48, 50, 51, 49, 50, 100]

        anomalies = StatisticalDetector.zscore_detect(values, threshold=2.0)

        assert len(anomalies) >= 1
        # The last value (100) should be detected
        indices = [a[0] for a in anomalies]
        assert 9 in indices

    def test_zscore_no_anomaly(self):
        """Test Z-score doesn't flag normal data."""
        values = [50, 51, 49, 52, 48, 50, 51, 49, 50, 51]

        anomalies = StatisticalDetector.zscore_detect(values, threshold=3.0)
        assert len(anomalies) == 0

    def test_iqr_detect_outlier(self):
        """Test IQR detection finds outliers."""
        values = [10, 12, 11, 13, 10, 11, 12, 50]  # 50 is outlier

        anomalies = StatisticalDetector.iqr_detect(values, multiplier=1.5)

        assert len(anomalies) >= 1
        indices = [a[0] for a in anomalies]
        assert 7 in indices  # Index of 50

    def test_moving_average_spike(self):
        """Test moving average detects spikes."""
        # Steady values then sudden spike
        values = [10, 10, 10, 10, 10, 10, 10, 10, 10, 50]

        anomalies = StatisticalDetector.moving_average_detect(
            values, window=5, threshold_multiplier=2.0
        )

        assert len(anomalies) >= 1
