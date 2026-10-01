"""Post-execution verification and human acceptance (MVP-2.6.1, spec §3.D.4) — one verdict for a fix and a
change execution.

evaluate() is pure: the execution's own outcome and results plus the plan's post_checks in, (verdict, reason)
out. The business status (HealthIssue / ChangeRequest), the execution status (fix_executions.status) and this
verdict (fix_executions.verification_status) are three separate facts; a `failed` verdict does not mean the
change was rolled back (fix_executions.rollback_results says that).

accept_execution() records a human's verdict on a `pending_acceptance` execution: a fix moves its HealthIssue
(fix_executed → resolved | root_cause_identified); a change goes through change_service.resolve_review, which
stays the only human writer of a change's terminal state and stamps the execution in the same transaction.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from agenticops.auth.actor import Actor

logger = logging.getLogger(__name__)

PASSED, FAILED, PENDING = "passed", "failed", "pending_acceptance"

_PASS = {"pass", "passed", "ok", "succeeded", "success", "true"}
_WARN = {"warn", "warning"}


class AcceptanceError(Exception):
    status_code = 409


class AcceptanceNotFound(AcceptanceError):
    status_code = 404


class AcceptanceForbidden(AcceptanceError):
    status_code = 403


class AcceptanceInvalid(AcceptanceError):
    status_code = 422


def _outcome(item) -> str:
    """pass | warning | fail | missing (a result that reports no status at all)."""
    status = item.get("status", item.get("result", item.get("passed"))) if isinstance(item, dict) else item
    if status is None:
        return "missing"
    value = str(status).strip().lower()
    return "pass" if value in _PASS else "warning" if value in _WARN else "fail"


def evaluate(execution_status: str, post_checks, post_check_results=None, step_results=None,
             error: str = "") -> tuple[str, str]:
    """The verdict on one execution: `passed` only when it succeeded and every post-check it declared passed.

    A run that did not succeed, or a post-check that failed, is `failed`. A succeeded run is otherwise
    `pending_acceptance` — no post-checks, missing or incomplete results, a warning, or a step that did not
    report success — and a human accepts or rejects it; a missing result is never a pass.
    """
    if execution_status != "succeeded":
        default = "execution rolled back" if execution_status == "rolled_back" else f"execution {execution_status}"
        return FAILED, error or default
    outcomes = [_outcome(r) for r in post_check_results or []]
    if "fail" in outcomes:
        return FAILED, f"post-check {outcomes.index('fail') + 1} failed"
    if not post_checks:
        return PENDING, "the plan has no post-checks"
    if len(outcomes) < len(post_checks) or "missing" in outcomes:
        return PENDING, "post-check results missing or incomplete"
    if "warning" in outcomes:
        return PENDING, f"post-check {outcomes.index('warning') + 1} reported a warning"
    steps = [_outcome(s) for s in step_results or []]
    unclear = next((i for i, o in enumerate(steps) if o != "pass"), None)
    if unclear is not None:
        return PENDING, f"step {unclear + 1} did not report success"
    return PASSED, "all post-checks passed"


def accept_execution(execution_id: int, *, actor: Actor, decision: str, reason: str) -> dict:
    """A human's verdict on an execution pending acceptance: `accepted` or `rejected`, with a reason.

    Identity is the caller's authenticated actor. Authorized as the approval of the plan's kind
    (plan.approve / change.approve), so webhook:* is refused even in shadow mode. Returns
    {"execution_id", "decision", "kind", "status"} — status is the issue's or the change request's.
    """
    from agenticops.auth import authz
    from agenticops.models import FixExecution, FixPlan, get_session

    if decision not in ("accepted", "rejected"):
        raise AcceptanceInvalid("decision must be accepted or rejected")
    reason = (reason or "").strip()[:2000]
    if not reason:
        raise AcceptanceInvalid("a reason is required")
    session = get_session()
    try:
        execution = session.get(FixExecution, execution_id)
        plan = session.get(FixPlan, execution.fix_plan_id) if execution is not None else None
        if plan is None:
            raise AcceptanceNotFound(f"Execution #{execution_id} not found")
        if execution.verification_status != PENDING:
            raise AcceptanceError(f"Execution #{execution_id} is not pending acceptance "
                                  f"(verification: {execution.verification_status or 'none'})")
        if plan.plan_kind == "change":
            cr_id = plan.change_request_id
        else:
            cr_id = None
            try:
                authz.check(actor, "plan.approve", subject=plan)
            except authz.AuthzDenied as e:
                raise AcceptanceForbidden(str(e)) from e
            status = _accept_fix(session, execution, plan, actor=actor, decision=decision, reason=reason)
    finally:
        session.close()
    if cr_id is not None:
        from agenticops.services import change_service as cs
        try:
            snap = cs.resolve_review(cr_id, actor=actor, outcome="completed" if decision == "accepted" else "failed",
                                     reason=reason)
        except cs.ChangeError as e:
            err = AcceptanceError(str(e))
            err.status_code = e.status_code
            raise err from e
        return {"execution_id": execution_id, "decision": decision, "kind": "change", "status": snap["status"]}
    return {"execution_id": execution_id, "decision": decision, "kind": "fix", "status": status}


def _accept_fix(session, execution, plan, *, actor: Actor, decision: str, reason: str) -> str:
    """Stamp the execution and move its issue from fix_executed, in one transaction; returns the issue status."""
    from agenticops.audit.service import Actions, AuditService, EntityTypes
    from agenticops.models import FixExecution, InvalidStatusTransition
    from agenticops.services.issue_state import transition_issue
    from agenticops.tools.metadata_tools import dispute_rca, log_rca_disputed

    issue_id = plan.health_issue_id
    target = "resolved" if decision == "accepted" else "root_cause_identified"
    stamped = (
        session.query(FixExecution)
        .filter(FixExecution.id == execution.id, FixExecution.verification_status == PENDING)
        .update({"verification_status": PASSED if decision == "accepted" else FAILED, "accepted_by": actor.key,
                 "accepted_at": datetime.now(timezone.utc), "acceptance_note": reason}, synchronize_session=False)
    )
    if stamped != 1:
        session.rollback()
        raise AcceptanceError(f"Execution #{execution.id} was accepted or rejected concurrently")
    try:
        transition_issue(session, issue_id, target, actor=actor.key, expected="fix_executed",
                         reason=f"Execution #{execution.id} {decision}: {reason}")
    except InvalidStatusTransition as e:  # the issue moved on since the run (resolved / dismissed / re-planned)
        session.rollback()
        raise AcceptanceError(f"HealthIssue #{issue_id} is no longer fix_executed: {e}") from e
    rca = dispute_rca(session, issue_id, execution.id, f"rejected at acceptance by {actor.key}: {reason}") \
        if decision == "rejected" else None
    action = Actions.EXECUTION_ACCEPTED if decision == "accepted" else Actions.EXECUTION_REJECTED
    AuditService.log(action, EntityTypes.FIX_PLAN, str(plan.id), actor=actor.key, user_id=actor.user_id,
                     details={"execution_id": execution.id, "health_issue_id": issue_id, "reason": reason},
                     old_values={"verification_status": PENDING, "issue_status": "fix_executed"},
                     new_values={"verification_status": PASSED if decision == "accepted" else FAILED,
                                 "issue_status": target}, session=session)
    session.commit()
    if rca is not None:
        log_rca_disputed(issue_id, rca.id, execution.id, reason)
    if decision == "accepted":
        try:
            from agenticops.services.resolution_service import trigger_post_resolution
            trigger_post_resolution(issue_id)
        except Exception as e:
            logger.warning("Failed to trigger post-resolution pipeline: %s", e)
    return target
