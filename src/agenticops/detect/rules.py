"""Detection Rules - Threshold and pattern-based rules."""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)


class RuleOperator(str, Enum):
    """Comparison operators for threshold rules."""

    GT = ">"
    GTE = ">="
    LT = "<"
    LTE = "<="
    EQ = "=="
    NEQ = "!="


class RuleSeverity(str, Enum):
    """Rule severity levels."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class RuleResult:
    """Result of a rule evaluation."""

    triggered: bool
    rule_name: str
    severity: RuleSeverity
    message: str
    actual_value: Optional[float] = None
    threshold_value: Optional[float] = None
    metadata: dict = field(default_factory=dict)


class Rule(ABC):
    """Abstract base class for detection rules."""

    def __init__(
        self,
        name: str,
        description: str,
        severity: RuleSeverity = RuleSeverity.MEDIUM,
    ):
        self.name = name
        self.description = description
        self.severity = severity

    @abstractmethod
    def evaluate(self, value: Any, context: dict = None) -> RuleResult:
        """Evaluate the rule against a value."""
        pass


class ThresholdRule(Rule):
    """Simple threshold-based rule."""

    def __init__(
        self,
        name: str,
        description: str,
        metric_name: str,
        operator: RuleOperator,
        threshold: float,
        severity: RuleSeverity = RuleSeverity.MEDIUM,
        unit: str = "",
    ):
        super().__init__(name, description, severity)
        self.metric_name = metric_name
        self.operator = operator
        self.threshold = threshold
        self.unit = unit

    def evaluate(self, value: float, context: dict = None) -> RuleResult:
        """Evaluate threshold rule."""
        context = context or {}
        triggered = self._compare(value, self.threshold)

        if triggered:
            message = (
                f"{self.metric_name} is {value}{self.unit} "
                f"({self.operator.value} {self.threshold}{self.unit})"
            )
        else:
            message = f"{self.metric_name} is {value}{self.unit} (within threshold)"

        return RuleResult(
            triggered=triggered,
            rule_name=self.name,
            severity=self.severity,
            message=message,
            actual_value=value,
            threshold_value=self.threshold,
            metadata=context,
        )

    def _compare(self, value: float, threshold: float) -> bool:
        """Perform comparison based on operator."""
        ops = {
            RuleOperator.GT: lambda v, t: v > t,
            RuleOperator.GTE: lambda v, t: v >= t,
            RuleOperator.LT: lambda v, t: v < t,
            RuleOperator.LTE: lambda v, t: v <= t,
            RuleOperator.EQ: lambda v, t: v == t,
            RuleOperator.NEQ: lambda v, t: v != t,
        }
        return ops[self.operator](value, threshold)


class RangeRule(Rule):
    """Rule that checks if value is within a range."""

    def __init__(
        self,
        name: str,
        description: str,
        metric_name: str,
        min_value: Optional[float] = None,
        max_value: Optional[float] = None,
        severity: RuleSeverity = RuleSeverity.MEDIUM,
        unit: str = "",
    ):
        super().__init__(name, description, severity)
        self.metric_name = metric_name
        self.min_value = min_value
        self.max_value = max_value
        self.unit = unit

    def evaluate(self, value: float, context: dict = None) -> RuleResult:
        """Evaluate range rule."""
        context = context or {}
        triggered = False
        message_parts = []

        if self.min_value is not None and value < self.min_value:
            triggered = True
            message_parts.append(f"below minimum ({self.min_value}{self.unit})")

        if self.max_value is not None and value > self.max_value:
            triggered = True
            message_parts.append(f"above maximum ({self.max_value}{self.unit})")

        if triggered:
            message = f"{self.metric_name} is {value}{self.unit} - {', '.join(message_parts)}"
        else:
            message = f"{self.metric_name} is {value}{self.unit} (within range)"

        return RuleResult(
            triggered=triggered,
            rule_name=self.name,
            severity=self.severity,
            message=message,
            actual_value=value,
            threshold_value=self.max_value or self.min_value,
            metadata=context,
        )


class RuleEngine:
    """Engine for managing and evaluating rules."""

    def __init__(self):
        self.rules: dict[str, Rule] = {}
        self._load_default_rules()

    def _load_default_rules(self):
        """Load default detection rules."""
        # EC2 Rules
        self.add_rule(
            ThresholdRule(
                name="ec2_high_cpu",
                description="EC2 CPU utilization is critically high",
                metric_name="CPUUtilization",
                operator=RuleOperator.GT,
                threshold=90.0,
                severity=RuleSeverity.CRITICAL,
                unit="%",
            )
        )
        self.add_rule(
            ThresholdRule(
                name="ec2_elevated_cpu",
                description="EC2 CPU utilization is elevated",
                metric_name="CPUUtilization",
                operator=RuleOperator.GT,
                threshold=70.0,
                severity=RuleSeverity.MEDIUM,
                unit="%",
            )
        )

        # Lambda Rules
        self.add_rule(
            ThresholdRule(
                name="lambda_high_errors",
                description="Lambda function error rate is high",
                metric_name="Errors",
                operator=RuleOperator.GT,
                threshold=10.0,
                severity=RuleSeverity.HIGH,
            )
        )
        self.add_rule(
            ThresholdRule(
                name="lambda_throttles",
                description="Lambda function is being throttled",
                metric_name="Throttles",
                operator=RuleOperator.GT,
                threshold=0.0,
                severity=RuleSeverity.HIGH,
            )
        )
        self.add_rule(
            ThresholdRule(
                name="lambda_high_duration",
                description="Lambda function duration is high",
                metric_name="Duration",
                operator=RuleOperator.GT,
                threshold=10000.0,  # 10 seconds
                severity=RuleSeverity.MEDIUM,
                unit="ms",
            )
        )

        # RDS Rules
        self.add_rule(
            ThresholdRule(
                name="rds_high_cpu",
                description="RDS CPU utilization is high",
                metric_name="CPUUtilization",
                operator=RuleOperator.GT,
                threshold=80.0,
                severity=RuleSeverity.HIGH,
                unit="%",
            )
        )
        self.add_rule(
            ThresholdRule(
                name="rds_high_connections",
                description="RDS database connections are high",
                metric_name="DatabaseConnections",
                operator=RuleOperator.GT,
                threshold=100.0,
                severity=RuleSeverity.MEDIUM,
            )
        )
        self.add_rule(
            ThresholdRule(
                name="rds_low_storage",
                description="RDS free storage is critically low",
                metric_name="FreeStorageSpace",
                operator=RuleOperator.LT,
                threshold=1073741824.0,  # 1 GB in bytes
                severity=RuleSeverity.CRITICAL,
                unit=" bytes",
            )
        )

        # SQS Rules
        self.add_rule(
            ThresholdRule(
                name="sqs_high_queue_depth",
                description="SQS queue depth is high",
                metric_name="ApproximateNumberOfMessagesVisible",
                operator=RuleOperator.GT,
                threshold=10000.0,
                severity=RuleSeverity.HIGH,
            )
        )

    def add_rule(self, rule: Rule):
        """Add a rule to the engine."""
        self.rules[rule.name] = rule
        logger.debug(f"Added rule: {rule.name}")

    def remove_rule(self, rule_name: str):
        """Remove a rule by name."""
        if rule_name in self.rules:
            del self.rules[rule_name]
            logger.debug(f"Removed rule: {rule_name}")

    def get_rules_for_metric(self, metric_name: str) -> list[Rule]:
        """Get all rules that apply to a metric."""
        matching = []
        for rule in self.rules.values():
            if hasattr(rule, "metric_name") and rule.metric_name == metric_name:
                matching.append(rule)
        return matching

    def evaluate_metric(
        self,
        metric_name: str,
        value: float,
        context: dict = None,
    ) -> list[RuleResult]:
        """Evaluate all rules for a metric."""
        results = []
        rules = self.get_rules_for_metric(metric_name)

        for rule in rules:
            result = rule.evaluate(value, context)
            if result.triggered:
                results.append(result)
                logger.info(f"Rule triggered: {rule.name} - {result.message}")

        return results

    def evaluate_all(
        self,
        metrics: dict[str, float],
        context: dict = None,
    ) -> list[RuleResult]:
        """Evaluate all rules against a set of metrics."""
        all_results = []

        for metric_name, value in metrics.items():
            results = self.evaluate_metric(metric_name, value, context)
            all_results.extend(results)

        return all_results
