"""Tests for agenticops.tools.detect_tools — the @tool wrappers."""

import json
import pytest


# ── run_zscore_detection ──────────────────────────────────────────────

class TestRunZscoreDetection:
    """Tests for run_zscore_detection tool wrapper."""

    @pytest.fixture(autouse=True)
    def _import(self):
        from agenticops.tools.detect_tools import run_zscore_detection
        self.fn = run_zscore_detection

    def _call(self, values_json, threshold=3.0):
        return self.fn(values_json=values_json, threshold=threshold)

    # --- happy path ---
    def test_no_anomalies(self):
        values = [10.0, 10.1, 9.9, 10.2, 10.0, 9.8]
        out = json.loads(self._call(json.dumps(values)))
        assert out["anomalies"] == []
        assert out["sample_size"] == 6

    def test_detects_spike(self):
        values = [10.0] * 20 + [100.0]
        out = json.loads(self._call(json.dumps(values)))
        assert len(out["anomalies"]) >= 1
        assert out["anomalies"][0]["index"] == 20

    def test_custom_threshold(self):
        values = [10.0] * 10 + [15.0]
        out = json.loads(self._call(json.dumps(values), threshold=1.0))
        assert len(out["anomalies"]) >= 1

    def test_returns_stats(self):
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        out = json.loads(self._call(json.dumps(values)))
        assert "mean" in out
        assert "std_dev" in out
        assert out["threshold"] == 3.0

    # --- edge cases ---
    def test_too_few_points(self):
        out = json.loads(self._call(json.dumps([1.0, 2.0])))
        assert out["anomalies"] == []
        assert "at least 3" in out.get("message", "").lower()

    def test_invalid_json(self):
        result = self._call("not-json")
        assert "Invalid JSON" in result

    def test_not_a_list(self):
        out = json.loads(self._call(json.dumps({"a": 1})))
        assert out["anomalies"] == []

    def test_empty_list(self):
        out = json.loads(self._call(json.dumps([])))
        assert out["anomalies"] == []


# ── run_rule_evaluation ───────────────────────────────────────────────

class TestRunRuleEvaluation:
    """Tests for run_rule_evaluation tool wrapper."""

    @pytest.fixture(autouse=True)
    def _import(self):
        from agenticops.tools.detect_tools import run_rule_evaluation
        self.fn = run_rule_evaluation

    def _call(self, metric_name, value, context_json="{}"):
        return self.fn(metric_name=metric_name, value=value, context_json=context_json)

    # --- happy path ---
    def test_cpu_high_triggers(self):
        out = json.loads(self._call("CPUUtilization", 95.0))
        assert len(out["rules_triggered"]) >= 1

    def test_cpu_normal_no_trigger(self):
        out = json.loads(self._call("CPUUtilization", 30.0))
        assert out["rules_triggered"] == []

    def test_lambda_errors(self):
        out = json.loads(self._call("Errors", 15.0))
        triggered = out["rules_triggered"]
        assert any("high" in r["severity"].lower() for r in triggered)

    def test_lambda_throttles(self):
        out = json.loads(self._call("Throttles", 5.0))
        assert len(out["rules_triggered"]) >= 1

    def test_rds_free_storage_critical(self):
        out = json.loads(self._call("FreeStorageSpace", 500_000_000))
        triggered = out["rules_triggered"]
        assert any("critical" in r["severity"].lower() for r in triggered)

    def test_sqs_messages_visible(self):
        out = json.loads(self._call("ApproximateNumberOfMessagesVisible", 50000))
        assert len(out["rules_triggered"]) >= 1

    def test_unknown_metric_no_rules(self):
        out = json.loads(self._call("UnknownMetric", 42.0))
        assert out["rules_triggered"] == []
        assert out["rules_checked"] == 0

    def test_rules_checked_count(self):
        out = json.loads(self._call("CPUUtilization", 50.0))
        assert out["rules_checked"] >= 1

    # --- context ---
    def test_with_context(self):
        ctx = json.dumps({"resource_id": "i-123", "resource_type": "EC2"})
        out = json.loads(self._call("CPUUtilization", 95.0, context_json=ctx))
        assert len(out["rules_triggered"]) >= 1

    def test_invalid_context_json(self):
        out = json.loads(self._call("CPUUtilization", 95.0, context_json="bad-json"))
        assert len(out["rules_triggered"]) >= 1

    def test_output_structure(self):
        out = json.loads(self._call("CPUUtilization", 95.0))
        assert out["metric_name"] == "CPUUtilization"
        assert out["value"] == 95.0
        for r in out["rules_triggered"]:
            assert "rule_name" in r
            assert "severity" in r
            assert "message" in r
