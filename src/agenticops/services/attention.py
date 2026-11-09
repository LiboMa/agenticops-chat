"""Needs your attention (MVP-2.7.0 S3): every work item whose page says it waits on a person, for this actor.

One row per work item (an issue or a change). Where it stands comes from services/work_phases — the issue and
change pages' own rules — so the top bar and the pages agree. Who sees a row (strict policy, never authz.check):
approvals and acceptance need the approval permission (SoD keeps a requester off their own change), "approved but
not running" the execute permission, a change's draft / clarification its requester (admins when the requester is
not a signed-in user); an issue's "you" steps have no permission check behind them and so show to everyone.
Configuration never hides a row: one the executor cannot run (executor off) shows with its action refused.
No model call, no cloud call; a fixed number of queries.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from agenticops.config import settings
from agenticops.models import (ChangeRequest, CloudResource, FixExecution, FixPlan, HealthIssue, PipelineEvent, RCAResult,
                               get_db_session)
from agenticops.services import ui_actions as ua
from agenticops.services import work_phases as wp

ISSUE_STATUSES = ("root_cause_identified", "fix_planned", "fix_approved", "fix_executed")
CHANGE_STATUSES = ("draft", "needs_clarification", "planned", "approved", "needs_review")
_FIX_TERMINAL = ("executed", "failed", "rejected")

# sub → (reason, reason_detail, hash anchor); awaitingApproval routes to the plan page instead
ISSUE_ROWS = {
    "needsNewPlan": ("execution_failed", "run_failed", "plan"),
    "planRejected": ("review_required", "plan_rejected", "plan"),
    "needsReview": ("review_required", "rca_gate", "diagnose"),
    "rcaRejected": ("review_required", "rca_rejected", "diagnose"),
    "toGenerate": ("review_required", "rca_confirmed", "plan"),
    "awaitingApproval": ("approval_required", None, None),
    "notQueued": ("execution_not_started", None, "run"),
    "awaitingAcceptance": ("verification_required", "acceptance", "accept"),
    "passed": ("verification_required", "resolve", "accept"),
    "unverified": ("verification_required", "resolve", "accept"),
}
CHANGE_ROWS = {
    "draft": ("review_required", "change_draft", "request"),
    "needsClarification": ("clarification_required", None, "review"),
    "awaitingApproval": ("approval_required", None, "plan"),
    "notQueued": ("execution_not_started", None, "run"),
    "awaitingAcceptance": ("verification_required", "acceptance", "accept"),
}
_PRIMARY_ACTION = {"generatePlan": "generate_plan", "rerunRca": "rerun_rca", "reviewRca": "review_rca",
                   "acceptResult": "accept", "markResolved": "mark_resolved", "startReview": "start_review",
                   "answerReviewer": "clarify", "markCompleted": "resolve_review"}


def _aware(ts: Optional[datetime]) -> Optional[datetime]:
    return None if ts is None else (ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc))


def _iso(ts: datetime) -> str:
    return ts.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _update(primary: str) -> dict:
    return {"action": _PRIMARY_ACTION.get(primary, primary), "allowed": True, "reason_code": None, "effect": "update"}


def _first_by(rows, key) -> dict:
    out: dict = {}
    for r in rows:  # rows arrive newest first
        out.setdefault(getattr(r, key), r)
    return out


def _group(rows, key) -> dict:
    out: dict = {}
    for r in rows:
        out.setdefault(getattr(r, key), []).append(r)
    return out


def _item(rid, ref, entity, reason, detail, title, account_id, occurred, route, actions, *, waiting_on,
          severity=None, risk_level=None, resource=None, region=None) -> dict:
    return {"id": rid, "ref": ref, "entity": entity, "reason": reason, "reason_detail": detail, "title": title,
            "account_id": account_id, "occurred_at": occurred, "route": route, "available_actions": actions,
            "waiting_on": waiting_on, "severity": severity, "risk_level": risk_level, "resource": resource,
            "region": region}


REASONS = frozenset(r for r, _d, _a in (*ISSUE_ROWS.values(), *CHANGE_ROWS.values()))
SORTS = ("waiting_longest", "newest", "severity")
_SEV_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}
_RISK_RANK = {"L3": 1, "L2": 2, "L1": 3, "L0": 3}


@dataclass(frozen=True)
class IssueWait:
    """Where an issue stands and since when it has waited there (MVP-2.8.0 S2) — one definition for the workbench,
    the issue list and the issue page. `since` follows the row rules: the plan's approval / update, the run's end,
    the RCA, else when the issue was last seen."""
    phase: wp.Phase
    since: datetime
    plan: Optional[FixPlan] = None
    plans: list = field(default_factory=list)
    run: Optional[FixExecution] = None
    rca: Optional[RCAResult] = None
    events: list = field(default_factory=list)
    auto: bool = False


def _since(issue, sub, plan, run, rca, now) -> datetime:
    if sub == "awaitingApproval" and plan is not None:
        ts = plan.updated_at or plan.created_at
    elif sub == "notQueued" and plan is not None:
        ts = plan.approved_at or plan.updated_at
    elif sub in ("awaitingAcceptance", "needsNewPlan", "passed", "unverified") and run is not None:
        ts = run.completed_at or run.created_at
    elif sub == "planRejected" and plan is not None:
        ts = plan.rejected_at or plan.updated_at
    elif rca is not None:
        ts = rca.created_at
    else:
        ts = issue.last_seen or issue.detected_at
    return _aware(ts) or now


def issue_waits(s, issues, *, now: datetime) -> dict[int, IssueWait]:
    """Phase + waiting-since for each issue, in a fixed number of queries (plans, RCAs, runs, run events)."""
    if not issues:
        return {}
    ids = [i.id for i in issues]
    plans_by = _group(s.query(FixPlan).filter(FixPlan.health_issue_id.in_(ids), FixPlan.plan_kind == "fix").all(),
                      "health_issue_id")
    rcas = _first_by(s.query(RCAResult).filter(RCAResult.health_issue_id.in_(ids))
                     .order_by(RCAResult.created_at.desc(), RCAResult.id.desc()).all(), "health_issue_id")
    runs = _first_by(s.query(FixExecution).filter(FixExecution.health_issue_id.in_(ids))
                     .order_by(FixExecution.created_at.desc(), FixExecution.id.desc()).all(), "health_issue_id")
    approved = [i.id for i in issues if i.status == "fix_approved"]
    events_by = _group(s.query(PipelineEvent).filter(
        PipelineEvent.health_issue_id.in_(approved),
        PipelineEvent.event_type.in_(("execution_started", "execution_completed"))).all(),
        "health_issue_id") if approved else {}
    out: dict[int, IssueWait] = {}
    for issue in issues:
        plans = plans_by.get(issue.id, [])
        plan = wp.current_fix_plan(plans)
        run, rca, events = runs.get(issue.id), rcas.get(issue.id), events_by.get(issue.id, [])
        auto = (plan is not None and plan.status == "approved" and wp.in_flight_auto_run(
            events, plan.id, timeout_seconds=settings.executor_total_timeout, now=now) is not None)
        phase = wp.issue_phase(issue.status, rca=rca, threshold=settings.rca_min_confidence_for_autofix,
                               plan=plan, latest_run=run, auto_run_in_flight=auto,
                               auto_fix_enabled=bool(settings.auto_fix_enabled))
        out[issue.id] = IssueWait(phase, _since(issue, phase.sub, plan, run, rca, now), plan, plans, run, rca,
                                  events, auto)
    return out


def change_waits(crs) -> dict[int, tuple]:
    """(phase, waiting-since) for each change request: a change waits from its last update."""
    return {cr.id: (wp.change_phase(cr), _aware(cr.updated_at or cr.created_at)) for cr in crs}


def _resources(s, issues) -> dict[int, CloudResource]:
    refs = {i.resource_ref for i in issues if i.resource_ref}
    if not refs:
        return {}
    return {r.id: r for r in s.query(CloudResource).filter(CloudResource.id.in_(refs))}


def _issue_items(s, actor, account_id, now) -> list[dict]:
    q = s.query(HealthIssue).filter(HealthIssue.status.in_(ISSUE_STATUSES))
    if account_id is not None:
        q = q.filter(HealthIssue.account_id == account_id)
    issues = q.all()
    if not issues:
        return []
    waits = issue_waits(s, issues, now=now)
    resources = _resources(s, issues)
    out = []
    for issue in issues:
        w = waits[issue.id]
        phase, plan, plans, run, rca, events, auto = w.phase, w.plan, w.plans, w.run, w.rca, w.events, w.auto
        if phase.waiting_for not in wp.HUMAN or phase.primary is None:
            continue
        if phase.sub == "notQueued" and plan is not None and plan.status == "approved":
            start = wp.not_queued_from(events, plan.id, plan.approved_at)
            if start is not None and now < start:
                continue   # still inside the grace: the page says it is checking whether the run started
        reason, detail, anchor = ISSUE_ROWS[phase.sub]
        if phase.sub == "needsReview" and rca is None:
            detail = "rca_missing"
        if phase.sub == "toGenerate" and getattr(rca, "human_verdict", None) != "correct":
            detail = "rca_ready"   # passed the gate, auto-fix off: nobody confirmed it, nobody asks the SRE agent
        entity = {"entity_type": "health_issue", "entity_id": issue.id, "content_version": None}
        route = f"/app/issues/{issue.id}#{anchor}" if anchor else None
        if reason == "approval_required":
            if not ua.strictly_allowed(actor, "plan.approve", plan):
                continue
            entity = {"entity_type": "fix_plan", "entity_id": plan.id, "content_version": plan.plan_version}
            route = f"/app/plans/{plan.id}"
            actions = [a for a in ua.plan_actions(plan, actor, issue_status=issue.status, run_in_flight=False)
                       if a["action"] == "approve"]
        elif phase.sub == "notQueued":
            if plan is None or not ua.strictly_allowed(actor, "plan.execute", plan):
                continue
            entity = {"entity_type": "fix_plan", "entity_id": plan.id, "content_version": plan.plan_version}
            actions = [a for a in ua.plan_actions(plan, actor, issue_status=issue.status, run_in_flight=auto)
                       if a["action"] == "execute"] or [{"action": "execute", "allowed": False,
                                                          "reason_code": "state", "effect": "queue_execution"}]
        elif phase.sub == "awaitingAcceptance":
            run_plan = next((p for p in plans if p.id == run.fix_plan_id), None)
            if run_plan is None or not ua.strictly_allowed(actor, "plan.approve", run_plan):
                continue
            actions = [_update(phase.primary)]
        else:
            # the «you» steps — a verdict on the RCA, a new plan, a note — all need the issue-level write flag
            # (issue.note): a viewer is never handed a step it cannot take (S2 review)
            if not ua.strictly_allowed(actor, "issue.note", issue):
                continue
            actions = [_update(phase.primary)]
        res = resources.get(issue.resource_ref) if issue.resource_ref else None
        if res is not None and res.account_id != issue.account_id:
            res = None   # a stale ref of another account's row (SQLite does not enforce ON DELETE SET NULL)
        out.append(_item(f"I{issue.id}", f"I#{issue.id}", entity, reason, detail, issue.title, issue.account_id,
                         w.since, route, actions, waiting_on=phase.waiting_for, severity=issue.severity,
                         resource=({"ref": res.id, "name": res.name, "type": res.resource_type,
                                    "resource_id": res.resource_id} if res else None),
                         region=res.region if res else None))
    return out


def _requester_sees(actor, cr) -> bool:
    if cr.requested_by and cr.requested_by == actor.key:
        return True
    return not (cr.requested_by or "").startswith("user:") and ua.is_admin(actor)


def _change_items(s, actor, account_id) -> list[dict]:
    q = s.query(ChangeRequest).filter(ChangeRequest.status.in_(CHANGE_STATUSES))
    if account_id is not None:
        q = q.filter(ChangeRequest.account_id == account_id)
    crs = q.all()
    if not crs:
        return []
    active = _first_by(s.query(FixPlan).filter(
        FixPlan.change_request_id.in_([c.id for c in crs]), FixPlan.plan_kind == "change",
        FixPlan.status.notin_(_FIX_TERMINAL)).order_by(FixPlan.created_at.desc(), FixPlan.id.desc()).all(),
        "change_request_id")
    out = []
    for cr in crs:
        phase = wp.change_phase(cr)
        if phase.waiting_for not in wp.HUMAN or phase.primary is None:
            continue
        reason, detail, anchor = CHANGE_ROWS[phase.sub]
        plan = active.get(cr.id)
        if phase.sub in ("draft", "needsClarification"):
            if not _requester_sees(actor, cr):
                continue
            actions = [_update(phase.primary)]
        elif phase.sub in ("awaitingApproval", "awaitingAcceptance"):
            if not ua.strictly_allowed(actor, "change.approve", cr):
                continue
            actions = ([a for a in ua.change_actions(cr, actor, plan=plan) if a["action"] == "approve"]
                       if phase.sub == "awaitingApproval" else [_update(phase.primary)])
        else:  # notQueued
            if not ua.strictly_allowed(actor, "change.execute", cr):
                continue
            actions = [a for a in ua.change_actions(cr, actor, plan=plan) if a["action"] == "execute"]
        entity = {"entity_type": "change_request", "entity_id": cr.id,
                  "content_version": plan.plan_version if plan is not None else None}
        targets = cr.target_resources or []
        region = next((t.get("region") for t in targets if isinstance(t, dict) and t.get("region")), None)
        out.append(_item(f"C{cr.id}", f"C#{cr.id}", entity, reason, detail, cr.title, cr.account_id,
                         _aware(cr.updated_at or cr.created_at), f"/app/changes/{cr.id}#{anchor}", actions,
                         waiting_on=phase.waiting_for, risk_level=cr.risk_level, region=region))
    return out


def _matches(item: dict, q: str) -> bool:
    needle = q.strip().casefold()
    if not needle:
        return True
    number = needle.lstrip("ic#")
    if number.isdigit() and item["ref"].casefold().split("#", 1)[1] == number:
        return True
    res = item.get("resource") or {}
    hay = (item["title"] or "", item["ref"], res.get("name") or "", res.get("resource_id") or "")
    return any(needle in h.casefold() for h in hay)


def _sort_key(sort: str):
    if sort == "newest":
        return lambda i: (-i["occurred_at"].timestamp(), i["id"])
    if sort == "severity":
        return lambda i: (_SEV_RANK.get(i["severity"] or "", _RISK_RANK.get(i["risk_level"] or "", 4)),
                          i["occurred_at"], i["id"])
    return lambda i: (i["occurred_at"], i["id"])   # waiting_longest: the longest wait first


def attention_page(actor, *, account_id: Optional[int] = None, reason: Optional[list[str]] = None,
                   q: Optional[str] = None, sort: str = "waiting_longest", limit: int = 25, offset: int = 0,
                   now: Optional[datetime] = None) -> dict:
    """The actor's work items. `counts` = items per reason after the account scope and the search, before the
    reason filter — so a workbench tab's number does not move with the selected tab. Sort: the longest wait first
    (default), newest, or severity (a change ranks by its risk level)."""
    if reason and not set(reason) <= REASONS:
        raise ValueError(f"unknown reason {sorted(set(reason) - REASONS)}; expected one of {sorted(REASONS)}")
    if sort not in SORTS:
        raise ValueError(f"unknown sort {sort!r}; expected one of {list(SORTS)}")
    now = now or datetime.now(timezone.utc)
    with get_db_session() as s:
        items = _issue_items(s, actor, account_id, now)
        if settings.change_management_enabled:
            items += _change_items(s, actor, account_id)
    if q:
        items = [i for i in items if _matches(i, q)]
    counts: dict[str, int] = {}
    for i in items:
        counts[i["reason"]] = counts.get(i["reason"], 0) + 1
    if reason:
        items = [i for i in items if i["reason"] in reason]
    items.sort(key=_sort_key(sort))
    page = items[offset:offset + limit]
    for i in page:
        i["occurred_at"] = _iso(i["occurred_at"])
    return {"items": page, "total": len(items), "counts": counts,
            "next_cursor": str(offset + limit) if offset + limit < len(items) else None, "generated_at": _iso(now)}


def issue_rows(actor, *, account_id: Optional[int] = None, now: Optional[datetime] = None) -> list[dict]:
    """The actor's issue rows of the workbench, unsorted, `occurred_at` still a datetime — the Cases quick views
    (mine / failed / waiting long) are subsets of these, so the queue and the workbench never disagree."""
    now = now or datetime.now(timezone.utc)
    with get_db_session() as s:
        return _issue_items(s, actor, account_id, now)
