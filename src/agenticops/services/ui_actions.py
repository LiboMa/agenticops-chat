"""What the actor can do to a plan or a change, and what it sets off (MVP-2.7.0 S3).

Side-effect free: permissions come from RbacPolicy.decide(), never authz.check() — check() audits every denial
(authz.denied[_shadow]) and would fill audit_logs and the /api/plans/stats denial counts on every page view.
`allowed` is what the route will actually do: in shadow mode (rbac_enforce=false) a decide() denial that no
`enforce: always` rule backs still goes through, reported as reason_code="policy_shadow". Who is EXPECTED to act
(the attention list) uses strictly_allowed(). The routes stay the source of truth; tests/test_ui_actions_parity.py
runs both and compares.
"""
from __future__ import annotations

from typing import Any, Optional

from agenticops.config import settings


def _policy():
    from agenticops.auth.authz import get_rbac_policy
    return get_rbac_policy()


def route_allows(actor, permission: str, subject: Any) -> tuple[bool, Optional[str]]:
    allowed, _reason, _rule, always = _policy().decide(actor, permission, subject)
    if allowed:
        return True, None
    if not settings.rbac_enforce and not always:
        return True, "policy_shadow"
    return False, "forbidden"


def strictly_allowed(actor, permission: str, subject: Any) -> bool:
    return _policy().decide(actor, permission, subject)[0]


def is_admin(actor) -> bool:
    return "admin" in _policy().effective_permissions(actor)


def fix_approve_effect() -> str:
    """pipeline_service.trigger_auto_execute starts the run iff auto_fix_enabled and executor_enabled."""
    return "approve_and_queue_execution" if settings.auto_fix_enabled and settings.executor_enabled else "approve_only"


def change_approve_effect(actor, cr: Any) -> str:
    """change_service.approve_and_execute queues the run iff the executor is on and the approver may execute it."""
    queues = settings.executor_enabled and route_allows(actor, "change.execute", cr)[0]
    return "approve_and_queue_execution" if queues else "approve_only"


def _action(name: str, allowed: bool, reason_code: Optional[str], effect: str) -> dict:
    return {"action": name, "allowed": allowed, "reason_code": reason_code, "effect": effect}


def _execute(actor, permission: str, subject: Any, blocked: Optional[str]) -> dict:
    """The execute routes' order: executor off → authz → anything still in the way (`blocked`)."""
    if not settings.executor_enabled:
        return _action("execute", False, "executor_disabled", "queue_execution")
    ok, code = route_allows(actor, permission, subject)
    if ok and blocked:
        ok, code = False, blocked
    return _action("execute", ok, code, "queue_execution")


def plan_actions(plan: Any, actor, *, issue_status: Optional[str], run_in_flight: bool) -> list[dict]:
    """A fix plan's actions (PUT /approve, POST /reject, POST /execute). A change plan's belong to its change."""
    if getattr(plan, "plan_kind", "fix") != "fix":
        return []
    out = []
    if plan.status in ("draft", "pending_approval"):
        ok, code = route_allows(actor, "plan.approve", plan)
        if ok and issue_status in ("resolved", "dismissed"):
            ok, code = False, "issue_closed"
        out.append(_action("approve", ok, code, fix_approve_effect()))
    if plan.status in ("draft", "pending_approval", "approved"):
        ok, code = route_allows(actor, "plan.reject", plan)
        out.append(_action("reject", ok, code, "update"))
    if plan.status == "approved":
        out.append(_execute(actor, "plan.execute", plan, "run_in_flight" if run_in_flight else None))
    return out


def change_actions(cr: Any, actor, *, plan: Any) -> list[dict]:
    """A change request's decisions (POST /api/changes/{id}/approve|reject|execute); `plan` = its active plan."""
    if not settings.change_management_enabled:
        return []
    out = []
    if cr.status == "planned" and plan is not None:
        ok, code = route_allows(actor, "change.approve", cr)
        out.append(_action("approve", ok, code, change_approve_effect(actor, cr)))
    if cr.status == "planned":
        ok, code = route_allows(actor, "change.reject", cr)
        out.append(_action("reject", ok, code, "update"))
    if cr.status == "approved":
        out.append(_execute(actor, "change.execute", cr,
                            None if plan is not None and plan.status == "approved" else "state"))
    return out
