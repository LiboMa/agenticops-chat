"""Auto-RCA service — triggers RCA automatically when a new HealthIssue is created.

Non-blocking: RCA runs in a daemon thread so the caller returns immediately.
Controlled by settings.auto_rca_enabled (AIOPS_AUTO_RCA_ENABLED).
"""

import logging
import threading
from typing import Optional

from agenticops.config import settings

logger = logging.getLogger(__name__)


def trigger_auto_rca(health_issue_id: int, trace_id: Optional[str] = None) -> None:
    """Fire-and-forget: spawn a daemon thread to run RCA on a newly created issue.

    Safe to call from any context (metadata tool, API handler, etc.).
    """
    if not settings.auto_rca_enabled:
        logger.info("Auto-RCA disabled — skipping for issue #%d", health_issue_id)
        return

    # Skip dismissed issues
    try:
        from agenticops.database import get_db_session
        from agenticops.models import HealthIssue
        with get_db_session() as session:
            issue = session.query(HealthIssue).filter_by(id=health_issue_id).first()
            if issue and issue.status == "dismissed":
                logger.info("Issue #%d is dismissed — skipping auto-RCA", health_issue_id)
                return
    except Exception:
        pass  # If check fails, proceed with RCA anyway

    thread = threading.Thread(
        target=_run_auto_rca,
        args=(health_issue_id, trace_id),
        daemon=True,
        name=f"auto-rca-{health_issue_id}",
    )
    thread.start()
    logger.info("Auto-RCA spawned for HealthIssue #%d", health_issue_id)


def _run_auto_rca(health_issue_id: int, trace_id: Optional[str] = None) -> None:
    """Run rca_agent for the given issue, with a wall-clock watchdog.

    Threads can't be force-killed, so on timeout we log rca failed + flag
    needs_review; the abandoned run can still finish but is observable as
    timed-out rather than silently stuck in 'investigating'.
    """
    from agenticops.services.pipeline_events import log_event

    # Restore trace_id in ContextVar as fallback (ThreadingInstrumentor may already propagate)
    if trace_id:
        from agenticops.config import set_trace_id, get_trace_id
        if not get_trace_id():
            set_trace_id(trace_id)

    from agenticops.config import get_agent_model_config
    rca_model_id, _ = get_agent_model_config("rca")
    log_event(health_issue_id, "rca_started", "rca", "started",
              detail={"model_id": rca_model_id}, trace_id=trace_id)
    try:
        from agenticops.agents.rca_agent import rca_agent

        logger.info("Auto-RCA starting for HealthIssue #%d", health_issue_id)

        timeout = settings.rca_timeout_seconds
        if timeout and timeout > 0:
            result_box: list = []
            error_box: list = []

            def _invoke():
                try:
                    result_box.append(rca_agent(issue_id=health_issue_id))
                except BaseException as e:  # propagate to the outer handler
                    error_box.append(e)

            worker = threading.Thread(target=_invoke, daemon=True,
                                      name=f"auto-rca-run-{health_issue_id}")
            worker.start()
            worker.join(timeout)
            if worker.is_alive():
                log_event(health_issue_id, "rca_completed", "rca", "failed",
                          detail={"reason": "timeout", "timeout_seconds": timeout},
                          trace_id=trace_id)
                _flag_needs_review(health_issue_id, f"RCA timed out after {timeout}s")
                logger.error("Auto-RCA TIMEOUT (%ds) for HealthIssue #%d", timeout, health_issue_id)
                return
            if error_box:
                raise error_box[0]
            result = result_box[0] if result_box else ""
        else:
            result = rca_agent(issue_id=health_issue_id)

        logger.info(
            "Auto-RCA completed for #%d: %s", health_issue_id, str(result)[:200]
        )
    except Exception:
        log_event(health_issue_id, "rca_completed", "rca", "failed", trace_id=trace_id)
        logger.exception("Auto-RCA failed for HealthIssue #%d", health_issue_id)


def _flag_needs_review(health_issue_id: int, reason: str) -> None:
    """Mark an issue as needing human review (metric_data flag, best-effort)."""
    try:
        from agenticops.models import HealthIssue, get_db_session

        with get_db_session() as session:
            issue = session.query(HealthIssue).filter_by(id=health_issue_id).first()
            if issue:
                md = dict(issue.metric_data) if isinstance(issue.metric_data, dict) else {}
                md["needs_review"] = True
                md["needs_review_reason"] = reason
                issue.metric_data = md
    except Exception:
        logger.debug("needs_review flag failed for #%d", health_issue_id, exc_info=True)
