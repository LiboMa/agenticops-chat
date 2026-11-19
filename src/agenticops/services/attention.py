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

from sqlalchemy import and_, func, or_

from agenticops.config import settings
from agenticops.models import (ChangeRequest, CloudResource, FixExecution, FixPlan, HealthIssue, PipelineEvent, RCAResult,
                               get_db_session)
from agenticops.services import agent_runs, exec_switches
from agenticops.services import ui_actions as ua
from agenticops.services import work_phases as wp

ISSUE_STATUSES = ("root_cause_identified", "fix_planned", "fix_approved", "fix_executed")
CHANGE_STATUSES = ("draft", "needs_clarification", "planned", "approved", "needs_review")
_FIX_TERMINAL = ("executed", "failed", "rejected")

# sub → (reason, reason_detail, hash anchor); awaitingApproval routes to the plan page instead
ISSUE_ROWS = {
    "rcaStopped": ("review_required", "rca_stopped", "diagnose"),
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


_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)      # «no status move on record»: earlier than any real time


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
SORTS = ("waiting_longest", "newest", "severity", "decision")
# MVP-2.8.0: the «在等我» tab of Issues groups the items by the decision they need, in this order; the web client's
# lib/inbox groupOf must agree (shared fixture tests/fixtures/attention_decision_groups.json)
DECISION_GROUPS = ("approval", "acceptance", "failed", "confirm")
DECISION_OF = {
    "approval_required": "approval",
    "verification_required": "acceptance",
    "execution_failed": "failed", "execution_not_started": "failed",
    "review_required": "confirm", "clarification_required": "confirm",
}
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
    # when the issue's newest diagnosis ended without a result, with nothing started since (N11); None otherwise
    rca_stopped_at: Optional[datetime] = None


def _since(issue, sub, plan, run, rca, now, stopped_at=None) -> datetime:
    if sub == "rcaStopped" and stopped_at is not None:
        ts = stopped_at
    elif sub == "awaitingApproval" and plan is not None:
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
    """Phase + waiting-since for each issue, in a fixed number of queries (plans, RCAs, runs, run events, last
    status moves). `since` is never earlier than the issue's last status move (MVP-2.9.0): a reopened issue has
    not waited since its old diagnosis — it was dismissed in between."""
    if not issues:
        return {}
    ids = [i.id for i in issues]
    moved = dict(s.query(PipelineEvent.health_issue_id, func.max(PipelineEvent.created_at))
                 .filter(PipelineEvent.health_issue_id.in_(ids), PipelineEvent.event_type == "status_changed")
                 .group_by(PipelineEvent.health_issue_id).all())
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
    # An issue still waiting for a diagnosis: did its newest one end without a result (N11)? One query for all.
    diagnosing = [i.id for i in issues if i.status in wp._DIAGNOSING]
    # … and its status moves, which say whether it has been outside the diagnosing statuses since.
    rca_events_by = _group(s.query(PipelineEvent.health_issue_id, PipelineEvent.event_type, PipelineEvent.created_at,
                                   PipelineEvent.detail).filter(
        PipelineEvent.health_issue_id.in_(diagnosing),
        PipelineEvent.event_type.in_(("rca_started", "rca_completed", "status_changed"))).all(),
        "health_issue_id") if diagnosing else {}
    out: dict[int, IssueWait] = {}
    auto_fix_on = exec_switches.effective().auto_fix_enabled      # the value in force, read once for the page
    for issue in issues:
        plans = plans_by.get(issue.id, [])
        plan = wp.current_fix_plan(plans)
        run, rca, events = runs.get(issue.id), rcas.get(issue.id), events_by.get(issue.id, [])
        auto = (plan is not None and plan.status == "approved" and wp.in_flight_auto_run(
            events, plan.id, timeout_seconds=settings.executor_total_timeout, now=now) is not None)
        its_events = rca_events_by.get(issue.id, ())
        stopped_at = wp.rca_stopped_at(issue.status, its_events, now=now, limit_seconds=agent_runs.limit_seconds(),
                                       moved_at=wp.left_diagnosing_at(its_events))
        # an agent that is on the issue and within its time limit will move it: then it is not a person's turn
        claim = agent_runs.in_time(issue.id, now=now)
        if stopped_at is not None and claim is not None:
            stopped_at = None
        phase = wp.issue_phase(issue.status, rca=rca, threshold=settings.rca_min_confidence_for_autofix,
                               plan=plan, latest_run=run, auto_run_in_flight=auto,
                               auto_fix_enabled=auto_fix_on, rca_stopped=stopped_at is not None)
        if claim is not None and phase.waiting_for in wp.HUMAN:
            # N14: the same for EVERY row a person would get. A plan being redone after «request changes», a
            # diagnosis being run again, a plan being written: the agent is on it now, and what it leaves decides
            # whose turn is next. Until it ends (or runs past its limit) the issue is in nobody's queue.
            out[issue.id] = IssueWait(wp.Phase("agentAtWork", f"{claim.agent}_agent", None), _aware(claim.started_at),
                                      plan, plans, run, rca, events, auto, None)
            continue
        since = max(_since(issue, phase.sub, plan, run, rca, now, stopped_at), _aware(moved.get(issue.id)) or _EPOCH)
        out[issue.id] = IssueWait(phase, since, plan, plans, run, rca, events, auto, stopped_at)
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
    # the four statuses a person moves on — and an issue still waiting for a diagnosis on which one has been TRIED
    # (N11; whether it stopped is decided below). Never-diagnosed `open` issues are not loaded: nothing ran on them.
    tried = (s.query(PipelineEvent.id).filter(PipelineEvent.health_issue_id == HealthIssue.id,
                                              PipelineEvent.event_type.in_(("rca_started", "rca_completed"))).exists())
    q = s.query(HealthIssue).filter(or_(HealthIssue.status.in_(ISSUE_STATUSES),
                                        and_(HealthIssue.status.in_(wp._DIAGNOSING), tried)))
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
        if phase.sub == "needsNewPlan" and getattr(run, "stop_requested_at", None) is not None:
            detail = "run_stopped"   # a person stopped the run (N9): the brief says so, not «the run failed»
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


def _sort_key(sort: str, snoozed_last: bool = False):
    """The order of a list. `snoozed_last` (MVP-2.9.0 N14, asked for by NewUI only): an item its reader snoozed goes
    to the end of its group — its severity, its decision group — or, in an ungrouped order, of the list."""
    later = (lambda i: bool(i.get("snoozed_until"))) if snoozed_last else (lambda i: False)
    if sort == "decision":    # by group, then the longest wait first: pages only ever append to the last group
        return lambda i: (DECISION_GROUPS.index(DECISION_OF[i["reason"]]), later(i), i["occurred_at"], i["id"])
    if sort == "newest":
        return lambda i: (later(i), -i["occurred_at"].timestamp(), i["id"])
    if sort == "severity":
        return lambda i: (_SEV_RANK.get(i["severity"] or "", _RISK_RANK.get(i["risk_level"] or "", 4)), later(i),
                          i["occurred_at"], i["id"])
    return lambda i: (later(i), i["occurred_at"], i["id"])   # waiting_longest: the longest wait first


def attention_page(actor, *, account_id: Optional[int] = None, reason: Optional[list[str]] = None,
                   q: Optional[str] = None, item: Optional[str] = None, sort: str = "waiting_longest", limit: int = 25,
                   offset: int = 0, now: Optional[datetime] = None, snooze_user_id: Optional[int] = None,
                   snoozed_last: bool = False) -> dict:
    """The actor's work items. `counts` = items per reason after the account scope and the search, before the
    reason filter — so a workbench tab's number does not move with the selected tab. Sort: the longest wait first
    (default), newest, severity (a change ranks by its risk level), or decision (grouped as DECISION_GROUPS, then
    the longest wait first). `item` ("I12" / "C3", MVP-2.9.0) keeps that one work item: whether it is on this
    actor's list, and as what — `q` cannot say (it also matches titles, resources and I#1 for I#10's digits).
    Every item carries `snoozed_until` (N14; services/attention_snooze): set while the person `snooze_user_id`
    has put it off — it still waits and still counts; `snoozed_last` moves it to the end of its group."""
    if reason and not set(reason) <= REASONS:
        raise ValueError(f"unknown reason {sorted(set(reason) - REASONS)}; expected one of {sorted(REASONS)}")
    if sort not in SORTS:
        raise ValueError(f"unknown sort {sort!r}; expected one of {list(SORTS)}")
    now = now or datetime.now(timezone.utc)
    items = attention_items(actor, account_id=account_id, now=now)
    from agenticops.services.attention_snooze import mark
    mark(items, snooze_user_id, now)
    if item:
        items = [i for i in items if i["id"] == item]
    if q:
        items = [i for i in items if _matches(i, q)]
    counts: dict[str, int] = {}
    for i in items:
        counts[i["reason"]] = counts.get(i["reason"], 0) + 1
    if reason:
        items = [i for i in items if i["reason"] in reason]
    items.sort(key=_sort_key(sort, snoozed_last))
    page = items[offset:offset + limit]
    for i in page:
        i["occurred_at"] = _iso(i["occurred_at"])
    return {"items": page, "total": len(items), "counts": counts,
            "next_cursor": str(offset + limit) if offset + limit < len(items) else None, "generated_at": _iso(now)}


def attention_items(actor, *, account_id: Optional[int] = None, now: Optional[datetime] = None) -> list[dict]:
    """Every work item waiting on the actor (issues, and changes when change management is on), unsorted, before any
    search or reason filter, `occurred_at` still a datetime — one source for the to-do list and its counts
    (services/nav_counts)."""
    now = now or datetime.now(timezone.utc)
    with get_db_session() as s:
        items = _issue_items(s, actor, account_id, now)
        if settings.change_management_enabled:
            items += _change_items(s, actor, account_id)
    return items


def issue_rows(actor, *, account_id: Optional[int] = None, now: Optional[datetime] = None) -> list[dict]:
    """The actor's issue rows of the workbench, unsorted, `occurred_at` still a datetime — the Cases quick views
    (mine / failed / waiting long) are subsets of these, so the queue and the workbench never disagree."""
    now = now or datetime.now(timezone.utc)
    with get_db_session() as s:
        return _issue_items(s, actor, account_id, now)
