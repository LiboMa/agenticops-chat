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
from agenticops.utils.timeutils import as_utc

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
    from agenticops.services.issue_state import advance_issue, run_refusal

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
        cannot = run_refusal(session, plan.health_issue_id)     # N26 / N27: only while the issue waits for this run
        if cannot:
            return None, cannot
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


def claim_refusal(fix_plan_id: int) -> Optional[str]:
    """Why a queued ticket of this fix plan is not run now that it is claimed (issue_state.run_refusal, claimed):
    its issue was closed — or moved — while the ticket waited. The command line's ticket can wait without limit
    (no web process polling), so «a window of seconds» was not true (MVP-2.9.0 N27, review). None for a change
    plan and for an issue that still waits."""
    from agenticops.models import FixPlan, get_db_session
    from agenticops.services.issue_state import run_refusal
    with get_db_session() as session:
        plan = session.query(FixPlan).filter_by(id=fix_plan_id).first()
        if plan is None or (plan.plan_kind or "fix") == "change":
            return None
        return run_refusal(session, plan.health_issue_id, claimed=True)


def close_ticket(execution_id: int, ticket_status: str, message: str, *, by: Optional[str] = None) -> bool:
    """Close a still-running record as `ticket_status`; its executing plan → failed; a fix's issue goes back to
    root_cause_identified; a change plan's request gets `ticket_status` through the change mapper. `by` is the
    person who closed it (a cancel): the issue's move and the run's end on the timeline are theirs; without one
    they are the executor's (a timeout, a reconcile).

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

    issue_id, actor = None, (by or "agent:executor")
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
                transition_issue(session, issue_id, "root_cause_identified", actor=actor,
                                 reason=f"Execution #{execution_id} {ticket_status}: {message}"[:500],
                                 expected="fix_executing")
            except (IssueNotFound, InvalidStatusTransition):
                pass                                  # the issue is not on this run any more: it stays where it is
        session.commit()
    if issue_id:
        from agenticops.services.pipeline_events import log_event
        log_event(issue_id, "execution_completed", "execution", "failed",
                  detail={"plan_id": plan_id, "execution_id": execution_id, "ticket": ticket_status,
                          "reason": (message or "")[:300]}, actor=actor)
    # Change plan: feed the terminal to the change mapper after commit (a no-op unless its request is
    # executing). Best-effort: a post-commit side-effect must never crash the handler that closes the ticket.
    if is_change:
        try:
            from agenticops.services.change_service import on_execution_result
            on_execution_result(plan_id, ticket_status, error=message)
        except Exception:
            logger.warning("change on_execution_result failed for FixPlan #%s", plan_id, exc_info=True)
    return True


def unrecorded_reason(execution_id: int, outcome: str = "") -> str:
    """Why a run that ended without recording a result is closed — one sentence whoever closes it (the executor's
    own `finally`, the queue's worker): what the agent last said, and — when a person had stopped the run — that
    no rollback is on record."""
    state = ticket_state(execution_id) or {}
    if state.get("stopped_by"):
        return (f"Stopped by {state['stopped_by']}; the executor ended without recording a result — "
                f"no rollback is on record. {(outcome or '')[:200]}")
    return f"Executor ended without recording a result: {(outcome or '')[:300]}"


def close_unrecorded(execution_id: int, outcome: str = "") -> bool:
    """Close a run that ended without recording a result, as failed (unrecorded_reason). False, and nothing
    written, when the record is already closed."""
    return close_ticket(execution_id, "failed", unrecorded_reason(execution_id, outcome))


def request_stop(execution_id: int, *, by: str, note: str = "", session=None) -> bool:
    """A person asks for a run in progress to stop (MVP-2.9.0 N9). The record is NOT closed: a closed record takes
    no result, and the agent must still be able to roll back and record what it did. From the next tool call on,
    agents/run_guard lets through only reads, the recording tools and the plan's own rollback commands.
    A compare-and-set: False when the record is missing, not running, or already has a stop request.
    With `session` the write joins the caller's transaction (the route writes the stop and its audit row together)."""
    from sqlalchemy import update
    from agenticops.models import FixExecution, get_db_session
    from agenticops.security.redaction import redact_obj

    def write(s) -> bool:
        done = s.execute(
            update(FixExecution)
            .where(FixExecution.id == execution_id, FixExecution.status == "running",
                   FixExecution.stop_requested_at.is_(None))
            .values(stop_requested_at=datetime.now(timezone.utc), stop_requested_by=(by or "")[:255],
                    stop_note=redact_obj((note or "")[:2000]) or None)
        )
        return done.rowcount == 1
    if session is not None:
        return write(session)
    with get_db_session() as own:
        return write(own)


ORPHAN_MARGIN_SECONDS = 120
ORPHANED = "The process that ran it ended before a result was recorded (a restart or a crash)"


def close_orphans() -> tuple[list[int], list]:
    """Runs a process that is gone left `running` — called once when the service starts (round-2 review A-I3).

    The timer that times a run out and the reconcile that closes one that recorded nothing both live in the process
    that runs it; after a restart nothing closed the record, so its issue stayed «executing» on nobody's list and
    neither a new run nor a new plan could start. Since N8 every fix run has such a record.

    A record older than executor_total_timeout plus a margin is closed as failed now: a run that is still alive in
    another process (the CLI) has been closed by that process's own timer by then. A younger one gets a timer for
    the moment it reaches that age — the same compare-and-set, so a run that ends by itself first is left as it
    ended. With no time limit configured (0) an old record proves nothing, and nothing is closed.
    → (the ids closed now, the timers started)"""
    import threading
    from agenticops.config import settings
    from agenticops.models import FixExecution, get_db_session
    limit = settings.executor_total_timeout or 0
    if limit <= 0:
        return [], []
    now = datetime.now(timezone.utc)
    with get_db_session() as session:
        running = session.query(FixExecution.id, FixExecution.started_at).filter(FixExecution.status == "running").all()
    closed, timers = [], []
    for execution_id, started in running:
        if started is None:
            age = float(limit + ORPHAN_MARGIN_SECONDS)
        else:
            started = as_utc(started)   # SQLite: naive UTC
            age = (now - started).total_seconds()
        left = limit + ORPHAN_MARGIN_SECONDS - age
        if left <= 0:
            if close_ticket(execution_id, "failed", ORPHANED):
                closed.append(execution_id)
            continue
        timer = threading.Timer(left, close_ticket, args=(execution_id, "failed", ORPHANED))
        timer.daemon = True
        timer.start()
        timers.append(timer)
    return closed, timers


def check_commands_of(execution_id: int) -> frozenset:
    """The declared check commands of the plan this record runs (change_steps.check_commands) — empty when there
    is no such record or plan. They are part of the approved content, so they do not change during the run."""
    from agenticops.models import FixExecution, FixPlan, get_db_session
    from agenticops.services.change_steps import check_commands
    with get_db_session() as session:
        row = (session.query(FixPlan.pre_checks, FixPlan.post_checks)
               .join(FixExecution, FixExecution.fix_plan_id == FixPlan.id)
               .filter(FixExecution.id == execution_id).first())
    return check_commands(row[0], row[1]) if row else frozenset()


def ticket_state(execution_id: int) -> Optional[dict]:
    """What the run's record says now — None when there is no such record:
    {"status", "fix_plan_id", "stopped_by": the actor who asked it to stop or None,
     "rollback": the plan's rollback commands (only read once a stop was asked: what may still run)}."""
    from agenticops.models import FixExecution, FixPlan, get_db_session
    with get_db_session() as session:
        row = (session.query(FixExecution.status, FixExecution.fix_plan_id, FixExecution.stop_requested_at,
                             FixExecution.stop_requested_by)
               .filter(FixExecution.id == execution_id).first())
        if not row:
            return None
        stopped_by, rollback = None, frozenset()
        if row[2] is not None:
            from agenticops.services.change_steps import rollback_commands
            stopped_by = row[3] or "a person"
            rollback = rollback_commands(session.query(FixPlan.rollback_plan).filter_by(id=row[1]).scalar())
    return {"status": row[0], "fix_plan_id": row[1], "stopped_by": stopped_by, "rollback": rollback}
