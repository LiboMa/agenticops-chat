"""Auto-RCA service — triggers RCA automatically when a new HealthIssue is created.

Non-blocking: RCA runs in a daemon thread so the caller returns immediately.
Controlled by settings.auto_rca_enabled (AIOPS_AUTO_RCA_ENABLED).
"""

import logging
import threading

from agenticops.config import settings

logger = logging.getLogger(__name__)


def trigger_auto_rca(health_issue_id: int) -> None:
    """Fire-and-forget: spawn a daemon thread to run RCA on a newly created issue.

    Safe to call from any context (metadata tool, API handler, etc.).
    """
    if not settings.auto_rca_enabled:
        logger.info("Auto-RCA disabled — skipping for issue #%d", health_issue_id)
        return

    thread = threading.Thread(
        target=_run_auto_rca,
        args=(health_issue_id,),
        daemon=True,
        name=f"auto-rca-{health_issue_id}",
    )
    thread.start()
    logger.info("Auto-RCA spawned for HealthIssue #%d", health_issue_id)


def _run_auto_rca(health_issue_id: int) -> None:
    """Run rca_agent for the given issue."""
    try:
        from agenticops.agents.rca_agent import rca_agent

        logger.info("Auto-RCA starting for HealthIssue #%d", health_issue_id)
        result = rca_agent(issue_id=health_issue_id)
        logger.info(
            "Auto-RCA completed for #%d: %s", health_issue_id, str(result)[:200]
        )
    except Exception:
        logger.exception("Auto-RCA failed for HealthIssue #%d", health_issue_id)
