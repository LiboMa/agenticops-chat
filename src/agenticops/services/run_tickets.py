"""The record of a run — one fix_executions row per run of the executor, from its start (MVP-2.9.0 N8).

Three things start the executor: a ticket queued by POST /api/fix-plans/{id}/execute, the CLI or a change and
claimed by ExecutorService; the thread an approval starts (pipeline_service._run_auto_execute); and Main calling
executor_agent in a chat turn. Until N8 only the first had a row while it worked, so only that one could be seen
on a page, cancelled, timed out, or closed when the agent ended without recording anything. A run of the other
two read as «approved» until it saved a result — and for executor_total_timeout if it never did.

open_ticket() gives such a run its record, moving the plan and the issue to «executing» as the queue does at
enqueue. close_ticket() is the one way a record is closed by anything other than its own result (a cancel, the
watchdog, a crash, the reconcile after a run that recorded nothing): the first closer wins, the executing plan
fails and — for a fix — the issue goes back to root_cause_identified with one timeline event, so it is on
somebody's list again. agents/run_guard.RunGuard reads ticket_state() before every tool call of the run.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

OPEN = ("pending", "running")


def open_ticket(fix_plan_id: int, *, executed_by: str) -> tuple[Optional[int], str]:
    """Open the record of a fix plan's run that has none → (execution id, "") or (None, why not).

    One transaction: the plan must be approved and have no pending / running record; it moves approved →
    executing (a compare-and-set: of two executors starting at once one is refused), its issue fix_approved →
    fix_executing, and a `running` row is inserted. A change plan gets (None, ""): its runs are always queued
    (change_service.request_execution), and executor_agent's own gate has already refused any other.
    """
    from agenticops.models import FixExecution, FixPlan, InvalidStatusTransition, get_db_session, transition_plan
    from agenticops.services.issue_state import advance_issue

    with get_db_session() as session:
        plan = session.query(FixPlan).filter_by(id=fix_plan_id).first()
        if plan is None:
            return None, f"FixPlan #{fix_plan_id} not found"
        if (plan.plan_kind or "fix") == "change":
            return None, ""
        live = (session.query(FixExecution.id)
                .filter(FixExecution.fix_plan_id == fix_plan_id, FixExecution.status.in_(OPEN))
                .order_by(FixExecution.id.desc()).first())
        if live:
            return None, f"a run of FixPlan #{fix_plan_id} is already in progress (Execution #{live[0]})"
        if plan.status != "approved":
            return None, f"FixPlan #{fix_plan_id} is '{plan.status}', not approved"
        try:
            transition_plan(plan, "executing")
        except InvalidStatusTransition as e:          # another executor, or a withdraw, moved it first
            return None, str(e)
        if plan.health_issue_id:
            advance_issue(session, plan.health_issue_id, "fix_executing", actor=executed_by,
                          reason=f"FixPlan #{plan.id} executing")
        ticket = FixExecution(fix_plan_id=fix_plan_id, health_issue_id=plan.health_issue_id, status="running",
                              started_at=datetime.now(timezone.utc), executed_by=executed_by)
        session.add(ticket)
        session.flush()
        return ticket.id, ""


def close_ticket(execution_id: int, ticket_status: str, message: str) -> bool:
    """Close a still-running record as `ticket_status`; its executing plan → failed; a fix's issue goes back to
    root_cause_identified; a change plan's request gets `ticket_status` through the change mapper.

    The record is the arbiter between the writers that close it — this one and save_execution_result — so the
    first write is a compare-and-set (`UPDATE … WHERE id=? AND status='running'`): only its winner goes on to the
    plan and the issue. False, and nothing written, when the record is missing or no longer running. The issue
    moves only from fix_executing (a compare-and-set too: one that was dismissed, resolved or sent back meanwhile
    stays where it is), and its diagnosis is NOT disputed — a cancel or a timeout says nothing about the cause.
    """
    from sqlalchemy import update
    from agenticops.models import FixExecution, FixPlan, InvalidStatusTransition, get_db_session, transition_plan
    from agenticops.security.redaction import redact_obj
    from agenticops.services.issue_state import IssueNotFound, transition_issue

    issue_id = None
    with get_db_session() as session:
        # Core UPDATE: past the ORM's before_flush secret scrubber, so the message is scrubbed here.
        closed = session.execute(
            update(FixExecution)
            .where(FixExecution.id == execution_id, FixExecution.status == "running")
            .values(status=ticket_status, completed_at=datetime.now(timezone.utc), error_message=redact_obj(message))
        )
        if closed.rowcount != 1:
            return False
        plan_id = session.query(FixExecution.fix_plan_id).filter_by(id=execution_id).scalar()
        plan = session.query(FixPlan).filter_by(id=plan_id).first()
        is_change = plan is not None and plan.plan_kind == "change"
        if plan is not None and plan.status == "executing":
            transition_plan(plan, "failed")
        if plan is not None and not is_change and plan.health_issue_id:
            issue_id = plan.health_issue_id
            try:
                transition_issue(session, issue_id, "root_cause_identified", actor="agent:executor",
                                 reason=f"Execution #{execution_id} {ticket_status}: {message}"[:500],
                                 expected="fix_executing")
            except (IssueNotFound, InvalidStatusTransition):
                pass                                  # the issue is not on this run any more: it stays where it is
        session.commit()
    if issue_id:
        from agenticops.services.pipeline_events import log_event
        log_event(issue_id, "execution_completed", "execution", "failed",
                  detail={"plan_id": plan_id, "execution_id": execution_id, "ticket": ticket_status,
                          "reason": (message or "")[:300]}, actor="agent:executor")
    # Change plan: feed the terminal to the change mapper after commit (a no-op unless its request is
    # executing). Best-effort: a post-commit side-effect must never crash the handler that closes the ticket.
    if is_change:
        try:
            from agenticops.services.change_service import on_execution_result
            on_execution_result(plan_id, ticket_status, error=message)
        except Exception:
            logger.warning("change on_execution_result failed for FixPlan #%s", plan_id, exc_info=True)
    return True


def ticket_state(execution_id: int) -> Optional[dict]:
    """What the run's record says now: {"status", "fix_plan_id"} — None when there is no such record."""
    from agenticops.models import FixExecution, get_db_session
    with get_db_session() as session:
        row = (session.query(FixExecution.status, FixExecution.fix_plan_id)
               .filter(FixExecution.id == execution_id).first())
    return {"status": row[0], "fix_plan_id": row[1]} if row else None
