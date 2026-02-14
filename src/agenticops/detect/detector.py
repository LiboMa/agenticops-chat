"""Anomaly Detector - Statistical and rule-based detection."""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import numpy as np

from agenticops.models import (
    Anomaly,
    AnomalySeverity,
    AWSAccount,
    AWSResource,
    MetricDataPoint,
    get_session,
)
from agenticops.detect.rules import RuleEngine, RuleResult, RuleSeverity
from agenticops.monitor.cloudwatch import CloudWatchMonitor

logger = logging.getLogger(__name__)


@dataclass
class AnomalyDetectionResult:
    """Result of anomaly detection."""

    is_anomaly: bool
    anomaly_type: str
    severity: str
    title: str
    description: str
    metric_name: Optional[str] = None
    expected_value: Optional[float] = None
    actual_value: Optional[float] = None
    deviation_percent: Optional[float] = None
    confidence: float = 0.0
    raw_data: dict = None

    def __post_init__(self):
        if self.raw_data is None:
            self.raw_data = {}


class StatisticalDetector:
    """Statistical anomaly detection methods."""

    @staticmethod
    def zscore_detect(
        values: list[float],
        threshold: float = 3.0,
    ) -> list[tuple[int, float]]:
        """
        Detect anomalies using Z-score method.

        Args:
            values: List of metric values
            threshold: Z-score threshold (default 3.0 = 99.7% confidence)

        Returns:
            List of (index, z-score) for anomalous points
        """
        if len(values) < 3:
            return []

        arr = np.array(values)
        mean = np.mean(arr)
        std = np.std(arr)

        if std == 0:
            return []

        z_scores = (arr - mean) / std
        anomalies = []

        for i, z in enumerate(z_scores):
            if abs(z) > threshold:
                anomalies.append((i, float(z)))

        return anomalies

    @staticmethod
    def iqr_detect(
        values: list[float],
        multiplier: float = 1.5,
    ) -> list[tuple[int, float]]:
        """
        Detect anomalies using IQR (Interquartile Range) method.

        Args:
            values: List of metric values
            multiplier: IQR multiplier (1.5 for outliers, 3.0 for extreme outliers)

        Returns:
            List of (index, deviation) for anomalous points
        """
        if len(values) < 4:
            return []

        arr = np.array(values)
        q1 = np.percentile(arr, 25)
        q3 = np.percentile(arr, 75)
        iqr = q3 - q1

        lower_bound = q1 - multiplier * iqr
        upper_bound = q3 + multiplier * iqr

        anomalies = []
        for i, v in enumerate(values):
            if v < lower_bound:
                deviation = (lower_bound - v) / iqr if iqr > 0 else 0
                anomalies.append((i, -deviation))
            elif v > upper_bound:
                deviation = (v - upper_bound) / iqr if iqr > 0 else 0
                anomalies.append((i, deviation))

        return anomalies

    @staticmethod
    def moving_average_detect(
        values: list[float],
        window: int = 5,
        threshold_multiplier: float = 2.0,
    ) -> list[tuple[int, float]]:
        """
        Detect anomalies using moving average deviation.

        Args:
            values: List of metric values
            window: Window size for moving average
            threshold_multiplier: Multiplier for standard deviation threshold

        Returns:
            List of (index, deviation) for anomalous points
        """
        if len(values) < window + 1:
            return []

        arr = np.array(values)
        anomalies = []

        for i in range(window, len(arr)):
            window_values = arr[i - window : i]
            ma = np.mean(window_values)
            std = np.std(window_values)

            if std > 0:
                deviation = (arr[i] - ma) / std
                if abs(deviation) > threshold_multiplier:
                    anomalies.append((i, float(deviation)))
            elif arr[i] != ma:
                # When std is 0 (constant window), any deviation is anomalous
                # Use relative deviation from mean as the score
                deviation = (arr[i] - ma) / ma if ma != 0 else float('inf')
                if abs(deviation) > 0:
                    anomalies.append((i, float(deviation) * threshold_multiplier))

        return anomalies


class AnomalyDetector:
    """Main anomaly detector combining rules and statistical methods."""

    def __init__(self, account: AWSAccount):
        """Initialize detector with AWS account."""
        self.account = account
        self.monitor = CloudWatchMonitor(account)
        self.rule_engine = RuleEngine()
        self.statistical = StatisticalDetector()

    def detect_for_resource(
        self,
        resource: AWSResource,
        hours: int = 1,
        save: bool = True,
    ) -> list[AnomalyDetectionResult]:
        """Run anomaly detection for a resource."""
        results = []

        # Get metrics
        metrics = self.monitor.get_service_metrics(
            service_type=resource.resource_type,
            resource_id=resource.resource_id,
            region=resource.region,
            hours=hours,
        )

        for metric_name, data_points in metrics.items():
            if not data_points:
                continue

            # Get latest value for rule-based detection
            latest = data_points[-1]
            latest_value = latest["value"]

            # Rule-based detection
            rule_results = self.rule_engine.evaluate_metric(
                metric_name=metric_name,
                value=latest_value,
                context={
                    "resource_id": resource.resource_id,
                    "resource_type": resource.resource_type,
                    "region": resource.region,
                },
            )

            for rule_result in rule_results:
                results.append(
                    self._rule_to_detection_result(
                        rule_result, resource, metric_name, latest_value
                    )
                )

            # Statistical detection (if enough data points)
            values = [dp["value"] for dp in data_points]
            if len(values) >= 10:
                # Z-score detection
                zscore_anomalies = self.statistical.zscore_detect(values)
                for idx, zscore in zscore_anomalies:
                    if idx == len(values) - 1:  # Only report if latest point is anomaly
                        results.append(
                            self._create_statistical_result(
                                resource=resource,
                                metric_name=metric_name,
                                anomaly_type="zscore_spike",
                                value=values[idx],
                                expected=np.mean(values),
                                deviation=zscore,
                                values=values,
                            )
                        )

        # Save anomalies if requested
        if save and results:
            self._save_anomalies(resource, results)

        return results

    def _rule_to_detection_result(
        self,
        rule_result: RuleResult,
        resource: AWSResource,
        metric_name: str,
        value: float,
    ) -> AnomalyDetectionResult:
        """Convert rule result to anomaly detection result."""
        severity_map = {
            RuleSeverity.LOW: AnomalySeverity.LOW.value,
            RuleSeverity.MEDIUM: AnomalySeverity.MEDIUM.value,
            RuleSeverity.HIGH: AnomalySeverity.HIGH.value,
            RuleSeverity.CRITICAL: AnomalySeverity.CRITICAL.value,
        }

        deviation = None
        if rule_result.threshold_value and rule_result.threshold_value != 0:
            deviation = (
                (value - rule_result.threshold_value) / rule_result.threshold_value * 100
            )

        return AnomalyDetectionResult(
            is_anomaly=True,
            anomaly_type="threshold_breach",
            severity=severity_map.get(rule_result.severity, AnomalySeverity.MEDIUM.value),
            title=f"{rule_result.rule_name}: {resource.resource_type}/{resource.resource_id}",
            description=rule_result.message,
            metric_name=metric_name,
            expected_value=rule_result.threshold_value,
            actual_value=value,
            deviation_percent=deviation,
            confidence=0.95,
            raw_data=rule_result.metadata,
        )

    def _create_statistical_result(
        self,
        resource: AWSResource,
        metric_name: str,
        anomaly_type: str,
        value: float,
        expected: float,
        deviation: float,
        values: list[float],
    ) -> AnomalyDetectionResult:
        """Create detection result for statistical anomaly."""
        severity = AnomalySeverity.MEDIUM.value
        if abs(deviation) > 4:
            severity = AnomalySeverity.CRITICAL.value
        elif abs(deviation) > 3:
            severity = AnomalySeverity.HIGH.value

        deviation_pct = ((value - expected) / expected * 100) if expected != 0 else 0

        return AnomalyDetectionResult(
            is_anomaly=True,
            anomaly_type=anomaly_type,
            severity=severity,
            title=f"Statistical anomaly: {metric_name} on {resource.resource_id}",
            description=(
                f"{metric_name} value ({value:.2f}) deviates significantly "
                f"from expected ({expected:.2f}). Z-score: {deviation:.2f}"
            ),
            metric_name=metric_name,
            expected_value=expected,
            actual_value=value,
            deviation_percent=deviation_pct,
            confidence=min(0.99, 0.9 + abs(deviation) * 0.02),
            raw_data={
                "z_score": deviation,
                "sample_size": len(values),
                "std_dev": float(np.std(values)),
            },
        )

    def _save_anomalies(
        self,
        resource: AWSResource,
        results: list[AnomalyDetectionResult],
    ):
        """Save detected anomalies to database."""
        session = get_session()

        try:
            for result in results:
                if not result.is_anomaly:
                    continue

                anomaly = Anomaly(
                    resource_id=resource.resource_id,
                    resource_type=resource.resource_type,
                    region=resource.region,
                    anomaly_type=result.anomaly_type,
                    severity=result.severity,
                    title=result.title,
                    description=result.description,
                    metric_name=result.metric_name,
                    expected_value=result.expected_value,
                    actual_value=result.actual_value,
                    deviation_percent=result.deviation_percent,
                    raw_data=result.raw_data,
                )
                session.add(anomaly)

            session.commit()
            logger.info(f"Saved {len(results)} anomalies")

        except Exception as e:
            session.rollback()
            logger.exception("Failed to save anomalies")
            raise
        finally:
            session.close()

    def detect_all(
        self,
        service_types: Optional[list[str]] = None,
        region: Optional[str] = None,
        hours: int = 1,
        save: bool = True,
    ) -> dict[str, list[AnomalyDetectionResult]]:
        """Run anomaly detection for all resources."""
        session = get_session()
        all_results = {}

        try:
            query = session.query(AWSResource).filter_by(account_id=self.account.id)

            if service_types:
                query = query.filter(AWSResource.resource_type.in_(service_types))
            if region:
                query = query.filter_by(region=region)

            resources = query.all()
            logger.info(f"Running anomaly detection on {len(resources)} resources")

            for resource in resources:
                try:
                    results = self.detect_for_resource(resource, hours, save)
                    if results:
                        all_results[resource.resource_id] = results
                except Exception as e:
                    logger.warning(f"Detection failed for {resource.resource_id}: {e}")

        finally:
            session.close()

        return all_results

    def get_open_anomalies(
        self,
        severity: Optional[str] = None,
        limit: int = 100,
    ) -> list[Anomaly]:
        """Get open (unresolved) anomalies."""
        session = get_session()

        try:
            query = (
                session.query(Anomaly)
                .filter_by(status="open")
                .order_by(Anomaly.detected_at.desc())
            )

            if severity:
                query = query.filter_by(severity=severity)

            return query.limit(limit).all()

        finally:
            session.close()
