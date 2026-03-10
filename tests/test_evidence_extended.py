"""Extended tests for evidence.py — push coverage from 44% to 80%+.

Covers:
- EvidenceItem.weighted_delta property
- gather_evidence dispatcher (all paths)
- _gather_cloudtrail (mock boto3)
- _gather_cloudwatch (mock CloudWatchMonitor)
- _gather_network (mock get_alert_context)
- _gather_trace (placeholder)
- _gather_logs (placeholder)
"""

import pytest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from agenticops.analyze.evidence import (
    EvidenceItem,
    gather_evidence,
)


# ── EvidenceItem.weighted_delta ──────────────────────────────────────


class TestWeightedDelta:
    def test_cloudtrail_highest_weight(self):
        item = EvidenceItem(source="cloudtrail", content="test", confidence_delta=1.0)
        assert item.weighted_delta == pytest.approx(0.95)

    def test_trace_weight(self):
        item = EvidenceItem(source="trace", content="test", confidence_delta=1.0)
        assert item.weighted_delta == pytest.approx(0.9)

    def test_cloudwatch_weight(self):
        item = EvidenceItem(source="cloudwatch", content="test", confidence_delta=0.5)
        assert item.weighted_delta == pytest.approx(0.5 * 0.85)

    def test_logs_weight(self):
        item = EvidenceItem(source="logs", content="test", confidence_delta=1.0)
        assert item.weighted_delta == pytest.approx(0.8)

    def test_memory_weight(self):
        item = EvidenceItem(source="memory", content="test", confidence_delta=1.0)
        assert item.weighted_delta == pytest.approx(0.7)

    def test_network_weight(self):
        item = EvidenceItem(source="network", content="test", confidence_delta=1.0)
        assert item.weighted_delta == pytest.approx(0.6)

    def test_unknown_source_defaults_to_half(self):
        item = EvidenceItem(source="alien_sensor", content="test", confidence_delta=1.0)
        assert item.weighted_delta == pytest.approx(0.5)

    def test_negative_delta(self):
        item = EvidenceItem(source="cloudtrail", content="test", confidence_delta=-0.5)
        assert item.weighted_delta == pytest.approx(-0.5 * 0.95)

    def test_zero_delta(self):
        item = EvidenceItem(source="cloudtrail", content="test", confidence_delta=0.0)
        assert item.weighted_delta == pytest.approx(0.0)

    def test_self_verification_weight(self):
        item = EvidenceItem(source="self_verification", content="test", confidence_delta=1.0)
        assert item.weighted_delta == pytest.approx(0.5)


# ── gather_evidence dispatcher ───────────────────────────────────────


class TestGatherEvidence:
    @pytest.mark.asyncio
    async def test_unknown_type_returns_none(self):
        result = await gather_evidence({"type": "magic", "params": {}})
        assert result is None

    @pytest.mark.asyncio
    async def test_missing_type_returns_none(self):
        result = await gather_evidence({})
        assert result is None

    @pytest.mark.asyncio
    async def test_trace_dispatcher(self):
        result = await gather_evidence(
            {"type": "trace", "params": {}}, resource_id="i-123"
        )
        assert result is not None
        assert result.source == "trace"

    @pytest.mark.asyncio
    async def test_logs_dispatcher(self):
        result = await gather_evidence(
            {"type": "logs", "params": {"log_group": "/app/test"}},
            resource_id="i-123",
        )
        assert result is not None
        assert result.source == "logs"
        assert "/app/test" in result.content

    @pytest.mark.asyncio
    async def test_gatherer_exception_returns_evidence_item(self):
        """If a gatherer raises, gather_evidence catches and returns an EvidenceItem."""
        with patch(
            "agenticops.analyze.evidence._gather_cloudtrail",
            side_effect=RuntimeError("boom"),
        ):
            result = await gather_evidence(
                {"type": "cloudtrail", "params": {}}, resource_id="i-123"
            )
            assert result is not None
            assert "Gathering failed" in result.content
            assert result.confidence_delta == 0.0


# ── _gather_cloudtrail ───────────────────────────────────────────────


class TestGatherCloudtrail:
    @pytest.mark.asyncio
    async def test_events_found(self):
        mock_client = MagicMock()
        mock_client.lookup_events.return_value = {
            "Events": [
                {"EventName": "StopInstances", "Username": "admin", "EventTime": "2026-03-10T12:00:00Z"},
                {"EventName": "TerminateInstances", "Username": "ci", "EventTime": "2026-03-10T12:01:00Z"},
            ]
        }
        with patch("boto3.client", return_value=mock_client):
            result = await gather_evidence(
                {"type": "cloudtrail", "params": {"lookback_hours": 12}},
                resource_id="i-0e09ff39942feb07d",
            )
        assert result.source == "cloudtrail"
        assert "2 events" in result.content
        assert result.confidence_delta > 0
        assert "StopInstances" in result.raw_data["events"]

    @pytest.mark.asyncio
    async def test_no_events_found(self):
        mock_client = MagicMock()
        mock_client.lookup_events.return_value = {"Events": []}
        with patch("boto3.client", return_value=mock_client):
            result = await gather_evidence(
                {"type": "cloudtrail", "params": {}},
                resource_id="i-nonexistent",
            )
        assert result.source == "cloudtrail"
        assert result.confidence_delta == pytest.approx(-0.05)
        assert "No CloudTrail events" in result.content

    @pytest.mark.asyncio
    async def test_boto3_exception(self):
        with patch("boto3.client", side_effect=Exception("creds expired")):
            result = await gather_evidence(
                {"type": "cloudtrail", "params": {}},
                resource_id="i-123",
            )
        assert result.source == "cloudtrail"
        assert "unavailable" in result.content.lower() or "failed" in result.content.lower()
        assert result.confidence_delta == 0.0

    @pytest.mark.asyncio
    async def test_many_events_capped(self):
        """Confidence delta is capped at 5 events."""
        mock_client = MagicMock()
        mock_client.lookup_events.return_value = {
            "Events": [
                {"EventName": f"Event{i}", "Username": "u", "EventTime": "t"}
                for i in range(20)
            ]
        }
        with patch("boto3.client", return_value=mock_client):
            result = await gather_evidence(
                {"type": "cloudtrail", "params": {}},
                resource_id="i-123",
            )
        # confidence_delta = 0.1 * min(20, 5) = 0.5
        assert result.confidence_delta == pytest.approx(0.5)


# ── _gather_cloudwatch ───────────────────────────────────────────────


class TestGatherCloudwatch:
    @pytest.mark.asyncio
    async def test_metrics_found(self):
        mock_monitor = MagicMock()
        mock_monitor.get_metric_data.return_value = [
            {"value": 50.0}, {"value": 80.0}, {"value": 60.0}
        ]
        with patch(
            "agenticops.monitor.cloudwatch.CloudWatchMonitor",
            return_value=mock_monitor,
        ):
            result = await gather_evidence(
                {"type": "cloudwatch", "params": {"metrics": ["CPUUtilization"], "hours": 3}},
                resource_id="i-123",
            )
        assert result.source == "cloudwatch"
        assert result.confidence_delta == pytest.approx(0.1)
        assert "CPUUtilization" in result.content
        assert "avg=" in result.content

    @pytest.mark.asyncio
    async def test_no_metric_data(self):
        mock_monitor = MagicMock()
        mock_monitor.get_metric_data.return_value = []
        with patch(
            "agenticops.monitor.cloudwatch.CloudWatchMonitor",
            return_value=mock_monitor,
        ):
            result = await gather_evidence(
                {"type": "cloudwatch", "params": {"metrics": ["Latency"]}},
                resource_id="i-123",
            )
        assert result.source == "cloudwatch"
        assert result.confidence_delta == 0.0
        assert "No significant" in result.content

    @pytest.mark.asyncio
    async def test_monitor_import_fails(self):
        """If CloudWatchMonitor import fails, returns unavailable evidence."""
        with patch.dict("sys.modules", {"agenticops.monitor.cloudwatch": None}):
            result = await gather_evidence(
                {"type": "cloudwatch", "params": {}},
                resource_id="i-123",
            )
        assert result.source == "cloudwatch"
        assert result.confidence_delta == 0.0

    @pytest.mark.asyncio
    async def test_individual_metric_exception_skipped(self):
        """If one metric fails, others still gathered."""
        mock_monitor = MagicMock()
        calls = []

        def side_effect(*args, **kwargs):
            calls.append(1)
            if len(calls) == 1:
                raise Exception("metric 1 failed")
            return [{"value": 42.0}]

        mock_monitor.get_metric_data.side_effect = side_effect
        with patch(
            "agenticops.monitor.cloudwatch.CloudWatchMonitor",
            return_value=mock_monitor,
        ):
            result = await gather_evidence(
                {"type": "cloudwatch", "params": {"metrics": ["Bad", "Good"]}},
                resource_id="i-123",
            )
        assert result.source == "cloudwatch"
        # Good metric should be in results
        assert result.confidence_delta == pytest.approx(0.1)

    @pytest.mark.asyncio
    async def test_data_without_value_key_skipped(self):
        mock_monitor = MagicMock()
        mock_monitor.get_metric_data.return_value = [
            {"timestamp": "2026-03-10"}, {"value": 10.0}
        ]
        with patch(
            "agenticops.monitor.cloudwatch.CloudWatchMonitor",
            return_value=mock_monitor,
        ):
            result = await gather_evidence(
                {"type": "cloudwatch", "params": {"metrics": ["CPU"]}},
                resource_id="i-123",
            )
        assert result.source == "cloudwatch"
        assert result.raw_data["CPU"]["count"] == 1


# ── _gather_network ──────────────────────────────────────────────────


class TestGatherNetwork:
    @pytest.mark.asyncio
    async def test_context_found(self):
        mock_ctx = {
            "topology_summary": "VPC → ALB → EC2",
            "blast_radius": {"total_affected": 5},
        }
        with patch(
            "agenticops.graph.context.get_alert_context",
            return_value=mock_ctx,
        ):
            result = await gather_evidence(
                {"type": "network", "params": {}},
                resource_id="i-123",
            )
        assert result.source == "network"
        assert "Blast radius: 5" in result.content
        assert result.confidence_delta == pytest.approx(0.05)

    @pytest.mark.asyncio
    async def test_no_context(self):
        with patch(
            "agenticops.graph.context.get_alert_context",
            return_value=None,
        ):
            result = await gather_evidence(
                {"type": "network", "params": {}},
                resource_id="i-123",
            )
        assert result.source == "network"
        assert "No network" in result.content
        assert result.confidence_delta == 0.0

    @pytest.mark.asyncio
    async def test_import_exception(self):
        """If graph module import fails, returns unavailable evidence."""
        with patch.dict("sys.modules", {"agenticops.graph.context": None}):
            result = await gather_evidence(
                {"type": "network", "params": {}},
                resource_id="i-123",
            )
        assert result.source == "network"
        assert result.confidence_delta == 0.0


# ── _gather_trace (placeholder) ──────────────────────────────────────


class TestGatherTrace:
    @pytest.mark.asyncio
    async def test_placeholder_returns_zero_delta(self):
        result = await gather_evidence(
            {"type": "trace", "params": {}}, resource_id="i-123"
        )
        assert result.source == "trace"
        assert result.confidence_delta == 0.0
        assert "not yet available" in result.content


# ── _gather_logs (placeholder) ───────────────────────────────────────


class TestGatherLogs:
    @pytest.mark.asyncio
    async def test_placeholder_with_log_group(self):
        result = await gather_evidence(
            {"type": "logs", "params": {"log_group": "/aws/lambda/fn"}},
            resource_id="fn",
        )
        assert result.source == "logs"
        assert "/aws/lambda/fn" in result.content
        assert result.confidence_delta == 0.0

    @pytest.mark.asyncio
    async def test_placeholder_without_log_group(self):
        result = await gather_evidence(
            {"type": "logs", "params": {}}, resource_id="x"
        )
        assert result.source == "logs"
        assert "group: " in result.content
