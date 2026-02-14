"""Tests for anomaly detector."""

import pytest

from agenticops.detect.detector import StatisticalDetector


def test_zscore_detect():
    """Test Z-score anomaly detection."""
    detector = StatisticalDetector()

    # Normal data with one outlier
    values = [10, 11, 9, 10, 11, 10, 9, 10, 11, 50]  # 50 is an outlier

    anomalies = detector.zscore_detect(values, threshold=2.0)

    assert len(anomalies) > 0
    # The outlier should be detected
    indices = [a[0] for a in anomalies]
    assert 9 in indices  # Index of 50


def test_zscore_no_anomalies():
    """Test Z-score with no anomalies."""
    detector = StatisticalDetector()

    # All normal data
    values = [10, 11, 10, 11, 10, 11, 10, 11, 10, 11]

    anomalies = detector.zscore_detect(values, threshold=3.0)

    assert len(anomalies) == 0


def test_iqr_detect():
    """Test IQR anomaly detection."""
    detector = StatisticalDetector()

    # Data with outliers
    values = [10, 11, 9, 10, 11, 10, 9, 10, 100, 1]

    anomalies = detector.iqr_detect(values, multiplier=1.5)

    assert len(anomalies) > 0


def test_moving_average_detect():
    """Test moving average anomaly detection."""
    detector = StatisticalDetector()

    # Data with sudden spike
    values = [10, 10, 10, 10, 10, 10, 10, 10, 10, 50]

    anomalies = detector.moving_average_detect(values, window=5, threshold_multiplier=2.0)

    assert len(anomalies) > 0
    # The spike should be detected
    indices = [a[0] for a in anomalies]
    assert 9 in indices


def test_insufficient_data():
    """Test detection with insufficient data."""
    detector = StatisticalDetector()

    # Too few data points
    values = [10, 11]

    zscore_anomalies = detector.zscore_detect(values)
    iqr_anomalies = detector.iqr_detect(values)
    ma_anomalies = detector.moving_average_detect(values)

    assert len(zscore_anomalies) == 0
    assert len(iqr_anomalies) == 0
    assert len(ma_anomalies) == 0
