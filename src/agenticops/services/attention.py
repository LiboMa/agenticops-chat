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

from datetime import datetime, timezone
from typing import Optional

from agenticops.config import settings
from agenticops.models import ChangeRequest, FixExecution, FixPlan, HealthIssue, PipelineEvent, RCAResult, get_db_session
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


def _item(rid, ref, entity, reason, detail, title, account_id, occurred, route, actions) -> dict:
    return {"id": rid, "ref": ref, "entity": entity, "reason": reason, "reason_detail": detail, "title": title,
            "account_id": account_id, "occurred_at": occurred, "route": route, "available_actions": actions}


def _issue_items(s, actor, account_id, now) -> list[dict]:
    q = s.query(HealthIssue).filter(HealthIssue.status.in_(ISSUE_STATUSES))
    if account_id is not None:
        q = q.filter(HealthIssue.account_id == account_id)
    issues = q.all()
    if not issues:
        return []
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
    out = []
    for issue in issues:
        plans = plans_by.get(issue.id, [])
        plan = wp.current_fix_plan(plans)
        run, rca, events = runs.get(issue.id), rcas.get(issue.id), events_by.get(issue.id, [])
        auto = (plan is not None and plan.status == "approved" and wp.in_flight_auto_run(
            events, plan.id, timeout_seconds=settings.executor_total_timeout, now=now) is not None)
        phase = wp.issue_phase(issue.status, rca=rca, threshold=settings.rca_min_confidence_for_autofix,
                               plan=plan, latest_run=run, auto_run_in_flight=auto,
                               auto_fix_enabled=bool(settings.auto_fix_enabled))
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
        occurred = _aware(issue.last_seen or issue.detected_at)
        if reason == "approval_required":
            if not ua.strictly_allowed(actor, "plan.approve", plan):
                continue
            entity = {"entity_type": "fix_plan", "entity_id": plan.id, "content_version": plan.plan_version}
            route = f"/app/plans/{plan.id}"
            actions = [a for a in ua.plan_actions(plan, actor, issue_status=issue.status, run_in_flight=False)
                       if a["action"] == "approve"]
            occurred = _aware(plan.updated_at or plan.created_at)
        elif phase.sub == "notQueued":
            if plan is None or not ua.strictly_allowed(actor, "plan.execute", plan):
                continue
            actions = [a for a in ua.plan_actions(plan, actor, issue_status=issue.status, run_in_flight=auto)
                       if a["action"] == "execute"] or [{"action": "execute", "allowed": False,
                                                          "reason_code": "state", "effect": "queue_execution"}]
            occurred = _aware(plan.approved_at or plan.updated_at)
        elif phase.sub == "awaitingAcceptance":
            run_plan = next((p for p in plans if p.id == run.fix_plan_id), None)
            if run_plan is None or not ua.strictly_allowed(actor, "plan.approve", run_plan):
                continue
            actions = [_update(phase.primary)]
            occurred = _aware(run.completed_at or run.created_at)
        else:
            actions = [_update(phase.primary)]
            if run is not None and phase.sub in ("needsNewPlan", "passed", "unverified"):
                occurred = _aware(run.completed_at or run.created_at)
            elif phase.sub == "planRejected" and plan is not None:
                occurred = _aware(plan.rejected_at or plan.updated_at)
            elif rca is not None:
                occurred = _aware(rca.created_at)
        out.append(_item(f"I{issue.id}", f"I#{issue.id}", entity, reason, detail, issue.title, issue.account_id,
                         occurred or now, route, actions))
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
        out.append(_item(f"C{cr.id}", f"C#{cr.id}", entity, reason, detail, cr.title, cr.account_id,
                         _aware(cr.updated_at or cr.created_at), f"/app/changes/{cr.id}#{anchor}", actions))
    return out


def attention_page(actor, *, account_id: Optional[int] = None, limit: int = 25, offset: int = 0,
                   now: Optional[datetime] = None) -> dict:
    now = now or datetime.now(timezone.utc)
    with get_db_session() as s:
        items = _issue_items(s, actor, account_id, now)
        if settings.change_management_enabled:
            items += _change_items(s, actor, account_id)
    items.sort(key=lambda i: (i["occurred_at"], i["id"]), reverse=True)
    page = items[offset:offset + limit]
    for i in page:
        i["occurred_at"] = _iso(i["occurred_at"])
    return {"items": page, "total": len(items),
            "next_cursor": str(offset + limit) if offset + limit < len(items) else None, "generated_at": _iso(now)}
