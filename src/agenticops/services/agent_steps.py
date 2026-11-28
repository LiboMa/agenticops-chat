"""Reading an agent run's recorded steps, and letting old ones go (MVP-2.9.0 N10).

agents/step_recorder writes the rows; this is what the pages read through GET /api/ui/activity/steps. A page asks
for ONE run's steps and must never be handed another run's as if they were its own:

- an execution is named by its record (`execution_id`);
- a lane in flight asks for the run that began at or after the lane did (`since`) — an older run of the same agent
  on the same item is not it, and until this run records its first step the answer is «no run yet»;
- a result that is already there (a diagnosis, a plan) asks for the newest run that began before it (`before`).
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func

from agenticops.config import settings
from agenticops.models import AgentStep, PipelineEvent, get_db_session
from agenticops.services.listing import parse_item
from agenticops.utils.timeutils import as_utc

logger = logging.getLogger(__name__)

AGENTS = ("rca", "sre", "executor")
STEPS_MAX = 200
_PRUNE_BATCH = 500
_last_prune: Optional[date] = None      # process-local: one prune per process-day


def _iso(ts: Optional[datetime]) -> Optional[str]:
    """This API answers «+00:00», not «Z»."""
    ts = as_utc(ts)
    return ts.isoformat() if ts else None


def _row(s: AgentStep, withhold: bool = False) -> dict:
    """One step as a page gets it. `withhold` (a read-only reader): a tool call keeps what it was, when and how it
    ended, but not the start of its result — and, when it carried a command, not the command line either."""
    row = {"id": s.id, "kind": s.kind, "tool": s.tool_name, "look": s.look, "tier": s.tier, "plan_ref": s.plan_ref,
           "summary": s.summary or "", "preview": s.preview, "outcome": s.outcome, "by": s.by,
           "started_at": _iso(s.started_at), "ended_at": _iso(s.ended_at), "delivered_at": _iso(s.delivered_at)}
    if withhold and s.kind == "tool":
        row["preview"], row["withheld"] = None, True
        if s.tier is not None:                 # the call carried a command (agents/step_recorder.step_look)
            row["summary"] = ""
    return row


def run_steps(item: str, agent: str, *, execution_id: Optional[int] = None, since: Optional[datetime] = None,
              before: Optional[datetime] = None, after: int = 0, limit: int = STEPS_MAX, withhold: bool = False) -> dict:
    """The steps of one run of `agent` on `item`, oldest first, from the step after `after`:
    {"run": {key, agent, item, execution_id, started_at} | None, "steps": [...], "more": whether `limit` cut it}.

    `withhold` = the reader is a read-only account. The record holds command lines and the start of what commands
    returned, scrubbed by the display redaction — which knows some shapes of a secret, not all (round-2 review
    B-I6: a JSON env array, `requirepass …`, `mysql -p<password>` pass). A read-only account's own agent may not
    run a host command; it is not shown what other agents' commands were or returned either."""
    since, before = as_utc(since), as_utc(before)
    with get_db_session() as session:
        parsed = parse_item(item)
        if before is not None and since is None and agent == "rca" and parsed is not None and parsed[0] == "I":
            # «the newest run that began before it» — and not before the diagnosis it belongs to began: a run that
            # failed at its first model call recorded nothing, and an older run's steps are not «how far it got»
            # (round-2 review B-m4). Nothing on the timeline = no lower bound, as before.
            began = (session.query(func.max(PipelineEvent.created_at))
                     .filter(PipelineEvent.health_issue_id == parsed[1], PipelineEvent.event_type == "rca_started",
                             PipelineEvent.created_at <= before.astimezone(timezone.utc).replace(tzinfo=None)).scalar())
            since = as_utc(began)
        runs = (session.query(AgentStep.run_key, func.min(AgentStep.id), func.min(AgentStep.started_at),
                              func.max(AgentStep.execution_id))
                .filter(AgentStep.item == item, AgentStep.agent == agent))
        if execution_id is not None:
            runs = runs.filter(AgentStep.execution_id == execution_id)
        chosen = None
        for key, _first, started, execution in runs.group_by(AgentStep.run_key).order_by(func.min(AgentStep.id).desc()):
            started = as_utc(started)
            if (since is None or started >= since) and (before is None or started <= before):
                chosen = {"key": key, "agent": agent, "item": item, "execution_id": execution, "started_at": _iso(started)}
                break
            if since is not None and started < since:      # newest first: every older run began even earlier
                break
        if chosen is None:
            return {"run": None, "steps": [], "more": False}
        rows = (session.query(AgentStep).filter(AgentStep.run_key == chosen["key"], AgentStep.id > max(0, after))
                .order_by(AgentStep.id).limit(limit + 1).all())
        return {"run": chosen, "steps": [_row(s, withhold) for s in rows[:limit]], "more": len(rows) > limit}


def maybe_prune_daily(*, now: Optional[datetime] = None) -> int:
    """Once per process-day: delete the steps older than `agent_steps_retention_days` (0 = keep everything), in
    small transactions. Returns how many went; a failure is logged and tried again on the next call."""
    global _last_prune
    now = now or datetime.now(timezone.utc)
    days = int(getattr(settings, "agent_steps_retention_days", 0) or 0)
    if days <= 0 or _last_prune == now.date():
        return 0
    cutoff, gone = now - timedelta(days=days), 0
    try:
        while True:
            with get_db_session() as session:
                ids = [i for (i,) in session.query(AgentStep.id).filter(AgentStep.started_at < cutoff).limit(_PRUNE_BATCH)]
                if not ids:
                    break
                session.query(AgentStep).filter(AgentStep.id.in_(ids)).delete(synchronize_session=False)
                gone += len(ids)
    except Exception:
        logger.warning("agent steps: prune failed — will retry on the next call", exc_info=True)
        return gone
    _last_prune = now.date()
    if gone:
        logger.info("agent steps: pruned %d rows older than %dd", gone, days)
    return gone
