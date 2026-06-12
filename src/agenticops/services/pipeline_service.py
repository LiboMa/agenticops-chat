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
from datetime import datetime, timezone
from typing import Optional

from agenticops.config import settings

logger = logging.getLogger(__name__)


def _restore_trace_id(trace_id: Optional[str]) -> None:
    """Restore trace_id in ContextVar as fallback (ThreadingInstrumentor may already propagate)."""
    if trace_id:
        from agenticops.config import set_trace_id, get_trace_id
        if not get_trace_id():
            set_trace_id(trace_id)


# ── Stage 1: Auto-SRE (after RCA completes) ──────────────────────────


def trigger_auto_sre(health_issue_id: int, trace_id: Optional[str] = None) -> None:
    """Fire-and-forget: spawn SRE agent to generate a fix plan after RCA.

    Called from save_rca_result() when an RCA result is persisted.
    Safe to call from any context (agent tool, API handler, etc.).
    """
    if not settings.auto_fix_enabled:
        logger.info("Auto-fix pipeline disabled — skipping SRE for issue #%d", health_issue_id)
        return

    # Guard: skip if issue already has a non-terminal FixPlan
    try:
        from agenticops.models import FixPlan, FIXPLAN_TERMINAL_STATUSES, get_db_session
        with get_db_session() as session:
            active = (
                session.query(FixPlan)
                .filter_by(health_issue_id=health_issue_id)
                .filter(FixPlan.status.notin_(FIXPLAN_TERMINAL_STATUSES))
                .first()
            )
            if active:
                logger.info(
                    "Issue #%d already has active FixPlan #%d (%s) — skipping auto-SRE",
                    health_issue_id, active.id, active.status,
                )
                return
    except Exception:
        logger.debug("FixPlan guard check failed, proceeding with auto-SRE", exc_info=True)

    thread = threading.Thread(
        target=_run_auto_sre,
        args=(health_issue_id, trace_id),
        daemon=True,
        name=f"auto-sre-{health_issue_id}",
    )
    thread.start()
    logger.info("Auto-SRE spawned for HealthIssue #%d", health_issue_id)


def _run_auto_sre(health_issue_id: int, trace_id: Optional[str] = None) -> None:
    """Run sre_agent for the given issue to generate a fix plan."""
    _restore_trace_id(trace_id)
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


def trigger_auto_approve(fix_plan_id: int, trace_id: Optional[str] = None) -> None:
    """Policy-gated auto-approval for fix plans. Synchronous — no agent needed.

    Called from save_fix_plan() when a new plan is persisted.
    With policy_engine_enabled, config/policies.yaml decides (auto_approve /
    require_human / require_itsm_change / block / escalate); the decision and
    its matching rule are logged to the pipeline-event timeline as the audit
    record. Legacy behavior (hardcoded L0/L1) is preserved when disabled.
    On auto-approval, chains to trigger_auto_execute().
    """
    if not settings.auto_fix_enabled:
        logger.info("Auto-fix pipeline disabled — skipping approve for plan #%d", fix_plan_id)
        return

    if not settings.executor_auto_approve_l0_l1:
        logger.info("Auto-approve disabled — skipping for plan #%d", fix_plan_id)
        return

    try:
        from agenticops.models import FixPlan, HealthIssue, get_db_session

        decision = None
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

            if settings.policy_engine_enabled:
                decision = _evaluate_policy_for_plan(session, plan)
                if decision.action != "auto_approve":
                    _log_policy_decision(plan, decision, trace_id)
                    logger.info(
                        "Policy '%s' → %s for FixPlan #%d (%s) — not auto-approving",
                        decision.rule_name, decision.action, fix_plan_id, plan.risk_level,
                    )
                    return
            elif plan.risk_level not in ("L0", "L1"):
                logger.info(
                    "Auto-approve: FixPlan #%d is %s — L2/L3 require human approval",
                    fix_plan_id, plan.risk_level,
                )
                return

            # Approve plan (policy auto_approve, or legacy L0/L1)
            plan.status = "approved"
            plan.approved_by = "agent:auto-pipeline"
            plan.approved_at = datetime.now(timezone.utc)

            # Capture values before session closes
            risk_level = plan.risk_level
            health_issue_id = plan.health_issue_id

            # Resolve trace_id from param or HealthIssue
            resolved_tid = trace_id
            if not resolved_tid:
                issue = session.query(HealthIssue).filter_by(id=health_issue_id).first()
                if issue:
                    resolved_tid = issue.trace_id

            # Update HealthIssue status
            issue = session.query(HealthIssue).filter_by(id=health_issue_id).first()
            if issue:
                issue.status = "fix_approved"

            # get_db_session auto-commits on exit

        logger.info(
            "Auto-approved FixPlan #%d (%s) for HealthIssue #%d",
            fix_plan_id, risk_level, health_issue_id,
        )

        try:
            from agenticops.services.pipeline_events import log_event
            detail = {"plan_id": fix_plan_id, "approved_by": "agent:auto-pipeline", "risk_level": risk_level}
            if decision is not None:
                detail["policy_decision"] = decision.to_dict()
            log_event(health_issue_id, "fix_approved", "approval",
                      detail=detail,
                      actor="agent:auto-pipeline", trace_id=resolved_tid)
        except Exception:
            pass

        # Chain: trigger execution
        trigger_auto_execute(fix_plan_id, trace_id=resolved_tid)

    except Exception:
        logger.exception("Auto-approve failed for FixPlan #%d", fix_plan_id)


def _evaluate_policy_for_plan(session, plan):
    """Build policy-engine inputs from the plan's issue context and evaluate.

    Runs an account-scoped blast-radius estimate AND a pre-execution impact
    simulation (graph engine, zero AWS calls) so policies can gate on what
    the fix would break, not just how risky the change class is. Both are
    fail-soft: no graph data → None → simulation rules simply don't match.
    """
    from agenticops.models import CloudAccount, HealthIssue
    from agenticops.services.policy_engine import (
        estimate_blast_radius,
        get_policy_engine,
        simulate_fix_impact,
    )

    severity = provider = resource_id = native_account_id = None
    issue = session.query(HealthIssue).filter_by(id=plan.health_issue_id).first()
    if issue:
        severity = issue.severity
        provider = issue.provider
        resource_id = issue.resource_id
        # Graph nodes are keyed by the cloud-native account number, not our FK
        if issue.account_id:
            account = session.query(CloudAccount).filter_by(id=issue.account_id).first()
            if account:
                native_account_id = (account.credentials or {}).get("account_id") or None

    impact = simulate_fix_impact(resource_id, native_account_id)
    decision = get_policy_engine().evaluate(
        risk_level=plan.risk_level,
        severity=severity,
        provider=provider,
        resource_id=resource_id,
        blast_radius=estimate_blast_radius(resource_id, native_account_id),
        impact_severity=impact["severity"] if impact else None,
    )
    if impact:
        decision.reasons.append(
            f"pre-execution simulation: {impact['affected_nodes']} nodes affected, "
            f"{impact['isolated_subnets']} subnets isolated, severity={impact['severity']}"
        )
    return decision


def _log_policy_decision(plan, decision, trace_id: Optional[str]) -> None:
    """Record a non-approving policy decision on the issue timeline (audit trail)."""
    try:
        from agenticops.services.pipeline_events import log_event
        log_event(
            plan.health_issue_id,
            "policy_decision",
            "approval",
            status=decision.action,
            detail={"plan_id": plan.id, "risk_level": plan.risk_level,
                    "policy_decision": decision.to_dict()},
            actor="policy-engine",
            trace_id=trace_id,
        )
    except Exception:
        pass


# ── Stage 3: Auto-Execute (after plan approved) ──────────────────────


def trigger_auto_execute(fix_plan_id: int, trace_id: Optional[str] = None) -> None:
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
        args=(fix_plan_id, trace_id),
        daemon=True,
        name=f"auto-execute-{fix_plan_id}",
    )
    thread.start()
    logger.info("Auto-execute spawned for FixPlan #%d", fix_plan_id)


def _run_auto_execute(fix_plan_id: int, trace_id: Optional[str] = None) -> None:
    """Run executor_agent for the given fix plan."""
    _restore_trace_id(trace_id)

    # Look up health_issue_id for event logging
    _issue_id = None
    try:
        from agenticops.models import FixPlan, get_db_session
        with get_db_session() as session:
            plan = session.query(FixPlan).filter_by(id=fix_plan_id).first()
            if plan:
                _issue_id = plan.health_issue_id
    except Exception:
        pass

    if _issue_id:
        from agenticops.services.pipeline_events import log_event
        log_event(_issue_id, "execution_started", "execution", "started",
                  detail={"plan_id": fix_plan_id, "executor": "agent:executor"},
                  trace_id=trace_id)

    try:
        from agenticops.agents.executor_agent import executor_agent

        logger.info("Auto-execute starting for FixPlan #%d", fix_plan_id)
        result = executor_agent(fix_plan_id=fix_plan_id)
        logger.info(
            "Auto-execute completed for #%d: %s", fix_plan_id, str(result)[:200]
        )
    except Exception:
        if _issue_id:
            from agenticops.services.pipeline_events import log_event
            log_event(_issue_id, "execution_completed", "execution", "failed",
                      detail={"plan_id": fix_plan_id}, trace_id=trace_id)
        logger.exception("Auto-execute failed for FixPlan #%d", fix_plan_id)
    finally:
        # Safety net: flush any consolidated notifications for this issue
        if _issue_id:
            try:
                from agenticops.services.notification_service import flush_consolidated
                flush_consolidated(_issue_id)
            except Exception:
                pass
