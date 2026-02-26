"""Background Executor Service — polls for pending FixExecutions and dispatches to executor_agent.

Runs as a daemon thread alongside the FastAPI app. Follows the same pattern as
ChatSessionManager (daemon thread + periodic polling).
"""

import logging
import threading
import time
from datetime import datetime

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
        executor agent thread. The agent will check status on next tool call.
        """
        from agenticops.models import FixExecution, get_db_session

        with get_db_session() as session:
            execution = session.query(FixExecution).filter_by(id=execution_id).first()
            if not execution or execution.status != "running":
                return False
            execution.status = "aborted"
            execution.completed_at = datetime.utcnow()
            execution.error_message = "Cancelled by operator"
            session.commit()
            logger.info("Execution #%d marked as aborted (cancellation requested)", execution_id)

        with self._lock:
            self._active_executions.pop(execution_id, None)
        return True

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
                .values(status="running", started_at=datetime.utcnow())
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
        """Invoke executor_agent for a specific fix plan."""
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
        finally:
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

    def _mark_crashed(self, execution_id: int, fix_plan_id: int, error: str):
        """Mark a crashed execution in the DB."""
        from agenticops.models import FixExecution, FixPlan, get_db_session

        with get_db_session() as session:
            execution = session.query(FixExecution).filter_by(id=execution_id).first()
            if execution and execution.status == "running":
                execution.status = "failed"
                execution.completed_at = datetime.utcnow()
                execution.error_message = f"Agent crashed: {error[:500]}"
                plan = session.query(FixPlan).filter_by(id=fix_plan_id).first()
                if plan:
                    plan.status = "failed"
                session.commit()

    def _mark_timed_out(self, execution_id: int):
        """Mark a timed-out execution in the DB."""
        from agenticops.models import FixExecution, get_db_session

        with get_db_session() as session:
            execution = session.query(FixExecution).filter_by(id=execution_id).first()
            if execution and execution.status == "running":
                execution.status = "failed"
                execution.completed_at = datetime.utcnow()
                execution.error_message = (
                    f"Execution timed out after {settings.executor_total_timeout}s"
                )
                session.commit()
