"""Shared alert processing pipeline — extracted from web/app.py _process_webhook_alert().

Provides a reusable `process_alert()` function that can be called from both the
webhook API endpoint and the IM alert pipeline.

Core pipeline: dedup AlertEvent -> create/dedup HealthIssue -> trigger RCA.
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

from agenticops.config import settings
from agenticops.integrations.base import AlertPayload

logger = logging.getLogger(__name__)


@dataclass
class AlertProcessResult:
    """Result of processing an alert through the pipeline."""

    action: str  # created, deduplicated, resolved, cooldown, error
    health_issue_id: Optional[int] = None
    alert_event_id: Optional[int] = None
    message: str = ""


def process_alert(
    alert: AlertPayload,
    im_origin: Optional[dict] = None,
) -> AlertProcessResult:
    """Process a parsed alert through the dedup + HealthIssue pipeline.

    Extracted from ``_process_webhook_alert()`` in ``web/app.py``.
    Preserves exact dedup logic including terminal-status bypass (Bug #2 fix).

    Args:
        alert: Parsed and normalised AlertPayload.
        im_origin: Optional IM origin metadata (platform, chat_id) to store
            in HealthIssue.metric_data for feedback routing.

    Returns:
        AlertProcessResult describing what happened.
    """
    from agenticops.models import AlertEvent, HealthIssue, get_db_session

    # ── Step 1: AlertEvent dedup ──────────────────────────────────

    try:
        with get_db_session() as session:
            existing = None
            if alert.external_id:
                existing = (
                    session.query(AlertEvent)
                    .filter_by(source=alert.source, external_id=alert.external_id)
                    .first()
                )

            reuse_event = False
            if existing:
                # Check if linked HealthIssue is in a terminal state.
                # If so, allow creating a new HealthIssue for the re-fired alert.
                linked_issue = None
                if existing.health_issue_id:
                    linked_issue = (
                        session.query(HealthIssue)
                        .filter_by(id=existing.health_issue_id)
                        .first()
                    )
                terminal_statuses = {"resolved", "fix_executed", "closed"}
                if linked_issue and linked_issue.status in terminal_statuses:
                    # Reuse existing AlertEvent but unlink from terminal issue
                    existing.health_issue_id = None
                    existing.severity = alert.severity
                    existing.title = alert.title
                    existing.description = alert.description
                    existing.raw_payload = alert.raw
                    existing.status = "received"
                    session.flush()
                    event_id = existing.id
                    reuse_event = True
                else:
                    # Active issue — true dedup
                    existing.severity = alert.severity
                    existing.title = alert.title
                    existing.description = alert.description
                    existing.raw_payload = alert.raw
                    session.flush()
                    return AlertProcessResult(
                        action="deduplicated",
                        alert_event_id=existing.id,
                        health_issue_id=existing.health_issue_id,
                        message=f"Updated existing alert event #{existing.id} (dedup)",
                    )

            if not reuse_event:
                # Create new AlertEvent
                event = AlertEvent(
                    source=alert.source,
                    external_id=alert.external_id,
                    severity=alert.severity,
                    title=alert.title,
                    description=alert.description,
                    resource_hint=alert.resource_hint,
                    raw_payload=alert.raw,
                    status="received",
                )
                session.add(event)
                session.flush()
                event_id = event.id
    except Exception as e:
        logger.exception("Failed to process AlertEvent")
        return AlertProcessResult(action="error", message=f"AlertEvent processing failed: {e}")

    # ── Step 2: Create / dedup HealthIssue ────────────────────────

    health_issue_id = None
    existing_issue = None
    if settings.webhook_auto_create_issue:
        try:
            with get_db_session() as session:
                # Dedup: check for existing open issue with same resource + source
                dedup_query = session.query(HealthIssue).filter(
                    HealthIssue.source == f"webhook_{alert.source}",
                    HealthIssue.status.in_(["open", "investigating"]),
                )
                if alert.resource_hint:
                    dedup_query = dedup_query.filter(
                        HealthIssue.resource_id == alert.resource_hint
                    )
                else:
                    dedup_query = dedup_query.filter(
                        HealthIssue.title == alert.title
                    )

                existing_issue = dedup_query.first()
                if existing_issue:
                    health_issue_id = existing_issue.id
                else:
                    metric_data = {"webhook_source": alert.source, "tags": alert.tags}
                    if im_origin:
                        metric_data["im_origin"] = {
                            k: v for k, v in im_origin.items() if k != "graph_context"
                        }
                        if "graph_context" in im_origin:
                            metric_data["graph_context"] = im_origin["graph_context"]
                    issue = HealthIssue(
                        resource_id=alert.resource_hint or "unknown",
                        severity=alert.severity,
                        source=f"webhook_{alert.source}",
                        title=alert.title,
                        description=alert.description,
                        metric_data=metric_data,
                    )
                    session.add(issue)
                    session.flush()
                    health_issue_id = issue.id

            # Link AlertEvent to HealthIssue
            with get_db_session() as session:
                evt = session.query(AlertEvent).filter_by(id=event_id).first()
                if evt:
                    evt.health_issue_id = health_issue_id
                    evt.status = "processed"

            # Auto-trigger RCA for new issues
            if health_issue_id and not existing_issue:
                from agenticops.services.rca_service import trigger_auto_rca

                trigger_auto_rca(health_issue_id)

                # Auto-notify (parity with Agent path in metadata_tools.py)
                try:
                    from agenticops.services.notification_service import notify_issue_created
                    notify_issue_created(
                        health_issue_id, alert.severity, alert.title,
                        alert.resource_hint or "unknown",
                    )
                except Exception:
                    logger.debug("Webhook notification failed", exc_info=True)

        except Exception:
            logger.exception("Failed to create HealthIssue from alert")
            with get_db_session() as session:
                evt = session.query(AlertEvent).filter_by(id=event_id).first()
                if evt:
                    evt.status = "error"

    action = "created" if (health_issue_id and not existing_issue) else "deduplicated"
    return AlertProcessResult(
        action=action,
        alert_event_id=event_id,
        health_issue_id=health_issue_id,
        message=f"Alert event #{event_id} from {alert.source}, issue={health_issue_id}",
    )
