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


def _resolve_trace_id(
    trace_id: Optional[str], health_issue_id: int
) -> Optional[str]:
    """Resolve trace_id: param → ContextVar → DB lookup (best-effort)."""
    if trace_id:
        return trace_id

    # Try ContextVar
    try:
        from agenticops.config import get_trace_id
        ctx_tid = get_trace_id()
        if ctx_tid:
            return ctx_tid
    except Exception:
        pass

    # Fallback: read from HealthIssue DB record
    try:
        from agenticops.models import HealthIssue, get_db_session
        with get_db_session() as session:
            issue = session.query(HealthIssue).filter_by(id=health_issue_id).first()
            if issue and issue.trace_id:
                return issue.trace_id
    except Exception:
        pass

    return None


def log_event(
    health_issue_id: int,
    event_type: str,
    stage: str,
    status: str = "completed",
    detail: Optional[dict] = None,
    actor: str = "system",
    duration_ms: Optional[int] = None,
    trace_id: Optional[str] = None,
) -> None:
    """Log a pipeline event (best-effort, never raises)."""
    try:
        from agenticops.models import PipelineEvent, get_db_session

        resolved_tid = _resolve_trace_id(trace_id, health_issue_id)

        with get_db_session() as session:
            event = PipelineEvent(
                health_issue_id=health_issue_id,
                event_type=event_type,
                stage=stage,
                status=status,
                detail=json.dumps(detail) if detail else None,
                actor=actor,
                duration_ms=duration_ms,
                trace_id=resolved_tid,
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
                "trace_id": e.trace_id,
            }
            for e in events
        ]
