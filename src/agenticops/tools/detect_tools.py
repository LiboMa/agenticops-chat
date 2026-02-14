"""Statistical detection tools for Strands agents.

Wraps StatisticalDetector (z-score, IQR, moving average) and RuleEngine
as callable @tool functions for the Detect Agent.
"""

import json
import logging

from strands import tool

from agenticops.detect.detector import StatisticalDetector
from agenticops.detect.rules import RuleEngine

logger = logging.getLogger(__name__)

# Module-level singletons
_statistical = StatisticalDetector()
_rule_engine = RuleEngine()


@tool
def run_zscore_detection(values_json: str, threshold: float = 3.0) -> str:
    """Run Z-score anomaly detection on a list of metric values.

    Detects data points that deviate significantly from the mean.
    A z-score > 3.0 means the point is beyond 99.7% of normal distribution.

    Args:
        values_json: JSON array of float values (time-ordered metric data points)
        threshold: Z-score threshold (default 3.0). Lower = more sensitive.

    Returns:
        JSON object with: anomalies found (index, z-score), mean, std_dev, sample_size.
        Empty anomalies list if no anomalies detected or insufficient data.
    """
    try:
        values = json.loads(values_json)
    except json.JSONDecodeError as e:
        return f"Invalid JSON: {e}"

    if not isinstance(values, list) or len(values) < 3:
        return json.dumps({
            "anomalies": [],
            "message": "Need at least 3 data points for z-score detection.",
        })

    import numpy as np
    anomalies = _statistical.zscore_detect(values, threshold)

    mean_val = float(np.mean(values))
    std_val = float(np.std(values))

    result = {
        "anomalies": [
            {"index": idx, "z_score": round(z, 2), "value": values[idx]}
            for idx, z in anomalies
        ],
        "mean": round(mean_val, 4),
        "std_dev": round(std_val, 4),
        "sample_size": len(values),
        "threshold": threshold,
    }

    return json.dumps(result)


@tool
def run_rule_evaluation(metric_name: str, value: float, context_json: str = "{}") -> str:
    """Evaluate built-in threshold rules against a metric value.

    Checks the value against predefined rules for known metrics:
    - EC2: CPUUtilization (>70% medium, >90% critical)
    - Lambda: Errors (>10 high), Throttles (>0 high), Duration (>10s medium)
    - RDS: CPUUtilization (>80% high), DatabaseConnections (>100 medium), FreeStorageSpace (<1GB critical)
    - SQS: ApproximateNumberOfMessagesVisible (>10000 high)

    Args:
        metric_name: CloudWatch metric name (e.g., 'CPUUtilization', 'Errors', 'Duration')
        value: Current metric value
        context_json: JSON object with context (resource_id, resource_type, region)

    Returns:
        JSON object with triggered rules, each including: rule_name, severity, message, threshold.
        Empty list if no rules triggered.
    """
    try:
        context = json.loads(context_json) if isinstance(context_json, str) else context_json
    except json.JSONDecodeError:
        context = {}

    results = _rule_engine.evaluate_metric(metric_name, value, context)

    triggered = []
    for r in results:
        triggered.append({
            "rule_name": r.rule_name,
            "severity": r.severity.value if hasattr(r.severity, 'value') else str(r.severity),
            "message": r.message,
            "actual_value": r.actual_value,
            "threshold_value": r.threshold_value,
        })

    return json.dumps({
        "metric_name": metric_name,
        "value": value,
        "rules_triggered": triggered,
        "rules_checked": len(_rule_engine.get_rules_for_metric(metric_name)),
    })
