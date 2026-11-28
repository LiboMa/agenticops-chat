"""Fix plans — list, read, create, edit, approve, reject, the previous version's diff, «request changes», delete (split
from web/app.py)."""
import logging
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy import or_

from agenticops.auth.actor import Actor
from agenticops.config import settings
from agenticops.models import ChangeRequest, FixExecution, FixPlan, get_db_session, HealthIssue, RCAResult
from agenticops.services.listing import like_pattern
from agenticops.services.plan_content import approval_conflict, repair_stale_hash, stamp_approval, stamp_content
from agenticops.web.deps import current_actor
from agenticops.web.routers.issue_agents import claim_issue, launch_issue_agent
from agenticops.web.schemas import (FixPlanApproveBody, FixPlanChangesBody, FixPlanCreate, FixPlanRejectBody,
                                    FixPlanResponse, FixPlanUpdate)

router = APIRouter()
logger = logging.getLogger(__name__)


def _issue_target(issue) -> dict:
    md = issue.metric_data if isinstance(issue.metric_data, dict) else {}
    return {"resource_id": issue.resource_id or None, "resource_ref": issue.resource_ref,
            "anchor_status": issue.anchor_status, "resource_type": md.get("resource_type") or None,
            "region": md.get("region") or None}


def _fix_plan_rows(session, plans, actor: Optional[Actor]) -> list:
    """Responses for these plans with their issue's context and the actor's actions — a fixed number of queries
    whatever the count (MVP-2.7.0 S3)."""
    from agenticops.services.pipeline_service import runs_in_flight
    from agenticops.services.ui_actions import plan_actions
    issue_ids = {p.health_issue_id for p in plans if p.health_issue_id}
    issues = ({i.id: i for i in session.query(HealthIssue).filter(HealthIssue.id.in_(issue_ids)).all()}
              if issue_ids else {})
    cr_ids = {p.change_request_id for p in plans if p.change_request_id}
    cr_accounts = (dict(session.query(ChangeRequest.id, ChangeRequest.account_id)
                        .filter(ChangeRequest.id.in_(cr_ids)).all()) if cr_ids else {})
    approved = [p for p in plans if p.status == "approved"]
    flying = runs_in_flight(session, approved) if approved and actor is not None else set()
    out = []
    for p in plans:
        resp = FixPlanResponse.model_validate(p)
        issue = issues.get(p.health_issue_id)
        if issue is not None:
            resp.account_id, resp.issue_title, resp.issue_status = issue.account_id, issue.title, issue.status
            resp.target = _issue_target(issue)
        elif p.change_request_id:
            resp.account_id = cr_accounts.get(p.change_request_id)
        if actor is not None:
            resp.available_actions = plan_actions(p, actor, issue_status=issue.status if issue else None,
                                                  run_in_flight=p.id in flying)
        out.append(resp)
    return out


def _fix_plan_response(session, plan, actor: Optional[Actor] = None) -> FixPlanResponse:
    return _fix_plan_rows(session, [plan], actor)[0]


def _reject_plan(session, plan, actor: Actor, reason: str) -> None:
    """Shared by POST /reject and the deprecated PUT status alias. Raises HTTPException 403 / 409
    (409 also for a change plan — it belongs to its change request).
    The audit row is added to the caller's session — decision and state commit together."""
    from agenticops.audit.service import Actions, AuditService, EntityTypes
    from agenticops.auth import authz
    from agenticops.models import InvalidStatusTransition, transition_plan
    from agenticops.services.change_service import fix_path_refusal
    refusal = fix_path_refusal(plan, "rejected")
    if refusal:
        raise HTTPException(status_code=409, detail=refusal)
    if plan.status == "rejected":
        # validate_plan_transition treats current == new as a no-op, so without this guard a second reject
        # would silently overwrite rejected_by / rejected_at / rejection_reason. rejected is terminal → 409.
        raise HTTPException(status_code=409, detail="Fix plan is already rejected")
    try:
        authz.check(actor, "plan.reject", subject=plan)
    except authz.AuthzDenied as e:
        raise HTTPException(status_code=403, detail=authz.http_detail(e))
    if plan.status == "approved":
        # an approval's auto-run writes no row until it ends: withdrawing now would leave the executor running while
        # the issue invites a new plan (final review I5)
        from agenticops.services.pipeline_service import plan_run_in_flight
        if plan_run_in_flight(session, plan.id):
            raise HTTPException(status_code=409, detail="A run of this plan is in progress; it cannot be withdrawn now")
    old = plan.status
    try:
        transition_plan(plan, "rejected")
    except InvalidStatusTransition as e:
        raise HTTPException(status_code=409, detail=str(e))
    if old == "approved" and plan.health_issue_id:
        # withdrawn before it ran: the issue goes back to root_cause_identified (the 2.6.1 back-edge) so its page
        # offers a new plan instead of a retry the execute endpoint would refuse
        from agenticops.services.issue_state import IssueStatusConflict, transition_issue
        issue = session.get(HealthIssue, plan.health_issue_id)
        if issue is not None and issue.status == "fix_approved":
            try:
                transition_issue(session, issue.id, "root_cause_identified", actor=actor.key,
                                 reason=f"FixPlan #{plan.id} withdrawn before it ran", expected="fix_approved")
            except IssueStatusConflict as e:
                raise HTTPException(status_code=409, detail=str(e))
    plan.rejected_by = actor.key
    plan.rejected_at = datetime.now(timezone.utc)
    plan.rejection_reason = reason
    AuditService.log(Actions.PLAN_REJECTED, EntityTypes.FIX_PLAN, str(plan.id), actor=actor.key,
                     user_id=actor.user_id, details={"reason": reason, "risk_level": plan.risk_level},
                     old_values={"status": old}, new_values={"status": "rejected"}, session=session)


@router.get("/api/fix-plans", response_model=List[FixPlanResponse])
def api_list_fix_plans(
    status: Optional[str] = None,
    risk_level: Optional[str] = None,
    health_issue_id: Optional[int] = None,
    account_id: Optional[int] = Query(None),
    kind: Optional[str] = Query(None, pattern="^(fix|change)$"),
    q: Optional[str] = Query(None, max_length=100),
    limit: int = Query(default=settings.default_list_limit, le=settings.max_list_limit),
    offset: int = Query(default=0, ge=0),
    actor: Actor = Depends(current_actor),
):
    """List fix plans (`kind` = fix | change; `status` = one or a comma list; `q` = id / title / target)."""
    import re
    from agenticops.models import VALID_PLAN_STATUSES
    statuses = [x.strip() for x in status.split(",") if x.strip()] if status else []
    bad = [x for x in statuses if x not in VALID_PLAN_STATUSES]
    if bad:
        raise HTTPException(status_code=422, detail=f"invalid status {bad}; expected one of {sorted(VALID_PLAN_STATUSES)}")
    with get_db_session() as session:
        query = session.query(FixPlan).order_by(FixPlan.created_at.desc(), FixPlan.id.desc())
        if kind:
            query = query.filter_by(plan_kind=kind)
        if statuses:
            query = query.filter(FixPlan.status.in_(statuses))
        if risk_level:
            query = query.filter_by(risk_level=risk_level)
        if health_issue_id:
            query = query.filter_by(health_issue_id=health_issue_id)
        term = (q or "").strip()
        if account_id is not None or term:
            # a fix plan's account / target is its HealthIssue's, a change plan's account its ChangeRequest's
            query = (query.outerjoin(HealthIssue, FixPlan.health_issue_id == HealthIssue.id)
                          .outerjoin(ChangeRequest, FixPlan.change_request_id == ChangeRequest.id))
        if account_id is not None:
            query = query.filter(or_(HealthIssue.account_id == account_id, ChangeRequest.account_id == account_id))
        if term:
            like = like_pattern(term)
            conds = [FixPlan.title.ilike(like, escape="\\"), HealthIssue.title.ilike(like, escape="\\"),
                     HealthIssue.resource_id.ilike(like, escape="\\")]
            # I#n is an issue, P#n / #n a plan, a bare number either
            num = re.fullmatch(r"([IiPp]?)(#?)(\d{1,9})", term)
            if num:
                n = int(num.group(3))
                is_issue = num.group(1).lower() == "i"
                is_plan = num.group(1).lower() == "p" or (not num.group(1) and num.group(2) == "#")
                if not is_plan:
                    conds.append(FixPlan.health_issue_id == n)
                if not is_issue:
                    conds.append(FixPlan.id == n)
            query = query.filter(or_(*conds))
        plans = query.offset(offset).limit(limit).all()
        return _fix_plan_rows(session, plans, actor)


@router.get("/api/fix-plans/{plan_id}", response_model=FixPlanResponse)
def api_get_fix_plan(plan_id: int, actor: Actor = Depends(current_actor)):
    """Get fix plan by ID, with its issue's context and the actor's actions."""
    with get_db_session() as session:
        plan = session.query(FixPlan).filter_by(id=plan_id).first()
        if not plan:
            raise HTTPException(status_code=404, detail="Fix plan not found")
        return _fix_plan_response(session, plan, actor)


@router.post("/api/fix-plans", response_model=FixPlanResponse, status_code=201)
async def api_create_fix_plan(data: FixPlanCreate):
    """Create a new fix plan."""
    with get_db_session() as session:
        # Validate health_issue_id exists
        issue = session.query(HealthIssue).filter_by(id=data.health_issue_id).first()
        if not issue:
            raise HTTPException(status_code=400, detail="Health issue not found")

        # Validate rca_result_id exists
        rca = session.query(RCAResult).filter_by(id=data.rca_result_id).first()
        if not rca:
            raise HTTPException(status_code=400, detail="RCA result not found")

        # Guard: reject ANY non-terminal plan (including drafts).
        # Unlike generate-fix-plan (which delegates to SRE agent with
        # in-place update), direct API creation should not silently replace.
        from agenticops.models import FIXPLAN_TERMINAL_STATUSES
        active = (
            session.query(FixPlan)
            .filter_by(health_issue_id=data.health_issue_id)
            .filter(FixPlan.status.notin_(FIXPLAN_TERMINAL_STATUSES))
            .first()
        )
        if active:
            raise HTTPException(
                status_code=409,
                detail=f"Issue #{data.health_issue_id} already has active FixPlan #{active.id} ({active.status}). "
                       f"Complete or reject it before creating a new one.",
            )

        plan = FixPlan(
            health_issue_id=data.health_issue_id,
            rca_result_id=data.rca_result_id,
            risk_level=data.risk_level,
            title=data.title,
            summary=data.summary,
            steps=data.steps,
            rollback_plan=data.rollback_plan,
            estimated_impact=data.estimated_impact,
            pre_checks=data.pre_checks,
            post_checks=data.post_checks,
        )
        session.add(plan)
        stamp_content(session, plan)
        session.flush()
        return FixPlanResponse.model_validate(plan)


# FixPlanUpdate content fields (everything except the deprecated `status` alias). Editing any of these
# is gated by plan.edit and is refused once the plan is locked (approved / executing / terminal).
_FIXPLAN_CONTENT_FIELDS = {"risk_level", "title", "summary", "steps", "rollback_plan",
                           "estimated_impact", "pre_checks", "post_checks"}


@router.put("/api/fix-plans/{plan_id}", response_model=FixPlanResponse)
async def api_update_fix_plan(plan_id: int, data: FixPlanUpdate, actor: Actor = Depends(current_actor)):
    """Update plan CONTENT. Status changes must use /approve, /reject, /execute
    (status="rejected" is kept as a deprecated alias for the pre-2.6 UI).

    Content is immutable once the plan is approved/executing or terminal (409). A content edit is
    authorized (plan.edit) and audited — one plan.edited row carrying only the fields that changed. A
    PUT that changes nothing writes no row and does not bump updated_at. The content-free reject alias
    is NOT a content edit: it stays gated by plan.reject and keeps its transition-409 behavior."""
    from agenticops.audit.service import Actions, AuditService, EntityTypes
    from agenticops.auth import authz
    from agenticops.models import FIXPLAN_TERMINAL_STATUSES
    with get_db_session() as session:
        plan = session.query(FixPlan).filter_by(id=plan_id).first()
        if not plan:
            raise HTTPException(status_code=404, detail="Fix plan not found")
        from agenticops.services.change_service import fix_path_refusal
        refusal = fix_path_refusal(plan, "edited")
        if refusal:
            raise HTTPException(status_code=409, detail=refusal)
        update_data = data.model_dump(exclude_unset=True)
        status_alias = update_data.pop("status", None)
        update_data.pop("content_hash", None)
        if status_alias is not None and status_alias != "rejected":
            raise HTTPException(status_code=400, detail="Status changes must use /approve, /reject or /execute")
        content_present = any(k in update_data for k in _FIXPLAN_CONTENT_FIELDS)
        if content_present:
            if plan.status in (FIXPLAN_TERMINAL_STATUSES | {"approved", "executing"}):
                raise HTTPException(status_code=409,
                                    detail=f"This plan's content is locked at status '{plan.status}'; edits are not allowed.")
            try:
                authz.check(actor, "plan.edit", subject=plan)
            except authz.AuthzDenied as e:
                raise HTTPException(status_code=403, detail=str(e))
            # MVP-2.7.0 S3: an edit names the content it was made against — a plan changed since is refused
            if not data.content_hash:
                raise HTTPException(status_code=422, detail="content_hash is required to edit a plan's content")
            conflict = approval_conflict(session, plan, data.content_hash)
            if conflict:
                if repair_stale_hash(session, plan):  # the stored hash was not of the stored content: the reload shows one that is
                    session.commit()
                raise HTTPException(status_code=409, detail=conflict)
        changed_old, changed_new = {}, {}
        for key, value in update_data.items():
            current = getattr(plan, key)
            if current != value:
                changed_old[key] = current
                changed_new[key] = value
                setattr(plan, key, value)
        if status_alias == "rejected":
            from agenticops.services.plan_content import DEPRECATED_REJECT
            _reject_plan(session, plan, actor, DEPRECATED_REJECT)
        if changed_new:
            AuditService.log(Actions.PLAN_EDITED, EntityTypes.FIX_PLAN, str(plan.id), actor=actor.key,
                             user_id=actor.user_id, details={"fields": sorted(changed_new)},
                             old_values=changed_old, new_values=changed_new, session=session)
            plan.updated_at = datetime.now(timezone.utc)  # bump only when content actually changed
            stamp_content(session, plan)
        session.flush()
        return _fix_plan_response(session, plan, actor)


@router.put("/api/fix-plans/{plan_id}/approve", response_model=FixPlanResponse)
async def api_approve_fix_plan(plan_id: int, data: FixPlanApproveBody, actor: Actor = Depends(current_actor)):
    """Approve a plan as the authenticated actor. The body's approved_by is a legacy claimed name:
    it is audited (details.claimed_name) but never stored as the approver. The L2/L3 agent ceiling
    is enforced by rbac (no-agent-approval-above-l1, enforce: always) on the resolved actor.
    content_hash is required (422 without it): it is the plan the approver reviewed, and a plan whose
    content has changed since is refused (409). The approval records the hash and version it approved.
    Checks run 404 → 403 → state 409 → hash 409: a caller who may not approve learns nothing about the plan."""
    from agenticops.audit.service import Actions, AuditService, EntityTypes
    from agenticops.auth import authz
    from agenticops.models import InvalidStatusTransition, transition_plan
    from agenticops.services.issue_state import closed_issue_refusal
    with get_db_session() as session:
        plan = session.query(FixPlan).filter_by(id=plan_id).first()
        if not plan:
            raise HTTPException(status_code=404, detail="Fix plan not found")
        try:
            authz.check(actor, "plan.approve", subject=plan)
        except authz.AuthzDenied as e:
            raise HTTPException(status_code=403, detail=authz.http_detail(e))
        from agenticops.services.change_service import fix_path_refusal
        refusal = fix_path_refusal(plan, "approved")
        if refusal:
            raise HTTPException(status_code=409, detail=refusal)
        # An already-decided plan is a state conflict (409, as reject reports it), not a bad request.
        if plan.status == "approved":
            raise HTTPException(status_code=409, detail="Fix plan is already approved")
        if plan.status == "rejected":
            raise HTTPException(status_code=409, detail="Fix plan was rejected. Create a new plan instead")
        closed = closed_issue_refusal(session, plan.health_issue_id)
        if closed:
            raise HTTPException(status_code=409, detail=closed)
        conflict = approval_conflict(session, plan, data.content_hash)
        if conflict:
            # The stored hash was not of the stored content: the reload shows one that is. Only for a plan that still
            # waits for approval — one that is executing or has run is refused just below, and its columns are the
            # record of what was approved and run (round-2 review C-M1).
            if plan.status in ("draft", "pending_approval") and repair_stale_hash(session, plan):
                session.commit()
            raise HTTPException(status_code=409, detail=conflict)
        old = plan.status
        try:
            transition_plan(plan, "approved")
        except InvalidStatusTransition as e:
            raise HTTPException(status_code=409, detail=str(e))
        plan.approved_by = actor.key
        plan.approved_at = datetime.now(timezone.utc)
        stamp_approval(session, plan)
        # Sync HealthIssue status (change plans have no issue)
        if plan.health_issue_id:
            from agenticops.services.issue_state import advance_issue
            advance_issue(session, plan.health_issue_id, "fix_approved", actor=actor.key,
                          reason=f"FixPlan #{plan.id} approved")
        details = {"reason": data.reason, "risk_level": plan.risk_level, "plan_kind": plan.plan_kind}
        if data.approved_by and actor.kind == "web":
            details["claimed_name"] = data.approved_by
        AuditService.log(Actions.PLAN_APPROVED, EntityTypes.FIX_PLAN, str(plan.id), actor=actor.key,
                         user_id=actor.user_id, details=details,
                         old_values={"status": old}, new_values={"status": "approved"}, session=session)
        # Capture plan_id before session closes
        approved_plan_id = plan.id
        session.flush()
        response = _fix_plan_response(session, plan, actor)

    # Chain to auto-execute (outside DB session); the answer says whether the run was queued
    queued = False
    try:
        from agenticops.services.pipeline_service import trigger_auto_execute
        queued = bool(trigger_auto_execute(approved_plan_id))
    except Exception:
        logger.warning("Failed to trigger auto-execute for plan #%d", approved_plan_id, exc_info=True)
    response.run_queued = queued

    return response


@router.post("/api/fix-plans/{plan_id}/reject", response_model=FixPlanResponse)
async def api_reject_fix_plan(plan_id: int, data: FixPlanRejectBody, actor: Actor = Depends(current_actor)):
    """Reject a draft / pending / approved (withdraw) plan with a mandatory reason."""
    with get_db_session() as session:
        plan = session.query(FixPlan).filter_by(id=plan_id).first()
        if not plan:
            raise HTTPException(status_code=404, detail="Fix plan not found")
        _reject_plan(session, plan, actor, data.reason)
        session.flush()
        return _fix_plan_response(session, plan, actor)


@router.get("/api/fix-plans/{plan_id}/previous-diff")
def api_fix_plan_previous_diff(plan_id: int):
    """What this fix plan changed relative to the plan before it on the same issue, and what became of that one
    (MVP-2.9.0 N14; services/plan_content.previous_plan_diff). `previous` is null for an issue's first plan.
    Plain `def`: DB work."""
    from agenticops.services.plan_content import previous_plan_diff
    with get_db_session() as session:
        plan = session.query(FixPlan).filter_by(id=plan_id).first()
        if not plan:
            raise HTTPException(status_code=404, detail="Fix plan not found")
        return previous_plan_diff(session, plan)


@router.post("/api/fix-plans/{plan_id}/request-changes", status_code=202)
def api_request_plan_changes(plan_id: int, data: FixPlanChangesBody, actor: Actor = Depends(current_actor)):
    """Send a fix plan that waits for approval back AND ask the plan agent for the next one — both, or neither
    (MVP-2.9.0 N14). The reason is the person's; the agent asked for the next plan is given it
    (sre_agent.rejection_feedback). Plain `def`: it writes.

    404 → 409 (a change plan; `not_awaiting_approval`; `issue_closed`) → 422 (no reason) → 409 `plan_changed` (the
    request names the content it was shown, and the plan is no longer that: the reason would be sent to the agent
    with a plan the reviewer never read) → 403 / 409 of a rejection → 409 `agent_run_in_flight` (an agent is on
    the issue: the plan is NOT sent back) → 202. The rejection is written first and committed only once the issue
    is claimed for the plan agent, so a refusal leaves nothing behind; the claim is released if the commit or the
    thread fails."""
    from agenticops.services import agent_runs
    from agenticops.services.change_service import fix_path_refusal
    reason = data.reason.strip()
    run = None
    try:
        with get_db_session() as session:
            plan = session.query(FixPlan).filter_by(id=plan_id).first()
            if not plan:
                raise HTTPException(status_code=404, detail="Fix plan not found")
            refusal = fix_path_refusal(plan, "sent back")
            if refusal:
                raise HTTPException(status_code=409, detail=refusal)
            if plan.status not in ("draft", "pending_approval"):
                return JSONResponse(status_code=409, content={
                    "detail": f"Fix plan #{plan.id} is '{plan.status}': only a plan that waits for approval can be sent back for changes.",
                    "code": "not_awaiting_approval", "status": plan.status})
            issue = session.get(HealthIssue, plan.health_issue_id)
            if issue is None or issue.status in ("resolved", "dismissed"):
                return JSONResponse(status_code=409, content={
                    "detail": f"Issue #{plan.health_issue_id} is closed; reopen it before asking for a new plan.",
                    "code": "issue_closed", "status": issue.status if issue else None})
            if not reason:
                raise HTTPException(status_code=422, detail="a reason is required")
            if data.content_hash is not None:
                changed = approval_conflict(session, plan, data.content_hash)
                if changed:
                    return JSONResponse(status_code=409, content={"detail": changed, "code": "plan_changed"})
            issue_id, trace_id = issue.id, issue.trace_id
            _reject_plan(session, plan, actor, reason)          # 403 / 409; added to this session, not committed yet
            session.flush()
            run, busy = claim_issue("sre", issue_id, actor)
            if busy is not None:
                session.rollback()                              # an agent is on the issue: the plan stays as it was
                return busy
    except BaseException:
        if run is not None:
            agent_runs.end(run)                                 # the commit failed: nobody is going to work under it
        raise
    launch_issue_agent("sre", issue_id, trace_id, actor, run, detail={"after_plan": plan_id})
    return JSONResponse(status_code=202, content={
        "message": f"Fix plan #{plan_id} sent back; a new plan was requested for issue #{issue_id}.",
        "health_issue_id": issue_id, "fix_plan_id": plan_id})


@router.delete("/api/fix-plans/{plan_id}", status_code=204)
def api_delete_fix_plan(plan_id: int, actor: Actor = Depends(current_actor)):
    """Delete a fix plan. Withdrawing a plan is a reject by another name, so it needs `plan.reject` — and through
    an API key it is refused like one (MVP-2.8.0 final review: a read-write key withdrew a pending plan unchecked)."""
    from agenticops.auth import authz
    with get_db_session() as session:
        plan = session.query(FixPlan).filter_by(id=plan_id).first()
        if not plan:
            raise HTTPException(status_code=404, detail="Fix plan not found")
        try:
            authz.check(actor, "plan.reject", subject=plan)
        except authz.AuthzDenied as e:
            raise HTTPException(status_code=403, detail=authz.http_detail(e))
        from agenticops.services.change_service import fix_path_refusal
        refusal = fix_path_refusal(plan, "deleted")
        if refusal:
            raise HTTPException(status_code=409, detail=refusal)
        # A plan that is running, or has run, is part of a record (MVP-2.9.0 N8): its runs point at it. Until then
        # the route had no state check — the plan of a run in progress could be removed under the executor, and
        # one with a finished run answered 500 (the run rows' foreign key).
        from agenticops.services.pipeline_service import plan_run_in_flight
        from agenticops.services.run_tickets import OPEN
        runs = session.query(FixExecution.status).filter(FixExecution.fix_plan_id == plan.id).all()
        if plan.status == "executing" or any(st in OPEN for (st,) in runs) or plan_run_in_flight(session, plan.id):
            raise HTTPException(status_code=409, detail="A run of this plan is in progress; it cannot be deleted now")
        if runs:
            raise HTTPException(status_code=409, detail=f"This plan has run ({len(runs)} run record"
                                f"{'s' if len(runs) != 1 else ''}); it is kept with them and cannot be deleted")
        session.delete(plan)
