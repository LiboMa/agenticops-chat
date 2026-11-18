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
from agenticops.models import AgentStep, get_db_session

logger = logging.getLogger(__name__)

AGENTS = ("rca", "sre", "executor")
STEPS_MAX = 200
_PRUNE_BATCH = 500
_last_prune: Optional[date] = None      # process-local: one prune per process-day


def _aware(ts: Optional[datetime]) -> Optional[datetime]:
    return ts if ts is None or ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def _iso(ts: Optional[datetime]) -> Optional[str]:
    ts = _aware(ts)
    return ts.isoformat() if ts else None


def _row(s: AgentStep) -> dict:
    return {"id": s.id, "kind": s.kind, "tool": s.tool_name, "look": s.look, "tier": s.tier, "plan_ref": s.plan_ref,
            "summary": s.summary or "", "preview": s.preview, "outcome": s.outcome, "by": s.by,
            "started_at": _iso(s.started_at), "ended_at": _iso(s.ended_at), "delivered_at": _iso(s.delivered_at)}


def run_steps(item: str, agent: str, *, execution_id: Optional[int] = None, since: Optional[datetime] = None,
              before: Optional[datetime] = None, after: int = 0, limit: int = STEPS_MAX) -> dict:
    """The steps of one run of `agent` on `item`, oldest first, from the step after `after`:
    {"run": {key, agent, item, execution_id, started_at} | None, "steps": [...], "more": whether `limit` cut it}."""
    since, before = _aware(since), _aware(before)
    with get_db_session() as session:
        runs = (session.query(AgentStep.run_key, func.min(AgentStep.id), func.min(AgentStep.started_at),
                              func.max(AgentStep.execution_id))
                .filter(AgentStep.item == item, AgentStep.agent == agent))
        if execution_id is not None:
            runs = runs.filter(AgentStep.execution_id == execution_id)
        chosen = None
        for key, _first, started, execution in runs.group_by(AgentStep.run_key).order_by(func.min(AgentStep.id).desc()):
            started = _aware(started)
            if (since is None or started >= since) and (before is None or started <= before):
                chosen = {"key": key, "agent": agent, "item": item, "execution_id": execution, "started_at": _iso(started)}
                break
            if since is not None:          # newest first: every older run began even earlier
                break
        if chosen is None:
            return {"run": None, "steps": [], "more": False}
        rows = (session.query(AgentStep).filter(AgentStep.run_key == chosen["key"], AgentStep.id > max(0, after))
                .order_by(AgentStep.id).limit(limit + 1).all())
        return {"run": chosen, "steps": [_row(s) for s in rows[:limit]], "more": len(rows) > limit}


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
