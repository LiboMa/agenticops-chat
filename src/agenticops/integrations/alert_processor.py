"""Shared alert processing pipeline — webhook/IM alerts through the Signal Gate.

Provides a reusable `process_alert()` that both the webhook API endpoint and
the IM alert pipeline call. Since MVP-2.2.0 all identity/dedup/noise judgment
lives in services/signal_gate.process_signal — this module only adapts an
AlertPayload into a SignalInput and maps the GateDecision back to the legacy
AlertProcessResult contract.
"""

import logging
from dataclasses import dataclass
from typing import Optional

from agenticops.config import settings
from agenticops.integrations.base import AlertPayload

logger = logging.getLogger(__name__)


@dataclass
class AlertProcessResult:
    """Result of processing an alert through the pipeline."""

    action: str  # created, deduplicated, noise, error
    health_issue_id: Optional[int] = None
    alert_event_id: Optional[int] = None
    message: str = ""


def process_alert(
    alert: AlertPayload,
    im_origin: Optional[dict] = None,
    trace_id: Optional[str] = None,
) -> AlertProcessResult:
    """Run one parsed alert through the Signal Gate.

    The gate records a Signal row for EVERY event (promoted/merged/noise) and
    owns fingerprinting, flapping, cooldown, resource+type merge, and the
    gray-zone LLM judgment. Webhook alerts therefore now get the same
    resolved-cooldown and cross-path identity the agent path has.

    Args:
        alert: Parsed and normalised AlertPayload.
        im_origin: Optional IM origin metadata (platform, chat_id) stored in
            HealthIssue.metric_data for feedback routing.
        trace_id: Pipeline trace ID generated at the intake point.

    Returns:
        AlertProcessResult describing what happened.
    """
    from agenticops.services.signal_gate import SignalInput, process_signal

    metric_data: dict = {"webhook_source": alert.source, "tags": alert.tags or {}}
    im_meta = None
    if im_origin:
        im_meta = {k: v for k, v in im_origin.items() if k != "graph_context"}
        if "graph_context" in im_origin:
            metric_data["graph_context"] = im_origin["graph_context"]

    # Legacy toggle: record the raw event but never create issues.
    if not settings.webhook_auto_create_issue:
        try:
            from agenticops.models import AlertEvent, get_db_session

            with get_db_session() as session:
                event = AlertEvent(
                    source=alert.source, external_id=alert.external_id,
                    severity=alert.severity, title=alert.title,
                    description=alert.description, resource_hint=alert.resource_hint,
                    raw_payload=alert.raw, status="received", trace_id=trace_id,
                    kind=alert.kind or "alert", issue_type=alert.issue_type or "other",
                )
                session.add(event)
                session.flush()
                event_id = event.id
            return AlertProcessResult(
                action="deduplicated", alert_event_id=event_id,
                message=f"Alert event #{event_id} recorded (auto-create disabled)",
            )
        except Exception as e:
            logger.exception("Failed to record AlertEvent")
            return AlertProcessResult(action="error", message=f"AlertEvent processing failed: {e}")

    try:
        decision = process_signal(SignalInput(
            source=f"webhook_{alert.source}",
            title=alert.title,
            description=alert.description,
            severity=alert.severity,
            resource_id=alert.resource_hint or "",
            provider=(alert.tags or {}).get("provider", "aws"),
            issue_type=alert.issue_type or "",
            upstream_key=alert.external_id or "",
            kind=alert.kind or "alert",
            metric_data=metric_data,
            raw=alert.raw or {},
            trace_id=trace_id,
            im_origin=im_meta,
            detected_by="webhook",
        ))
    except Exception as e:
        logger.exception("Signal gate failed for webhook alert")
        return AlertProcessResult(action="error", message=f"Alert processing failed: {e}")

    if decision.disposition == "promoted":
        return AlertProcessResult(
            action="created",
            alert_event_id=decision.signal_id,
            health_issue_id=decision.issue_id,
            message=(
                f"Signal #{decision.signal_id} from {alert.source} promoted to "
                f"HealthIssue #{decision.issue_id}"
            ),
        )
    if decision.disposition == "merged":
        return AlertProcessResult(
            action="deduplicated",
            alert_event_id=decision.signal_id,
            health_issue_id=decision.issue_id,
            message=(
                f"Signal #{decision.signal_id} merged into HealthIssue "
                f"#{decision.issue_id} ({decision.reason})"
            ),
        )
    return AlertProcessResult(
        action="noise",
        alert_event_id=decision.signal_id,
        health_issue_id=None,
        message=f"Signal #{decision.signal_id} classified as noise ({decision.reason})",
    )
