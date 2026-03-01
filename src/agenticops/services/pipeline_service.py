"""Auto-fix pipeline service — chains RCA → SRE → Approve → Execute.

After RCA completes, the pipeline automatically:
1. Triggers the SRE agent to generate a fix plan
2. Auto-approves L0/L1 plans (synchronous DB update)
3. Triggers the Executor agent to execute the approved plan

Each stage is independently gated:
- auto_fix_enabled: Master switch for the entire post-RCA pipeline
- executor_auto_approve_l0_l1: Gates L0/L1 auto-approval
- executor_enabled: Gates fix execution

Non-blocking: Agent stages (SRE, Executor) run in daemon threads.
Follows the same pattern as rca_service.py.
"""

import logging
import threading
from datetime import datetime

from agenticops.config import settings

logger = logging.getLogger(__name__)


# ── Stage 1: Auto-SRE (after RCA completes) ──────────────────────────


def trigger_auto_sre(health_issue_id: int) -> None:
    """Fire-and-forget: spawn SRE agent to generate a fix plan after RCA.

    Called from save_rca_result() when an RCA result is persisted.
    Safe to call from any context (agent tool, API handler, etc.).
    """
    if not settings.auto_fix_enabled:
        logger.info("Auto-fix pipeline disabled — skipping SRE for issue #%d", health_issue_id)
        return

    thread = threading.Thread(
        target=_run_auto_sre,
        args=(health_issue_id,),
        daemon=True,
        name=f"auto-sre-{health_issue_id}",
    )
    thread.start()
    logger.info("Auto-SRE spawned for HealthIssue #%d", health_issue_id)


def _run_auto_sre(health_issue_id: int) -> None:
    """Run sre_agent for the given issue to generate a fix plan."""
    try:
        from agenticops.agents.sre_agent import sre_agent

        logger.info("Auto-SRE starting for HealthIssue #%d", health_issue_id)
        result = sre_agent(issue_id=health_issue_id)
        logger.info(
            "Auto-SRE completed for #%d: %s", health_issue_id, str(result)[:200]
        )
    except Exception:
        logger.exception("Auto-SRE failed for HealthIssue #%d", health_issue_id)


# ── Stage 2: Auto-Approve (after fix plan saved) ─────────────────────


def trigger_auto_approve(fix_plan_id: int) -> None:
    """Auto-approve L0/L1 fix plans. Synchronous — no agent needed.

    Called from save_fix_plan() when a new plan is persisted.
    L2/L3 plans are skipped (require human approval).
    On success, chains to trigger_auto_execute().
    """
    if not settings.auto_fix_enabled:
        logger.info("Auto-fix pipeline disabled — skipping approve for plan #%d", fix_plan_id)
        return

    if not settings.executor_auto_approve_l0_l1:
        logger.info("Auto-approve disabled — skipping for plan #%d", fix_plan_id)
        return

    try:
        from agenticops.models import FixPlan, HealthIssue, get_db_session

        with get_db_session() as session:
            plan = session.query(FixPlan).filter_by(id=fix_plan_id).first()
            if not plan:
                logger.warning("Auto-approve: FixPlan #%d not found", fix_plan_id)
                return

            if plan.status != "draft":
                logger.debug(
                    "Auto-approve: FixPlan #%d status is '%s', not 'draft' — skipping",
                    fix_plan_id, plan.status,
                )
                return

            if plan.risk_level not in ("L0", "L1"):
                logger.info(
                    "Auto-approve: FixPlan #%d is %s — L2/L3 require human approval",
                    fix_plan_id, plan.risk_level,
                )
                return

            # Approve L0/L1 plan
            plan.status = "approved"
            plan.approved_by = "agent:auto-pipeline"
            plan.approved_at = datetime.utcnow()

            # Capture values before session closes
            risk_level = plan.risk_level
            health_issue_id = plan.health_issue_id

            # Update HealthIssue status
            issue = session.query(HealthIssue).filter_by(id=health_issue_id).first()
            if issue:
                issue.status = "fix_approved"

            # get_db_session auto-commits on exit

        logger.info(
            "Auto-approved FixPlan #%d (%s) for HealthIssue #%d",
            fix_plan_id, risk_level, health_issue_id,
        )

        # Chain: trigger execution
        trigger_auto_execute(fix_plan_id)

    except Exception:
        logger.exception("Auto-approve failed for FixPlan #%d", fix_plan_id)


# ── Stage 3: Auto-Execute (after plan approved) ──────────────────────


def trigger_auto_execute(fix_plan_id: int) -> None:
    """Fire-and-forget: spawn executor agent to run an approved fix plan.

    Called from trigger_auto_approve() (L0/L1 auto path) or from
    approve_fix_plan() (manual/human approval path).
    """
    if not settings.auto_fix_enabled:
        logger.info("Auto-fix pipeline disabled — skipping execute for plan #%d", fix_plan_id)
        return

    if not settings.executor_enabled:
        logger.info("Executor disabled — skipping auto-execute for plan #%d", fix_plan_id)
        return

    thread = threading.Thread(
        target=_run_auto_execute,
        args=(fix_plan_id,),
        daemon=True,
        name=f"auto-execute-{fix_plan_id}",
    )
    thread.start()
    logger.info("Auto-execute spawned for FixPlan #%d", fix_plan_id)


def _run_auto_execute(fix_plan_id: int) -> None:
    """Run executor_agent for the given fix plan."""
    try:
        from agenticops.agents.executor_agent import executor_agent

        logger.info("Auto-execute starting for FixPlan #%d", fix_plan_id)
        result = executor_agent(fix_plan_id=fix_plan_id)
        logger.info(
            "Auto-execute completed for #%d: %s", fix_plan_id, str(result)[:200]
        )
    except Exception:
        logger.exception("Auto-execute failed for FixPlan #%d", fix_plan_id)
