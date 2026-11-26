"""A fix plan's runs and the issue's record around them — execute, the runs, an issue's timeline, notes and trace,
stop, cancel, accept, the executor's status (split from web/app.py)."""
import json
from typing import List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from agenticops.auth.actor import Actor
from agenticops.config import settings
from agenticops.models import AlertEvent, FixExecution, FixPlan, get_db_session, HealthIssue
from agenticops.web.deps import current_actor
from agenticops.web.schemas import (ExecutionAcceptBody, FixExecutionResponse, HealthIssueResponse, IssueNote,
                                    IssueNoteRequest)

router = APIRouter()


@router.post("/api/fix-plans/{plan_id}/execute", response_model=FixExecutionResponse, status_code=202)
async def api_execute_fix_plan(plan_id: int, actor: Actor = Depends(current_actor)):
    """Trigger execution of an approved fix plan as the authenticated actor (no body is read).

    Creates a FixExecution record in 'pending' status. The actual execution
    is handled asynchronously by the executor agent.
    """
    from agenticops.audit.service import Actions, AuditService, EntityTypes
    from agenticops.auth import authz
    from agenticops.models import InvalidStatusTransition, transition_plan
    with get_db_session() as session:
        plan = session.query(FixPlan).filter_by(id=plan_id).first()
        if not plan:
            raise HTTPException(status_code=404, detail="Fix plan not found")

        from agenticops.services.change_service import fix_path_refusal
        refusal = fix_path_refusal(plan, "executed")
        if refusal:
            raise HTTPException(status_code=409, detail=refusal)

        if plan.status != "approved":
            raise HTTPException(
                status_code=400,
                detail=f"Fix plan status is '{plan.status}', must be 'approved' to execute",
            )

        from agenticops.services import exec_switches
        if not exec_switches.effective().executor_enabled:
            raise HTTPException(
                status_code=403,
                detail="Executor is disabled. An administrator switches it on in Settings",
            )

        try:
            authz.check(actor, "plan.execute", subject=plan)
        except authz.AuthzDenied as e:
            raise HTTPException(status_code=403, detail=authz.http_detail(e))

        # A plan runs only while its issue waits for that run (N26: not once it is resolved or dismissed; N27: nor
        # once it moved anywhere else — it could not follow the run)
        from agenticops.services.issue_state import run_refusal
        cannot = run_refusal(session, plan.health_issue_id)
        if cannot:
            raise HTTPException(status_code=409, detail=cannot)

        # An approval's auto-run writes no row until it ends and leaves the plan 'approved': a second executor
        # must not run the same plan alongside it (2026-10-05 final review C1)
        from agenticops.services.pipeline_service import plan_run_in_flight
        if plan_run_in_flight(session, plan.id):
            raise HTTPException(status_code=409, detail="A run of this plan is already in progress")

        # Mark plan as executing; the issue moves with it
        try:
            transition_plan(plan, "executing")
        except InvalidStatusTransition as e:  # a concurrent execute / withdraw moved it first (CAS)
            raise HTTPException(status_code=409, detail=str(e))
        if plan.health_issue_id:
            from agenticops.services.issue_state import advance_issue
            advance_issue(session, plan.health_issue_id, "fix_executing", actor=actor.key,
                          reason=f"FixPlan #{plan.id} executing")

        execution = FixExecution(
            fix_plan_id=plan_id,
            health_issue_id=plan.health_issue_id,
            status="pending",
            executed_by=actor.key,
        )
        session.add(execution)
        session.flush()
        AuditService.log(Actions.PLAN_EXECUTE_REQUESTED, EntityTypes.FIX_PLAN, str(plan.id), actor=actor.key,
                         user_id=actor.user_id, details={"execution_id": execution.id}, session=session)
        return FixExecutionResponse.model_validate(execution)


@router.get("/api/fix-executions", response_model=List[FixExecutionResponse])
async def api_list_fix_executions(
    fix_plan_id: Optional[int] = None,
    health_issue_id: Optional[int] = None,
    status: Optional[str] = None,
    limit: int = Query(default=settings.default_list_limit, le=settings.max_list_limit),
    offset: int = 0,
):
    """List fix executions with optional filters."""
    with get_db_session() as session:
        query = session.query(FixExecution).order_by(FixExecution.created_at.desc())

        if fix_plan_id is not None:
            query = query.filter_by(fix_plan_id=fix_plan_id)
        if health_issue_id is not None:
            query = query.filter_by(health_issue_id=health_issue_id)
        if status:
            query = query.filter_by(status=status)

        executions = query.offset(offset).limit(limit).all()
        return [FixExecutionResponse.model_validate(e) for e in executions]


@router.get("/api/fix-executions/{execution_id}", response_model=FixExecutionResponse)
async def api_get_fix_execution(execution_id: int):
    """Get a specific fix execution with step-level results."""
    with get_db_session() as session:
        execution = session.query(FixExecution).filter_by(id=execution_id).first()
        if not execution:
            raise HTTPException(status_code=404, detail="Fix execution not found")
        return FixExecutionResponse.model_validate(execution)


@router.get("/api/health-issues/{issue_id}/executions", response_model=List[FixExecutionResponse])
async def api_list_issue_executions(issue_id: int):
    """List all fix executions for a specific health issue."""
    with get_db_session() as session:
        issue = session.query(HealthIssue).filter_by(id=issue_id).first()
        if not issue:
            raise HTTPException(status_code=404, detail="Health issue not found")

        executions = (
            session.query(FixExecution)
            .filter_by(health_issue_id=issue_id)
            .order_by(FixExecution.created_at.desc())
            .all()
        )
        return [FixExecutionResponse.model_validate(e) for e in executions]


@router.get("/api/health-issues/{issue_id}/timeline")
def api_get_issue_timeline(issue_id: int):
    """Get the pipeline event timeline for a health issue."""
    with get_db_session() as session:
        issue = session.query(HealthIssue).filter_by(id=issue_id).first()
        if not issue:
            raise HTTPException(status_code=404, detail="Health issue not found")

    from agenticops.services.pipeline_events import get_timeline
    return get_timeline(issue_id)


@router.post("/api/health-issues/{issue_id}/notes", response_model=IssueNote, status_code=201)
def api_add_issue_note(issue_id: int, data: IssueNoteRequest, actor: Actor = Depends(current_actor)):
    """Append a note to an issue's activity (MVP-2.7.0 S4) as the session actor — never edited, never deleted, and it
    does not move the issue. 404 → authz 403 → content 422; stored in this request's transaction or refused."""
    from agenticops.auth import authz
    from agenticops.services.issue_notes import NoteRejected, add_note

    with get_db_session() as session:
        issue = session.query(HealthIssue).filter_by(id=issue_id).first()
        if not issue:
            raise HTTPException(status_code=404, detail="Health issue not found")
        try:
            authz.check(actor, "issue.note", subject=issue)
        except authz.AuthzDenied as e:
            raise HTTPException(status_code=403, detail=str(e))
        try:
            ev, text = add_note(session, issue, data.content, actor)
        except NoteRejected as e:
            raise HTTPException(status_code=422, detail=str(e))
        session.commit()
        return IssueNote(event_id=ev.id, health_issue_id=issue.id, content=text, actor=ev.actor,
                         created_at=ev.created_at)


@router.get("/api/trace/{trace_id}")
async def api_get_trace(trace_id: str):
    """Get all artifacts linked to a pipeline trace ID."""
    from agenticops.models import PipelineEvent

    with get_db_session() as session:
        # Find linked HealthIssues
        issues = session.query(HealthIssue).filter_by(trace_id=trace_id).all()
        issue_ids = [i.id for i in issues]
        issues_data = [HealthIssueResponse.from_issue(i).model_dump(mode="json") for i in issues]

        # Find linked AlertEvents
        alert_events = session.query(AlertEvent).filter_by(trace_id=trace_id).all()
        alerts_data = [
            {
                "id": a.id, "source": a.source, "external_id": a.external_id,
                "severity": a.severity, "title": a.title,
                "health_issue_id": a.health_issue_id, "status": a.status,
                "received_at": a.received_at.isoformat() if a.received_at else None,
                "trace_id": a.trace_id,
            }
            for a in alert_events
        ]

        # Find PipelineEvents for all linked issues
        timeline = []
        if issue_ids:
            events = (
                session.query(PipelineEvent)
                .filter(PipelineEvent.health_issue_id.in_(issue_ids))
                .order_by(PipelineEvent.created_at.asc())
                .all()
            )
            timeline = [
                {
                    "id": e.id, "health_issue_id": e.health_issue_id,
                    "event_type": e.event_type, "stage": e.stage,
                    "status": e.status, "actor": e.actor,
                    "duration_ms": e.duration_ms,
                    "detail": json.loads(e.detail) if e.detail else None,
                    "created_at": e.created_at.isoformat() if e.created_at else None,
                    "trace_id": e.trace_id,
                }
                for e in events
            ]

    return {
        "trace_id": trace_id,
        "health_issues": issues_data,
        "alert_events": alerts_data,
        "timeline": timeline,
    }


@router.post("/api/fix-executions/{execution_id}/cancel")
def api_cancel_execution(execution_id: int, actor: Actor = Depends(current_actor)):
    """Cancel a running fix execution — authorized against the plan behind it (plan.execute for a fix
    plan, change.execute for a change plan; cancelling a run is executing it, not change.cancel) and
    audited (one plan.execution_cancelled row on success). An unknown/closed ticket is a 400 as before.
    Plain `def`: closing the record fails the plan, moves the issue and writes the timeline — under the name of
    the person who cancelled (round-2 review A-M7: it was written as the executor's)."""
    from agenticops.web.app import _executor_service  # here: app imports this router
    from agenticops.audit.service import Actions, AuditService, EntityTypes
    from agenticops.auth import authz
    with get_db_session() as session:
        plan = (session.query(FixPlan)
                .join(FixExecution, FixExecution.fix_plan_id == FixPlan.id)
                .filter(FixExecution.id == execution_id).first())
        if plan is None:
            raise HTTPException(status_code=400, detail="Execution not found or not in running state")
        plan_id = plan.id
        plan_kind = plan.plan_kind or "fix"
        try:
            if plan_kind == "change":
                authz.check(actor, "change.execute", subject=plan.change_request)
            else:
                authz.check(actor, "plan.execute", subject=plan)
        except authz.AuthzDenied as e:
            raise HTTPException(status_code=403, detail=authz.http_detail(e))
    if _executor_service.cancel_execution(execution_id, by=actor.key):
        AuditService.log(Actions.PLAN_EXECUTION_CANCELLED, EntityTypes.FIX_PLAN, str(plan_id),
                         actor=actor.key, user_id=actor.user_id,
                         details={"execution_id": execution_id, "plan_kind": plan_kind})
        return {"status": "cancelled", "execution_id": execution_id}
    raise HTTPException(status_code=400, detail="Execution not found or not in running state")


class StopExecutionBody(BaseModel):
    reason: str = Field(default="", max_length=2000)


@router.post("/api/fix-executions/{execution_id}/stop", response_model=FixExecutionResponse)
def api_stop_execution(execution_id: int, body: StopExecutionBody = Body(default_factory=StopExecutionBody),
                       actor: Actor = Depends(current_actor)):
    """A person stops a run in progress (MVP-2.9.0 N9). Unlike cancel, the run's record stays `running`: the
    executor finishes the command it is on, is refused every further step of the plan, may run only the plan's own
    rollback commands and read-only checks (agents/run_guard), and records what it did. Authorized like a cancel
    — plan.execute for a fix plan, change.execute for a change plan — so a request through an API key is refused
    (a human decision). 404 no such run · 403 · 409 `not_running` / `already_stopping`."""
    from agenticops.audit.service import Actions, AuditService, EntityTypes
    from agenticops.auth import authz
    from agenticops.services.issue_notes import reads_as_written
    from agenticops.services.run_tickets import request_stop
    note = body.reason.strip()
    if not reads_as_written(note):
        raise HTTPException(status_code=422, detail="the note may not contain control characters")
    with get_db_session() as session:
        ex = session.get(FixExecution, execution_id)
        plan = session.get(FixPlan, ex.fix_plan_id) if ex is not None else None
        if ex is None or plan is None:
            raise HTTPException(status_code=404, detail="Execution not found")
        plan_id, plan_kind = plan.id, plan.plan_kind or "fix"
        issue_id, change_id = plan.health_issue_id, plan.change_request_id
        try:
            if plan_kind == "change":
                authz.check(actor, "change.execute", subject=plan.change_request)
            else:
                authz.check(actor, "plan.execute", subject=plan)
        except authz.AuthzDenied as e:
            raise HTTPException(status_code=403, detail=authz.http_detail(e))
        if ex.status != "running":
            raise HTTPException(status_code=409, detail={
                "detail": f"This run is not in progress (it is '{ex.status}'); there is nothing to stop.",
                "code": "not_running", "status": ex.status})
        if ex.stop_requested_at is not None:
            raise HTTPException(status_code=409, detail={
                "detail": f"{ex.stop_requested_by or 'Someone'} already asked this run to stop.",
                "code": "already_stopping", "by": ex.stop_requested_by})
        # The stop and its audit row are ONE write (round-2 review A-M8: as three transactions, an audit write that
        # failed answered 500 for a stop that had taken effect, and the retry said «already stopping»).
        if not request_stop(execution_id, by=actor.key, note=note, session=session):
            session.expire(ex)                     # it ended, or someone else stopped it, between the read and the write
            code = "already_stopping" if ex.status == "running" else "not_running"
            raise HTTPException(status_code=409, detail={
                "detail": "This run ended, or was stopped by someone else, a moment ago.", "code": code,
                "status": ex.status})
        AuditService.log(Actions.PLAN_EXECUTION_STOP_REQUESTED, EntityTypes.FIX_PLAN, str(plan_id), actor=actor.key,
                         user_id=actor.user_id, details={"execution_id": execution_id, "plan_kind": plan_kind},
                         session=session)
    from agenticops.services.pipeline_events import log_event
    log_event(issue_id, "execution_stop_requested", "execution", "completed",
              detail={"execution_id": execution_id, "plan_id": plan_id, "by": actor.key,
                      **({"note": note[:2000]} if note else {})},
              actor=actor.key, change_request_id=change_id if plan_kind == "change" else None)
    with get_db_session() as session:
        return FixExecutionResponse.model_validate(session.get(FixExecution, execution_id))


@router.post("/api/fix-executions/{execution_id}/accept", response_model=FixExecutionResponse)
def api_accept_execution(execution_id: int, data: ExecutionAcceptBody, actor: Actor = Depends(current_actor)):
    """Accept or reject an execution pending acceptance (MVP-2.6.1): a fix moves its issue (fix_executed →
    resolved | root_cause_identified), a change goes through the change's resolve-review. The identity is the
    session's actor; authorized as the plan kind's approval, so a webhook actor is 403 even in shadow mode."""
    from agenticops.services.verification import AcceptanceError, accept_execution
    try:
        accept_execution(execution_id, actor=actor, decision=data.decision, reason=data.reason,
                         confirmed_checks=data.confirmed_checks)
    except AcceptanceError as e:
        from agenticops.auth import authz
        raise HTTPException(status_code=e.status_code, detail=authz.http_detail(e))
    with get_db_session() as session:
        return FixExecutionResponse.model_validate(session.get(FixExecution, execution_id))


@router.get("/api/executor/status")
async def api_executor_status():
    """Get executor service status."""
    from agenticops.web.app import _executor_service  # here: app imports this router
    from agenticops.services import exec_switches
    return {
        "enabled": exec_switches.effective().executor_enabled,
        "running": _executor_service.is_running,
        "active_executions": _executor_service.active_count,
        "poll_interval": settings.executor_poll_interval,
        "auto_resolve": settings.executor_auto_resolve,
    }
