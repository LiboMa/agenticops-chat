"""What happened in the last hours (MVP-2.9.0 N15) — for the top bar's band and the map's replay.

One list from the record that already exists (`pipeline_events`): when an issue was found, when an agent started
and ended a piece of work, what a person decided, what happened to a change — each with its time and the work
item it belongs to. Nothing is stored for it and nothing is inferred: an event is on the list or it is not.

Not on it: the pipeline's internals (a critic's verdict, an evidence check, a gate merging a signal into an
existing issue, a notification, a policy rule firing) and the code moving a status (the event beside it says why).
A note's text is never sent (it is on the item's own page); a detail keeps only the keys a sentence is made of,
each cut to DETAIL_MAX characters.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import or_

from agenticops.models import ChangeRequest, HealthIssue, PipelineEvent, get_db_session
from agenticops.services.plan_content import HUMAN_ACTORS

HOURS_MAX = 24
MAX_EVENTS = 500       # the newest are kept; the answer says when older ones of the window were left out
DETAIL_MAX = 200

_SIGNAL = frozenset({"issue_created"})
# an agent's — or the pipeline's own — start and end of a piece of work
_AGENT = frozenset({"rca_started", "rca_completed", "fix_plan_requested", "fix_plan_created", "fix_plan_updated", "fix_approved",
                    "execution_started", "execution_completed", "resolved", "agent_run_abandoned"})
_CHANGE = frozenset({"change_requested", "change_review_started", "change_reviewed", "review_failed", "change_approved",
                     "change_rejected", "change_cancelled", "change_clarified"})
# always a person's act, whoever the event names as its actor
_ALWAYS_A_PERSONS = frozenset({"rca_human_feedback", "execution_stop_requested", "change_review_resolved", "note_added"})
_ON_BAND = _SIGNAL | _AGENT | _CHANGE | _ALWAYS_A_PERSONS | {"status_changed"}
_DETAIL_KEYS = ("from", "to", "reason", "verdict", "outcome", "action", "risk_level", "execution_status", "confidence",
                "after_plan", "trigger")


def kind_of(event_type: str, actor: Optional[str], change_request_id: Optional[int]) -> Optional[str]:
    """`signal` (an issue was found) | `agent` (an agent or the pipeline started / ended work) | `decision` (a person
    did it) | `change` (a change request's own course) — or None: not on the band."""
    if event_type not in _ON_BAND:
        return None
    if (actor or "").startswith(HUMAN_ACTORS) or event_type in _ALWAYS_A_PERSONS:
        return "decision"
    if event_type == "status_changed":
        return None
    if event_type in _SIGNAL:
        return "signal"
    if change_request_id or event_type in _CHANGE:
        return "change"
    return "agent"


def _aware(ts: datetime) -> datetime:
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def _iso(ts: datetime) -> str:
    return _aware(ts).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _detail(raw) -> dict:
    """The keys a sentence about the event is made of. An allowlist: a note's text (`content`), a policy decision's
    blob and anything a later event type adds are not on it, so they are never sent."""
    for _ in range(2):
        if not isinstance(raw, str):
            break
        try:
            raw = json.loads(raw)
        except ValueError:
            return {}
    if not isinstance(raw, dict):
        return {}
    out = {}
    for key in _DETAIL_KEYS:
        value = raw.get(key)
        if isinstance(value, str) and value:
            out[key] = value[:DETAIL_MAX]
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            out[key] = value
    return out


def recent_events(*, hours: int = HOURS_MAX, account_id: Optional[int] = None, now: Optional[datetime] = None) -> dict:
    """The band's events of the last `hours`, oldest first: {events: [{id, at, kind, type, status, item, actor,
    detail}], total, cut, hours, from, to, generated_at}. With more than MAX_EVENTS the newest are kept and `cut`
    says so (`total` = how many there were). `account_id` keeps the events of that account's issues and changes.
    Two statements."""
    now = now or datetime.now(timezone.utc)
    start = now - timedelta(hours=hours)
    lo, hi = start.replace(tzinfo=None), now.replace(tzinfo=None)
    with get_db_session() as s:
        q = (s.query(PipelineEvent.id, PipelineEvent.created_at, PipelineEvent.event_type, PipelineEvent.status,
                     PipelineEvent.actor, PipelineEvent.detail, PipelineEvent.health_issue_id, PipelineEvent.change_request_id)
             .filter(PipelineEvent.created_at >= lo, PipelineEvent.created_at <= hi, PipelineEvent.event_type.in_(_ON_BAND)))
        if account_id is not None:
            q = q.filter(or_(
                PipelineEvent.health_issue_id.in_(s.query(HealthIssue.id).filter(HealthIssue.account_id == account_id)),
                PipelineEvent.change_request_id.in_(s.query(ChangeRequest.id).filter(ChangeRequest.account_id == account_id))))
        rows = q.order_by(PipelineEvent.created_at, PipelineEvent.id).all()
    events = []
    for eid, at, event_type, status, actor, detail, issue_id, change_id in rows:
        kind = kind_of(event_type, actor, change_id)
        if kind is None:
            continue
        events.append({"id": eid, "at": _iso(at), "kind": kind, "type": event_type, "status": status,
                       "item": f"C{change_id}" if change_id else f"I{issue_id}" if issue_id else None,
                       "actor": actor or "system", "detail": _detail(detail)})
    total = len(events)
    return {"events": events[-MAX_EVENTS:], "total": total, "cut": total > MAX_EVENTS, "hours": hours,
            "from": _iso(start), "to": _iso(now), "generated_at": _iso(datetime.now(timezone.utc))}
