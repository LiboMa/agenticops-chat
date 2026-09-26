"""Pipeline event timeline — lightweight lifecycle tracking for HealthIssues and ChangeRequests.

Every pipeline stage logs events here so we get a unified timeline:
Alert → Issue → RCA → Fix Plan → Approve → Execute → Resolve.
A change request gets its own timeline the same way (exactly one of
``health_issue_id`` / ``change_request_id`` is set per event).

Best-effort: log_event() never raises — pipeline correctness is never
blocked by event logging failure.
"""

import json
import logging
import threading
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# ── In-process subscribers (MVP-2.0.0) ──────────────────────────────
#
# Integrations (ITSM bridge, webhooks) subscribe here to react to pipeline
# lifecycle events. Handlers run on a daemon thread and are best-effort:
# a failing subscriber never blocks or breaks the pipeline.
# Subscribers only see HealthIssue events — change-request events are not fanned out.

_subscribers: list[Callable[[int, str, str, str, Optional[dict]], None]] = []
_subscribers_lock = threading.Lock()


def subscribe(handler: Callable[[int, str, str, str, Optional[dict]], None]) -> None:
    """Register handler(health_issue_id, event_type, stage, status, detail)."""
    with _subscribers_lock:
        if handler not in _subscribers:
            _subscribers.append(handler)


def unsubscribe(handler: Callable) -> None:
    with _subscribers_lock:
        if handler in _subscribers:
            _subscribers.remove(handler)


def _notify_subscribers(
    health_issue_id: int, event_type: str, stage: str, status: str, detail: Optional[dict]
) -> None:
    with _subscribers_lock:
        handlers = list(_subscribers)
    for handler in handlers:
        def _run(h=handler):
            try:
                h(health_issue_id, event_type, stage, status, detail)
            except Exception:
                logger.debug("pipeline event subscriber failed", exc_info=True)
        threading.Thread(target=_run, daemon=True, name="pipeline-event-sub").start()


def _resolve_trace_id(
    trace_id: Optional[str],
    health_issue_id: Optional[int],
    change_request_id: Optional[int] = None,
) -> Optional[str]:
    """Resolve trace_id: param → ContextVar → DB lookup (best-effort).

    The DB fallback reads the HealthIssue first, then the ChangeRequest.
    """
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

    # Fallback: read from the owning HealthIssue / ChangeRequest DB record
    try:
        from agenticops.models import ChangeRequest, HealthIssue, get_db_session
        with get_db_session() as session:
            if health_issue_id:
                issue = session.query(HealthIssue).filter_by(id=health_issue_id).first()
                if issue and issue.trace_id:
                    return issue.trace_id
            if change_request_id:
                cr = session.query(ChangeRequest).filter_by(id=change_request_id).first()
                if cr and cr.trace_id:
                    return cr.trace_id
    except Exception:
        pass

    return None


def log_event(
    health_issue_id: Optional[int],
    event_type: str,
    stage: str,
    status: str = "completed",
    detail: Optional[dict] = None,
    actor: str = "system",
    duration_ms: Optional[int] = None,
    trace_id: Optional[str] = None,
    *,
    change_request_id: Optional[int] = None,
) -> None:
    """Log a pipeline event for a HealthIssue OR a ChangeRequest (best-effort, never raises)."""
    if not health_issue_id and not change_request_id:
        logger.debug("pipeline event %s dropped: no issue or change id", event_type)
        return
    try:
        from agenticops.models import PipelineEvent, get_db_session
        resolved_tid = _resolve_trace_id(trace_id, health_issue_id, change_request_id)
        with get_db_session() as session:
            session.add(PipelineEvent(
                health_issue_id=health_issue_id or None, change_request_id=change_request_id or None,
                event_type=event_type, stage=stage, status=status,
                detail=json.dumps(detail) if detail else None, actor=actor,
                duration_ms=duration_ms, trace_id=resolved_tid,
            ))
    except Exception:
        logger.debug("Failed to log pipeline event %s (issue=%s change=%s)", event_type, health_issue_id, change_request_id, exc_info=True)
    if health_issue_id:
        try:
            _notify_subscribers(health_issue_id, event_type, stage, status, detail)
        except Exception:
            logger.debug("Subscriber notification failed for %s", event_type, exc_info=True)


def get_timeline(
    health_issue_id: Optional[int] = None,
    *,
    change_request_id: Optional[int] = None,
) -> list[dict]:
    """Get the full event timeline for a HealthIssue or a ChangeRequest, ordered by created_at.

    Filters by whichever ids are given; with neither there is nothing to look up → [].
    """
    filters: dict[str, int] = {}
    if health_issue_id:
        filters["health_issue_id"] = health_issue_id
    if change_request_id:
        filters["change_request_id"] = change_request_id
    if not filters:
        return []

    from agenticops.models import PipelineEvent, get_db_session

    with get_db_session() as session:
        events = (
            session.query(PipelineEvent)
            .filter_by(**filters)
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
                "change_request_id": e.change_request_id,
            }
            for e in events
        ]
