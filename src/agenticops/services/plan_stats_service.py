"""Plans & Changes statistics (MVP-2.6.0) — real-time aggregation, no rollup tables.

Sources: fix_plans (both kinds), change_requests, fix_executions, audit_logs, command_audits.
Percentiles and the series buckets are computed in Python (tables are small at MVP scale), so no
dialect-specific SQL is needed on SQLite or PostgreSQL.
The window and the buckets are UTC: an aware start/end is converted to UTC and a naive one is taken as UTC.

What each block counts:
- totals, lead_time, outcomes, breakdown and series are a COHORT: the plans (both kinds) and change
  requests CREATED in [start, end) — a change created before the window and closed inside it is not in
  `completed`. The work items are fix plans and change requests; a change plan is its request's child and
  never a work item of its own, but its executions feed lead_time, outcomes and the executors. The series
  dates a change request's completion by its closed_at and a fix plan's by the latest completed_at among
  its executions — its updated_at only when none has one, since an edit re-stamps updated_at.
- approvals are decision EVENTS whose audit timestamp falls in [start, end), each counted once, under its
  work item's kind, and only when that kind is selected. change.* rows are change decisions. A plan.* row
  takes its plan's plan_kind; one that classifies as "change" is the echo change_service writes onto the
  change plan, and is skipped (its change.* row is the one counted). A denial takes its subject's kind:
  a change request → change, a plan → that plan's plan_kind (a denial on a change plan is a change-side
  denial, not an echo). A denial with no plan or change subject is classified by its permission —
  change.* → change, plan.* → fix — and any other permission (e.g. audit.read) is not a plan or change
  decision, so it is never counted. auto = an agent: actor, human = any other; rejected counts every
  surviving rejection, whoever the actor.
- commands are ledger-wide — NOT kind-filtered: a refused change_required attempt belongs to no plan.
- open counts the cohort's work items not in a terminal status (FIXPLAN_TERMINAL_STATUSES /
  CHANGE_TERMINAL_STATUSES).
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func

_DECISION_ACTIONS = ("plan.approved", "change.approved", "plan.rejected", "change.rejected",
                     "authz.denied", "authz.denied_shadow")
_KINDS = ("all", "fix", "change")
_BUCKETS = ("day", "week")


def _pct(values: list[float], p: float) -> Optional[float]:
    """The nearest-rank p-th percentile — the smallest value with at least p% of the values at or below it —
    rounded to 0.1; None for no values."""
    if not values:
        return None
    vals = sorted(values)
    n = len(vals)
    k = max(0, math.ceil(p / 100 * n) - 1)
    return round(vals[k], 1)


def _secs(a: Optional[datetime], b: Optional[datetime]) -> Optional[float]:
    if a is None or b is None:
        return None
    return (b - a).total_seconds()


def _top(counter: Counter, n: int = 5) -> list[dict]:
    return [{"actor": k, "count": v} for k, v in counter.most_common(n)]


def _bucket_key(dt: datetime, bucket: str) -> str:
    """Series bucket label: the day (YYYY-MM-DD), or the Monday that starts dt's ISO week."""
    d = dt.date()
    if bucket == "week":
        d = d - timedelta(days=d.weekday())
    return d.isoformat()


def _plan_id(a) -> Optional[int]:
    """The fix_plan id an audit row names; None when it names no plan or the id is not a decimal string."""
    return int(a.entity_id) if a.entity_type == "fix_plan" and (a.entity_id or "").isdecimal() else None


def _plan_kind(a, plan_kinds: dict[int, str]) -> str:
    """The plan_kind of the plan an audit row names. A plan that no longer exists falls back to the row's
    own details.plan_kind, then "fix" (a legacy row predates change plans)."""
    return plan_kinds.get(_plan_id(a)) or (a.details or {}).get("plan_kind") or "fix"


def _decision_kind(a, plan_kinds: dict[int, str]) -> Optional[str]:
    """The work-item kind ("fix" | "change") a decision audit row counts under; None = not counted."""
    if a.action.startswith("change."):
        return "change"
    if a.action.startswith("plan."):
        kind = _plan_kind(a, plan_kinds)
        return None if kind == "change" else kind  # the echo of a change decision
    # authz.denied / authz.denied_shadow
    if a.entity_type == "change_request":
        return "change"
    if a.entity_type == "fix_plan":
        return _plan_kind(a, plan_kinds)
    permission = (a.details or {}).get("permission") or ""
    if permission.startswith("change."):
        return "change"
    if permission.startswith("plan."):
        return "fix"
    return None


def plan_stats(start: datetime, end: datetime, kind: str = "all", bucket: str = "day") -> dict:
    if kind not in _KINDS:
        raise ValueError(f"kind must be one of {'|'.join(_KINDS)}, got {kind!r}")
    if bucket not in _BUCKETS:
        raise ValueError(f"bucket must be one of {'|'.join(_BUCKETS)}, got {bucket!r}")
    start, end = (d.astimezone(timezone.utc) if d.tzinfo else d.replace(tzinfo=timezone.utc) for d in (start, end))

    from agenticops.audit.models import AuditLog
    from agenticops.models import (
        CHANGE_TERMINAL_STATUSES, FIXPLAN_TERMINAL_STATUSES, ChangeRequest, CommandAudit, FixExecution, FixPlan,
        get_db_session,
    )

    kinds = ("fix", "change") if kind == "all" else (kind,)
    with get_db_session() as db:
        plans = db.query(FixPlan).filter(FixPlan.created_at >= start, FixPlan.created_at < end,
                                         FixPlan.plan_kind.in_(kinds)).all()
        changes = db.query(ChangeRequest).filter(ChangeRequest.created_at >= start, ChangeRequest.created_at < end).all() \
            if "change" in kinds else []
        plan_ids = [p.id for p in plans]
        execs = db.query(FixExecution).filter(FixExecution.fix_plan_id.in_(plan_ids)).all() if plan_ids else []
        audits = db.query(AuditLog).filter(AuditLog.timestamp >= start, AuditLog.timestamp < end,
                                           AuditLog.action.in_(_DECISION_ACTIONS)).all()
        named = {pid for pid in (_plan_id(a) for a in audits) if pid is not None}
        plan_kinds = dict(db.query(FixPlan.id, FixPlan.plan_kind).filter(FixPlan.id.in_(named)).all()) if named else {}
        cmds = db.query(CommandAudit.outcome, CommandAudit.tool, func.count(CommandAudit.id)) \
            .filter(CommandAudit.created_at >= start, CommandAudit.created_at < end) \
            .group_by(CommandAudit.outcome, CommandAudit.tool).all()

        fix_plans = [p for p in plans if p.plan_kind == "fix"]
        by_kind_status: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for p in fix_plans:
            by_kind_status["fix"][p.status] += 1
        for c in changes:
            by_kind_status["change"][c.status] += 1
        open_count = sum(1 for p in fix_plans if p.status not in FIXPLAN_TERMINAL_STATUSES) \
            + sum(1 for c in changes if c.status not in CHANGE_TERMINAL_STATUSES)

        approvals = Counter()
        for a in audits:
            if _decision_kind(a, plan_kinds) not in kinds:
                continue
            if a.action.endswith(".approved"):
                approvals["auto" if (a.actor or "").startswith("agent:") else "human"] += 1
            elif a.action.endswith(".rejected"):
                approvals["rejected"] += 1
            elif a.action == "authz.denied":
                approvals["authz_denied"] += 1
            elif a.action == "authz.denied_shadow":
                approvals["authz_denied_shadow"] += 1

        # a negative span is clock skew or a back-filled stamp, not a lead time: dropped here as in approve_to_start
        req_to_approve = [s for s in (_secs(c.requested_at or c.created_at, c.approved_at) for c in changes)
                          if s is not None and s >= 0]
        req_to_approve += [s for s in (_secs(p.created_at, p.approved_at) for p in fix_plans) if s is not None and s >= 0]
        approve_to_start, exec_durations = [], []
        plan_by_id = {p.id: p for p in plans}
        for e in execs:
            p = plan_by_id.get(e.fix_plan_id)
            if p is not None:
                s = _secs(p.approved_at, e.started_at)
                if s is not None and s >= 0:
                    approve_to_start.append(s)
            if e.duration_ms:
                exec_durations.append(e.duration_ms / 1000.0)

        succeeded = sum(1 for e in execs if e.status == "succeeded")
        failed = sum(1 for e in execs if e.status in ("failed", "rolled_back"))
        rollbacks = sum(1 for e in execs if e.status == "rolled_back")
        needs_review = sum(1 for c in changes if c.status == "needs_review")
        success_rate = round(succeeded / (succeeded + failed), 3) if (succeeded + failed) else None

        requesters = Counter(c.requested_by for c in changes)
        approvers = Counter(x for x in ([c.approved_by for c in changes] + [p.approved_by for p in fix_plans]) if x)
        executors = Counter(e.executed_by for e in execs if e.executed_by)
        by_risk = Counter([p.risk_level for p in fix_plans] + [c.risk_level for c in changes if c.risk_level])
        by_change_type = Counter(c.effective_change_type or c.requested_change_type for c in changes)
        by_action_type = Counter(c.action_type for c in changes if c.action_type)
        by_account = Counter(str(c.account_id) for c in changes if c.account_id)

        # series: work items created per bucket (a change plan is not counted again), and the cohort's
        # completions — a change request by its closed_at; a fix plan by the latest completed_at among its
        # executions, else by its updated_at (which an edit re-stamps, so it is only the fallback)
        ended: dict[int, datetime] = {}
        for e in execs:
            if e.completed_at:
                ended[e.fix_plan_id] = max(e.completed_at, ended.get(e.fix_plan_id, e.completed_at))
        rows: dict[str, dict[str, int]] = defaultdict(lambda: {"created": 0, "completed": 0, "failed": 0})
        for p in fix_plans:
            rows[_bucket_key(p.created_at, bucket)]["created"] += 1
            done = ended.get(p.id) or p.updated_at
            if done and p.status in ("executed", "failed"):
                rows[_bucket_key(done, bucket)]["completed" if p.status == "executed" else "failed"] += 1
        for c in changes:
            rows[_bucket_key(c.created_at, bucket)]["created"] += 1
            if c.closed_at and c.status == "completed":
                rows[_bucket_key(c.closed_at, bucket)]["completed"] += 1
            elif c.closed_at and c.status in ("failed", "rolled_back"):
                rows[_bucket_key(c.closed_at, bucket)]["failed"] += 1
        series = [{"bucket": b, **rows[b]} for b in sorted(rows)]

        cmd_by_outcome, cmd_by_tool = Counter(), Counter()
        for outcome, tool, n in cmds:
            cmd_by_outcome[outcome] += n
            cmd_by_tool[tool] += n

    return {
        "period": {"start": start.isoformat(), "end": end.isoformat(), "bucket": bucket},
        "kind": kind,
        "totals": {"by_kind_status": {k: dict(v) for k, v in by_kind_status.items()}, "open": open_count},
        "approvals": {"auto": approvals["auto"], "human": approvals["human"], "rejected": approvals["rejected"],
                      "authz_denied": approvals["authz_denied"], "authz_denied_shadow": approvals["authz_denied_shadow"]},
        "lead_time": {"request_to_approve_p50_s": _pct(req_to_approve, 50), "request_to_approve_p90_s": _pct(req_to_approve, 90),
                      "approve_to_start_p50_s": _pct(approve_to_start, 50), "exec_duration_p50_s": _pct(exec_durations, 50)},
        "outcomes": {"success_rate": success_rate, "rollbacks": rollbacks, "needs_review": needs_review},
        "breakdown": {"by_actor": {"requesters": _top(requesters), "approvers": _top(approvers), "executors": _top(executors)},
                      "by_risk": dict(by_risk), "by_change_type": dict(by_change_type), "by_action_type": dict(by_action_type),
                      "by_account": dict(by_account)},
        "series": series,
        "commands": {"by_outcome": dict(cmd_by_outcome), "by_tool": dict(cmd_by_tool)},
    }
