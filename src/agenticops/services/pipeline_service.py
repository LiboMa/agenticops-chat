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

import json
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
    """Run sre_agent for the given issue to generate a fix plan (daemon thread — sets its own Run Context)."""
    _restore_trace_id(trace_id)
    from agenticops.config import get_trace_id
    from agenticops.run_context import RunContext, reset_run_context, set_run_context
    _rc_token = set_run_context(RunContext(actor="agent:auto-pipeline", trace_id=get_trace_id(), agent_name="sre"))
    try:
        from agenticops.agents.sre_agent import sre_agent

        logger.info("Auto-SRE starting for HealthIssue #%d", health_issue_id)
        result = sre_agent(issue_id=health_issue_id)
        logger.info(
            "Auto-SRE completed for #%d: %s", health_issue_id, str(result)[:200]
        )
    except Exception:
        logger.exception("Auto-SRE failed for HealthIssue #%d", health_issue_id)
    finally:
        reset_run_context(_rc_token)


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

            from agenticops.services.issue_state import closed_issue_refusal
            closed = closed_issue_refusal(session, plan.health_issue_id)
            if closed:
                logger.info("Auto-approve: FixPlan #%d skipped — %s", fix_plan_id, closed)
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

            # Trust-Kernel ceiling (M-5): the always-enforced agent rule (no-agent-approval-above-l1) holds
            # regardless of policies.yaml — a rule granting auto_approve to L2/L3 cannot make
            # agent:auto-pipeline approve them. The check writes its own authz.denied audit row.
            from agenticops.auth import authz
            from agenticops.auth.actor import agent_actor
            try:
                authz.check(agent_actor("auto-pipeline"), "plan.approve", subject=plan)
            except authz.AuthzDenied as e:
                logger.info("Auto-approve: FixPlan #%d (%s) left as is — %s", fix_plan_id, plan.risk_level, e.reason)
                return

            # Approve plan (policy auto_approve, or legacy L0/L1)
            from agenticops.models import transition_plan
            transition_plan(plan, "approved")
            plan.approved_by = "agent:auto-pipeline"
            plan.approved_at = datetime.now(timezone.utc)
            from agenticops.services.plan_content import stamp_approval
            stamp_approval(session, plan)

            # Audit row in the SAME transaction as the status change (decision + state together)
            from agenticops.audit.service import Actions, AuditService, EntityTypes
            AuditService.log(
                Actions.PLAN_APPROVED, EntityTypes.FIX_PLAN, str(plan.id), actor="agent:auto-pipeline",
                details={"risk_level": plan.risk_level, "plan_kind": plan.plan_kind,
                         "policy_rule": decision.rule_name if decision else "legacy-l0-l1",
                         "policy_action": decision.action if decision else "auto_approve"},
                old_values={"status": "draft"}, new_values={"status": "approved"}, session=session,
            )

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
            from agenticops.services.issue_state import advance_issue
            if health_issue_id:
                advance_issue(session, health_issue_id, "fix_approved", actor="agent:auto-pipeline",
                              reason=f"FixPlan #{fix_plan_id} auto-approved")

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

    Runs an account-scoped blast-radius estimate (the published relationship
    graph's potential impact of the issue's anchor; shadow mode by default,
    see policy_blast_radius) AND a pre-execution impact simulation (graph
    engine, zero AWS calls) so policies can gate on what the fix would break,
    not just how risky the change class is. Both are fail-soft: no graph
    data → None → those rules simply don't match.
    """
    from agenticops.models import CloudAccount, HealthIssue
    from agenticops.services.policy_engine import (
        get_policy_engine,
        policy_blast_radius,
        simulate_fix_impact,
    )

    severity = provider = resource_id = native_account_id = None
    blast_radius = shadow_blast_radius = None
    issue = session.query(HealthIssue).filter_by(id=plan.health_issue_id).first()
    if issue:
        severity = issue.severity
        provider = issue.provider
        resource_id = issue.resource_id
        # Own session: a failed graph read must not poison the caller's transaction (PostgreSQL aborts it);
        # shadow mode stays zero-impact.
        blast_radius, shadow_blast_radius = policy_blast_radius([issue.resource_ref], issue.account_id)
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
        blast_radius=blast_radius,
        impact_severity=impact["severity"] if impact else None,
    )
    decision.shadow_blast_radius = shadow_blast_radius
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


def runs_in_flight(session, plans) -> set[int]:
    """The ids of these fix plans whose approval auto-run is under way — one events query for all of them
    (2026-10-05 final review C1 rule, ported to services/work_phases.in_flight_auto_run)."""
    from agenticops.models import PipelineEvent
    from agenticops.services.work_phases import in_flight_auto_run
    by_issue: dict[int, list[int]] = {}
    for p in plans:
        if p.health_issue_id:
            by_issue.setdefault(p.health_issue_id, []).append(p.id)
    if not by_issue:
        return set()
    events = (session.query(PipelineEvent)
              .filter(PipelineEvent.health_issue_id.in_(list(by_issue)),
                      PipelineEvent.event_type.in_(("execution_started", "execution_completed")))
              .all())
    grouped: dict[int, list] = {}
    for e in events:
        grouped.setdefault(e.health_issue_id, []).append(e)
    now = datetime.now(timezone.utc)
    return {pid for iid, pids in by_issue.items() for pid in pids
            if in_flight_auto_run(grouped.get(iid, []), pid, timeout_seconds=settings.executor_total_timeout,
                                  now=now) is not None}


def plan_run_in_flight(session, plan_id: int) -> bool:
    """Whether an auto-run of this fix plan is in progress (2026-10-05 final review C1).

    _run_auto_execute writes no FixExecution row until the run ends, so the plan stays 'approved' throughout;
    its timeline events are the signal (services/work_phases.in_flight_auto_run — the page's own rule)."""
    from agenticops.models import FixPlan
    plan = session.get(FixPlan, plan_id)
    return plan is not None and bool(plan.health_issue_id) and plan_id in runs_in_flight(session, [plan])


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

    # Daemon thread — sets its own Run Context; fix_plan_id is what lets
    # approved_plan_in_context() admit change_required commands for this plan.
    # Set immediately before the try so the finally's reset always pairs with it.
    from agenticops.config import get_trace_id
    from agenticops.run_context import RunContext, reset_run_context, set_run_context
    _rc_token = set_run_context(RunContext(actor="agent:auto-pipeline", trace_id=trace_id or get_trace_id(),
                                           agent_name="executor", fix_plan_id=fix_plan_id))
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
        reset_run_context(_rc_token)
        # Safety net: flush any consolidated notifications for this issue
        if _issue_id:
            try:
                from agenticops.services.notification_service import flush_consolidated
                flush_consolidated(_issue_id)
            except Exception:
                pass
