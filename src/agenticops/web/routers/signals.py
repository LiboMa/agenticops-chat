"""Signals ledger API — the audit trail behind the Signal Gate (MVP-2.2.0).

GET  /api/signals                 — cursor-paginated ledger with filters
POST /api/signals/{id}/promote    — manually promote a merged/noise signal to a HealthIssue
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query

from agenticops.models import AlertEvent, get_db_session
from agenticops.web.schemas import SignalResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/signals", tags=["signals"])


@router.get("", response_model=List[SignalResponse])
async def api_list_signals(
    disposition: Optional[str] = Query(None, pattern="^(promoted|merged|noise|error)$"),
    issue_type: Optional[str] = None,
    kind: Optional[str] = Query(None, pattern="^(alert|detection|resolution|manual)$"),
    source: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    before_id: Optional[int] = Query(None, description="Cursor: return signals with id < before_id"),
):
    """List signals newest-first with cursor pagination."""
    with get_db_session() as session:
        query = session.query(AlertEvent).order_by(AlertEvent.id.desc())
        if disposition:
            query = query.filter(AlertEvent.disposition == disposition)
        if issue_type:
            query = query.filter(AlertEvent.issue_type == issue_type)
        if kind:
            query = query.filter(AlertEvent.kind == kind)
        if source:
            query = query.filter(AlertEvent.source == source)
        if before_id:
            query = query.filter(AlertEvent.id < before_id)
        rows = query.limit(limit).all()
        return [SignalResponse.model_validate(r) for r in rows]


@router.post("/{signal_id}/promote", status_code=201)
async def api_promote_signal(signal_id: int):
    """Manually promote a gated (merged/noise) signal into its own HealthIssue.

    Bypasses the gate (human override); the signal's disposition becomes
    promoted/manual_override and links to the new issue.
    """
    from agenticops.services.signal_gate import _promote, SignalInput

    with get_db_session() as session:
        signal = session.query(AlertEvent).filter_by(id=signal_id).first()
        if not signal:
            raise HTTPException(status_code=404, detail="Signal not found")
        if signal.disposition == "promoted" and signal.health_issue_id:
            raise HTTPException(status_code=409, detail=f"Already promoted to issue #{signal.health_issue_id}")

        sig = SignalInput(
            source=signal.source,
            title=signal.title,
            description=signal.description or "",
            severity=signal.severity or "medium",
            resource_id=signal.resource_id or signal.resource_hint or "",
            account_id=signal.account_id or "",
            issue_type=signal.issue_type or "other",
            upstream_key=signal.external_id or "",
            kind="manual",
            raw=signal.raw_payload or {},
            trace_id=signal.trace_id,
            detected_by="manual_promote",
        )
        issue = _promote(session, sig, signal.fingerprint or "", signal.trace_id, None)
        signal.disposition = "promoted"
        signal.disposition_reason = "manual_override"
        signal.health_issue_id = issue.id
        signal.status = "processed"
        session.flush()
        issue_id = issue.id

    try:
        from agenticops.services.pipeline_events import log_event

        log_event(issue_id, "issue_created", "detection",
                  detail={"source": "manual_promote", "signal_id": signal_id})
    except Exception:
        pass

    return {"health_issue_id": issue_id, "signal_id": signal_id, "message": f"Signal #{signal_id} promoted to HealthIssue #{issue_id}"}
