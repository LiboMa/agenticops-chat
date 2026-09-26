"""Background Executor Service — polls for pending FixExecutions and dispatches to executor_agent.

Runs as a daemon thread alongside the FastAPI app. Follows the same pattern as
ChatSessionManager (daemon thread + periodic polling).
"""

import logging
import threading
import time
from datetime import datetime, timezone

from agenticops.config import settings

logger = logging.getLogger(__name__)


class ExecutorService:
    """Background service that picks up pending FixExecutions and runs the executor agent.

    Lifecycle:
    1. Polls DB every `poll_interval` seconds for FixExecution with status="pending"
    2. Claims the oldest pending execution atomically (set status="running")
    3. Dispatches to executor_agent in a worker thread
    4. Executor agent handles the full 7-step protocol and records results
    5. On timeout, marks execution as failed
    """

    def __init__(self, poll_interval: int = 30):
        self._poll_interval = poll_interval
        self._thread: threading.Thread | None = None
        self._shutdown = False
        self._active_executions: dict[int, threading.Thread] = {}
        self._lock = threading.Lock()

    def start(self):
        """Start the background polling loop."""
        if not settings.executor_enabled:
            logger.info("Executor service not started (AIOPS_EXECUTOR_ENABLED=false)")
            return

        if self._thread is not None:
            return

        self._shutdown = False
        self._thread = threading.Thread(target=self._poll_loop, daemon=True, name="executor-service")
        self._thread.start()
        logger.info("Executor service started (poll interval=%ds)", self._poll_interval)

    def stop(self):
        """Signal the polling loop to stop."""
        self._shutdown = True
        if self._thread:
            self._thread.join(timeout=10)
            self._thread = None
        logger.info("Executor service stopped")

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def active_count(self) -> int:
        with self._lock:
            return len(self._active_executions)

    def cancel_execution(self, execution_id: int) -> bool:
        """Request cancellation of a running execution.

        Note: This sets the DB status to 'aborted' but cannot forcibly kill the
        executor agent thread. The plan (if executing) → failed and, for a change
        plan, the change request → failed via on_execution_result("aborted"); the
        still-running agent's later writes and change_required commands are refused
        because its plan is no longer approved/executing. False when the ticket is
        missing or no longer running (see _close_ticket).
        """
        ok = self._close_ticket(execution_id, "aborted", "Cancelled by operator")
        if ok:
            logger.info("Execution #%d marked as aborted (cancellation requested)", execution_id)
            with self._lock:
                self._active_executions.pop(execution_id, None)
        return ok

    def _poll_loop(self):
        """Main polling loop — runs in daemon thread."""
        while not self._shutdown:
            try:
                self._check_for_pending()
            except Exception:
                logger.exception("Error in executor poll loop")
            time.sleep(self._poll_interval)

    def _check_for_pending(self):
        """Find and claim the oldest pending FixExecution atomically.

        Uses UPDATE ... WHERE status='pending' to prevent race conditions
        when multiple executor instances run concurrently.
        """
        from sqlalchemy import update
        from agenticops.models import FixExecution, get_db_session

        with get_db_session() as session:
            # Find candidate
            pending = (
                session.query(FixExecution)
                .filter_by(status="pending")
                .order_by(FixExecution.created_at.asc())
                .first()
            )
            if not pending:
                return

            # Atomic claim: UPDATE ... WHERE id=X AND status='pending'
            # If another thread already claimed it, rowcount will be 0
            result = session.execute(
                update(FixExecution)
                .where(FixExecution.id == pending.id, FixExecution.status == "pending")
                .values(status="running", started_at=datetime.now(timezone.utc))
            )
            session.commit()

            if result.rowcount == 0:
                logger.debug("FixExecution #%d already claimed by another worker", pending.id)
                return

            execution_id = pending.id
            fix_plan_id = pending.fix_plan_id

        logger.info("Claimed FixExecution #%d for FixPlan #%d", execution_id, fix_plan_id)
        self._dispatch(execution_id, fix_plan_id)

    def _dispatch(self, execution_id: int, fix_plan_id: int):
        """Run executor_agent in a worker thread with timeout."""
        worker = threading.Thread(
            target=self._run_executor,
            args=(execution_id, fix_plan_id),
            daemon=True,
            name=f"executor-worker-{execution_id}",
        )
        with self._lock:
            self._active_executions[execution_id] = worker
        worker.start()

        # Timeout watchdog
        watchdog = threading.Thread(
            target=self._timeout_watchdog,
            args=(execution_id, worker),
            daemon=True,
            name=f"executor-watchdog-{execution_id}",
        )
        watchdog.start()

    def _run_executor(self, execution_id: int, fix_plan_id: int):
        """Invoke executor_agent for a specific fix plan (worker thread — sets its own Run Context).

        The context carries the plan (so ``approved_plan_in_context()`` lets change_required
        commands run), the queued ticket (``execution_id``, which save_execution_result closes in
        place), the approver as ``on_behalf_of`` and the issue's trace id. It is set even when the
        lookup fails, so audit rows are never attributed to ``system``. A run that returns without
        recording its result is reconciled: the still-running ticket, its plan and a change plan's
        request are failed (``_fail_execution``).
        """
        from agenticops.config import set_trace_id
        from agenticops.run_context import RunContext, reset_run_context, set_run_context
        approved_by = trace_id = None
        change_request_id = None
        bound_account_id = None  # a change plan binds this run to its CR's account; a fix plan / lookup-miss stays unbound
        try:
            from agenticops.models import FixPlan, HealthIssue, get_db_session
            with get_db_session() as db:
                plan = db.query(FixPlan).filter_by(id=fix_plan_id).first()
                if plan:
                    approved_by = plan.approved_by
                    change_request_id = plan.change_request_id
                    bound_account_id = plan.change_request.account_id if plan.change_request else None
                    if plan.health_issue_id:
                        trace_id = db.query(HealthIssue.trace_id).filter_by(id=plan.health_issue_id).scalar()
                    elif plan.change_request:
                        trace_id = plan.change_request.trace_id
        except Exception:
            logger.debug("executor run-context lookup failed for FixPlan #%d", fix_plan_id, exc_info=True)
        if trace_id:
            set_trace_id(trace_id)
        _rc_token = set_run_context(RunContext(actor="agent:executor", on_behalf_of=approved_by, trace_id=trace_id,
                                               agent_name="executor", fix_plan_id=fix_plan_id,
                                               change_request_id=change_request_id, execution_id=execution_id,
                                               bound_account_id=bound_account_id))
        try:
            from agenticops.agents.executor_agent import executor_agent

            logger.info("Starting executor agent for FixPlan #%d (Execution #%d)", fix_plan_id, execution_id)
            result = executor_agent(fix_plan_id=fix_plan_id)
            logger.info(
                "Executor agent completed for FixPlan #%d: %s",
                fix_plan_id,
                str(result)[:200],
            )
        except Exception as e:
            logger.exception("Executor agent crashed for FixPlan #%d", fix_plan_id)
            self._mark_crashed(execution_id, fix_plan_id, str(e))
        else:
            # A run that returned without recording its result (a refusal, a model error the agent
            # caught, the iteration cap) must not leave the ticket running and the plan/change executing.
            # A no-op when save_execution_result already closed the ticket.
            try:
                self._fail_execution(execution_id, f"Executor ended without recording a result: {str(result)[:300]}")
            except Exception:
                logger.warning("post-run reconcile failed for Execution #%d", execution_id, exc_info=True)
        finally:
            reset_run_context(_rc_token)  # self-contained: never leaves the plan context behind
            set_trace_id(None)  # symmetric with the IM sites: the worker's trace goes with it
            with self._lock:
                self._active_executions.pop(execution_id, None)

    def _timeout_watchdog(self, execution_id: int, worker: threading.Thread):
        """Wait for worker to finish or timeout."""
        worker.join(timeout=settings.executor_total_timeout)
        if worker.is_alive():
            logger.warning(
                "Execution #%d exceeded total timeout (%ds) — marking as failed",
                execution_id,
                settings.executor_total_timeout,
            )
            self._mark_timed_out(execution_id)
            with self._lock:
                self._active_executions.pop(execution_id, None)

    def _close_ticket(self, execution_id: int, ticket_status: str, message: str) -> bool:
        """Close a still-running ticket as ``ticket_status``; its executing plan → failed; for a change plan the
        change mapper gets ``ticket_status`` (its request → failed).

        The ticket is the arbiter between the three writers that close it — this one (a cancel, the watchdog, a
        crash, the post-run reconcile) and save_execution_result — so the first write is a compare-and-set,
        ``UPDATE … WHERE id=? AND status='running'`` (the _check_for_pending claim): only its winner goes on
        to the plan. False (and nothing written) when the ticket is missing or no longer running — it was
        already closed by one of the others. The plan is the TICKET's plan.
        """
        from sqlalchemy import update
        from agenticops.models import FixExecution, FixPlan, get_db_session, transition_plan
        from agenticops.security.redaction import redact_obj

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
            session.commit()
        # Change plan: feed the terminal to the change mapper after commit (a no-op unless its request is
        # executing). Best-effort: a post-commit side-effect must never crash the handler that closes the ticket.
        if is_change:
            try:
                from agenticops.services.change_service import on_execution_result
                on_execution_result(plan_id, ticket_status, error=message)
            except Exception:
                logger.warning("change on_execution_result failed for FixPlan #%s", plan_id, exc_info=True)
        return True

    def _fail_execution(self, execution_id: int, message: str) -> bool:
        """Close a still-running ticket as failed; its executing plan → failed; a change plan's request → failed.

        False (and nothing written) when the ticket is missing or no longer running — it was already closed
        by save_execution_result, a cancel, the watchdog or a crash. The plan is the TICKET's plan.
        """
        return self._close_ticket(execution_id, "failed", message)

    def _mark_crashed(self, execution_id: int, fix_plan_id: int, error: str):
        """Mark a crashed execution in the DB (fix_plan_id kept for the caller's signature; the ticket's plan is used)."""
        self._fail_execution(execution_id, f"Agent crashed: {error[:500]}")

    def _mark_timed_out(self, execution_id: int):
        """Mark a timed-out execution in the DB."""
        self._fail_execution(execution_id, f"Execution timed out after {settings.executor_total_timeout}s")
