"""Tests for detection rules."""

import pytest

from agenticops.detect.rules import (
    ThresholdRule,
    RangeRule,
    RuleEngine,
    RuleOperator,
    RuleSeverity,
)


def test_threshold_rule_gt():
    """Test threshold rule with greater than operator."""
    rule = ThresholdRule(
        name="high_cpu",
        description="CPU is high",
        metric_name="CPUUtilization",
        operator=RuleOperator.GT,
        threshold=90.0,
        severity=RuleSeverity.HIGH,
        unit="%",
    )

    # Should trigger
    result = rule.evaluate(95.0)
    assert result.triggered is True
    assert result.severity == RuleSeverity.HIGH

    # Should not trigger
    result = rule.evaluate(85.0)
    assert result.triggered is False


def test_threshold_rule_lt():
    """Test threshold rule with less than operator."""
    rule = ThresholdRule(
        name="low_storage",
        description="Storage is low",
        metric_name="FreeStorageSpace",
        operator=RuleOperator.LT,
        threshold=1000.0,
        severity=RuleSeverity.CRITICAL,
    )

    # Should trigger
    result = rule.evaluate(500.0)
    assert result.triggered is True
    assert result.severity == RuleSeverity.CRITICAL

    # Should not trigger
    result = rule.evaluate(2000.0)
    assert result.triggered is False


def test_range_rule():
    """Test range rule."""
    rule = RangeRule(
        name="memory_range",
        description="Memory should be in range",
        metric_name="MemoryUtilization",
        min_value=20.0,
        max_value=80.0,
        severity=RuleSeverity.MEDIUM,
        unit="%",
    )

    # In range - should not trigger
    result = rule.evaluate(50.0)
    assert result.triggered is False

    # Below minimum - should trigger
    result = rule.evaluate(10.0)
    assert result.triggered is True

    # Above maximum - should trigger
    result = rule.evaluate(90.0)
    assert result.triggered is True


def test_rule_engine():
    """Test rule engine."""
    engine = RuleEngine()

    # Should have default rules loaded
    assert len(engine.rules) > 0

    # Test evaluation
    results = engine.evaluate_metric("CPUUtilization", 95.0)
    assert len(results) > 0
    assert any(r.triggered for r in results)


def test_rule_engine_evaluate_all():
    """Test evaluating all rules against metrics."""
    engine = RuleEngine()

    metrics = {
        "CPUUtilization": 95.0,
        "Errors": 15.0,
        "Duration": 5000.0,
    }

    results = engine.evaluate_all(metrics)

    # Should have some triggered rules
    assert len(results) > 0
