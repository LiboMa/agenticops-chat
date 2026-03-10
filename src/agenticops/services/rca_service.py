"""Auto-RCA service — triggers RCA automatically when a new HealthIssue is created.

Non-blocking: RCA runs in a daemon thread so the caller returns immediately.
Controlled by settings.auto_rca_enabled (AIOPS_AUTO_RCA_ENABLED).
"""

import logging
import threading
from typing import Optional

from agenticops.config import settings

logger = logging.getLogger(__name__)


# Track in-flight RCA tasks to prevent duplicate runs for the same issue
_inflight_lock = threading.Lock()
_inflight: set[int] = set()


def trigger_auto_rca(health_issue_id: int, trace_id: Optional[str] = None) -> None:
    """Fire-and-forget: spawn a daemon thread to run RCA on a newly created issue.

    Safe to call from any context (metadata tool, API handler, etc.).
    Dedup: only one RCA runs per health_issue_id at a time.
    """
    if not settings.auto_rca_enabled:
        logger.info("Auto-RCA disabled — skipping for issue #%d", health_issue_id)
        return

    with _inflight_lock:
        if health_issue_id in _inflight:
            logger.info("Auto-RCA already in-flight for #%d — skipping duplicate", health_issue_id)
            return
        _inflight.add(health_issue_id)

    thread = threading.Thread(
        target=_run_auto_rca,
        args=(health_issue_id, trace_id),
        daemon=True,
        name=f"auto-rca-{health_issue_id}",
    )
    thread.start()
    logger.info("Auto-RCA spawned for HealthIssue #%d", health_issue_id)


def _run_auto_rca(health_issue_id: int, trace_id: Optional[str] = None) -> None:
    """Run rca_agent for the given issue."""
    from agenticops.services.pipeline_events import log_event

    # Restore trace_id in ContextVar as fallback (ThreadingInstrumentor may already propagate)
    if trace_id:
        from agenticops.config import set_trace_id, get_trace_id
        if not get_trace_id():
            set_trace_id(trace_id)

    log_event(health_issue_id, "rca_started", "rca", "started",
              detail={"model_id": settings.bedrock_model_id}, trace_id=trace_id)
    try:
        from agenticops.agents.rca_agent import rca_agent

        logger.info("Auto-RCA starting for HealthIssue #%d", health_issue_id)
        result = rca_agent(issue_id=health_issue_id)
        logger.info(
            "Auto-RCA completed for #%d: %s", health_issue_id, str(result)[:200]
        )
    except Exception:
        log_event(health_issue_id, "rca_completed", "rca", "failed", trace_id=trace_id)
        logger.exception("Auto-RCA failed for HealthIssue #%d", health_issue_id)
    finally:
        with _inflight_lock:
            _inflight.discard(health_issue_id)
