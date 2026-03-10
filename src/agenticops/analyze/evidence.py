"""Evidence model and gathering functions for Deep RCA.

Each evidence source has a dedicated gatherer function.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class EvidenceItem:
    """Single piece of investigation evidence."""

    source: str  # "cloudtrail" | "cloudwatch" | "kb" | "memory" | "trace" | "network"
    content: str  # Human-readable evidence text
    confidence_delta: float  # How much this shifts confidence (-1.0 to 1.0)
    timestamp: datetime = field(default_factory=datetime.utcnow)
    raw_data: dict = field(default_factory=dict)

    def summary(self, max_len: int = 200) -> str:
        sign = "+" if self.confidence_delta >= 0 else ""
        return (
            f"[{self.source}] {self.content[:max_len]} "
            f"(Δconf: {sign}{self.confidence_delta:.2f})"
        )


async def gather_evidence(
    gap_request: dict,
    resource_id: str = "",
    context: dict | None = None,
) -> EvidenceItem | None:
    """Dispatch evidence gathering based on gap request type.

    Args:
        gap_request: {"type": "cloudtrail", "params": {...}} from LLM
        resource_id: Target resource
        context: Additional context

    Returns:
        EvidenceItem or None if gathering failed
    """
    evidence_type = gap_request.get("type", "")
    params = gap_request.get("params", {})

    gatherers = {
        "cloudtrail": _gather_cloudtrail,
        "cloudwatch": _gather_cloudwatch,
        "network": _gather_network,
        "trace": _gather_trace,
        "logs": _gather_logs,
    }

    gatherer = gatherers.get(evidence_type)
    if not gatherer:
        logger.warning("Unknown evidence type: %s", evidence_type)
        return None

    try:
        return await gatherer(resource_id, params, context or {})
    except Exception as e:
        logger.warning("Evidence gathering failed (%s): %s", evidence_type, e)
        return EvidenceItem(
            source=evidence_type,
            content=f"Gathering failed: {e}",
            confidence_delta=0.0,
        )


async def _gather_cloudtrail(
    resource_id: str, params: dict, context: dict
) -> EvidenceItem:
    """Gather CloudTrail events for the resource."""
    lookback_hours = params.get("lookback_hours", 24)

    try:
        import boto3

        client = boto3.client("cloudtrail")
        from datetime import timedelta

        start_time = datetime.utcnow() - timedelta(hours=lookback_hours)
        response = client.lookup_events(
            LookupAttributes=[
                {"AttributeKey": "ResourceName", "AttributeValue": resource_id},
            ],
            StartTime=start_time,
            MaxResults=20,
        )
        events = response.get("Events", [])
        if events:
            summary = "; ".join(
                f"{e.get('EventName', '?')} by {e.get('Username', '?')} at {e.get('EventTime', '?')}"
                for e in events[:5]
            )
            return EvidenceItem(
                source="cloudtrail",
                content=f"Found {len(events)} events in last {lookback_hours}h: {summary}",
                confidence_delta=0.1 * min(len(events), 5),
                raw_data={"events": [e.get("EventName") for e in events]},
            )
        return EvidenceItem(
            source="cloudtrail",
            content=f"No CloudTrail events found for {resource_id} in last {lookback_hours}h",
            confidence_delta=-0.05,
        )
    except Exception as e:
        return EvidenceItem(
            source="cloudtrail",
            content=f"CloudTrail unavailable: {e}",
            confidence_delta=0.0,
        )


async def _gather_cloudwatch(
    resource_id: str, params: dict, context: dict
) -> EvidenceItem:
    """Gather CloudWatch metrics for the resource."""
    metrics = params.get("metrics", ["CPUUtilization"])

    try:
        from agenticops.monitor.cloudwatch import CloudWatchMonitor

        monitor = CloudWatchMonitor()
        results = {}
        for metric_name in metrics[:5]:  # Cap at 5 metrics
            try:
                data = monitor.get_metric_data(
                    resource_id=resource_id,
                    metric_name=metric_name,
                    hours=params.get("hours", 6),
                )
                if data:
                    values = [p["value"] for p in data if "value" in p]
                    if values:
                        results[metric_name] = {
                            "min": min(values),
                            "max": max(values),
                            "avg": sum(values) / len(values),
                            "count": len(values),
                        }
            except Exception:
                continue

        if results:
            summary = "; ".join(
                f"{k}: avg={v['avg']:.1f}, max={v['max']:.1f}" for k, v in results.items()
            )
            return EvidenceItem(
                source="cloudwatch",
                content=f"Metrics for {resource_id}: {summary}",
                confidence_delta=0.1,
                raw_data=results,
            )
        return EvidenceItem(
            source="cloudwatch",
            content=f"No significant metric data for {resource_id}",
            confidence_delta=0.0,
        )
    except Exception as e:
        return EvidenceItem(
            source="cloudwatch",
            content=f"CloudWatch unavailable: {e}",
            confidence_delta=0.0,
        )


async def _gather_network(
    resource_id: str, params: dict, context: dict
) -> EvidenceItem:
    """Gather network topology context."""
    try:
        from agenticops.graph.context import get_alert_context

        graph_ctx = get_alert_context(resource_id)
        if graph_ctx:
            topo = graph_ctx.get("topology_summary", "")
            blast = graph_ctx.get("blast_radius", {}).get("total_affected", 0)
            return EvidenceItem(
                source="network",
                content=f"Topology: {topo}. Blast radius: {blast} resources",
                confidence_delta=0.05,
                raw_data=graph_ctx,
            )
        return EvidenceItem(
            source="network",
            content=f"No network topology data for {resource_id}",
            confidence_delta=0.0,
        )
    except Exception as e:
        return EvidenceItem(
            source="network",
            content=f"Network context unavailable: {e}",
            confidence_delta=0.0,
        )


async def _gather_trace(
    resource_id: str, params: dict, context: dict
) -> EvidenceItem:
    """Gather distributed tracing data (placeholder)."""
    # TODO: Integrate with X-Ray or similar when available
    return EvidenceItem(
        source="trace",
        content=f"Trace data not yet available for {resource_id}",
        confidence_delta=0.0,
    )


async def _gather_logs(
    resource_id: str, params: dict, context: dict
) -> EvidenceItem:
    """Gather CloudWatch Logs (placeholder)."""
    # TODO: Integrate with CloudWatch Logs Insights
    log_group = params.get("log_group", "")
    return EvidenceItem(
        source="logs",
        content=f"Log analysis not yet available (group: {log_group})",
        confidence_delta=0.0,
    )
