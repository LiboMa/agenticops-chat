"""Pipeline event timeline — lightweight lifecycle tracking for HealthIssues.

Every pipeline stage logs events here so we get a unified timeline:
Alert → Issue → RCA → Fix Plan → Approve → Execute → Resolve.

Best-effort: log_event() never raises — pipeline correctness is never
blocked by event logging failure.
"""

import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def log_event(
    health_issue_id: int,
    event_type: str,
    stage: str,
    status: str = "completed",
    detail: Optional[dict] = None,
    actor: str = "system",
    duration_ms: Optional[int] = None,
) -> None:
    """Log a pipeline event (best-effort, never raises)."""
    try:
        from agenticops.models import PipelineEvent, get_db_session

        with get_db_session() as session:
            event = PipelineEvent(
                health_issue_id=health_issue_id,
                event_type=event_type,
                stage=stage,
                status=status,
                detail=json.dumps(detail) if detail else None,
                actor=actor,
                duration_ms=duration_ms,
            )
            session.add(event)
    except Exception:
        logger.debug("Failed to log pipeline event %s for issue #%d", event_type, health_issue_id, exc_info=True)


def get_timeline(health_issue_id: int) -> list[dict]:
    """Get full event timeline for a HealthIssue, ordered by created_at."""
    from agenticops.models import PipelineEvent, get_db_session

    with get_db_session() as session:
        events = (
            session.query(PipelineEvent)
            .filter_by(health_issue_id=health_issue_id)
            .order_by(PipelineEvent.created_at.asc())
            .all()
        )
        return [
            {
                "id": e.id,
                "event_type": e.event_type,
                "stage": e.stage,
                "status": e.status,
                "detail": json.loads(e.detail) if e.detail else None,
                "actor": e.actor,
                "duration_ms": e.duration_ms,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in events
        ]
