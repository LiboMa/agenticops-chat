"""services/ui_actions: what an actor can do to a plan / change and what it sets off — decide() only, so viewing
a page never writes an audit row (MVP-2.7.0 S3)."""
from types import SimpleNamespace
from unittest.mock import patch

from agenticops.auth.actor import Actor
from agenticops.config import settings
from agenticops.services import ui_actions as ua

WRITER = Actor("user", "alice", 1, ("read", "write"))
READER = Actor("user", "rita", 2, ("read",))


def _plan(status="pending_approval", risk="L1", kind="fix"):
    return SimpleNamespace(id=5, status=status, risk_level=risk, plan_kind=kind)


def _by(actions):
    return {a["action"]: a for a in actions}


def test_fix_approve_effect_follows_auto_fix_and_executor():
    with patch.object(settings, "auto_fix_enabled", True), patch.object(settings, "executor_enabled", True):
        assert ua.fix_approve_effect() == "approve_and_queue_execution"
    with patch.object(settings, "auto_fix_enabled", False), patch.object(settings, "executor_enabled", True):
        assert ua.fix_approve_effect() == "approve_only"
    with patch.object(settings, "auto_fix_enabled", True), patch.object(settings, "executor_enabled", False):
        assert ua.fix_approve_effect() == "approve_only"


def test_pending_plan_offers_approve_and_reject():
    acts = _by(ua.plan_actions(_plan(), WRITER, issue_status="fix_planned", run_in_flight=False))
    assert set(acts) == {"approve", "reject"} and acts["approve"]["allowed"] and acts["approve"]["reason_code"] is None


def test_a_reader_is_shadow_allowed_then_forbidden_under_enforce():
    with patch.object(settings, "rbac_enforce", False):
        a = _by(ua.plan_actions(_plan(), READER, issue_status="fix_planned", run_in_flight=False))["approve"]
        assert (a["allowed"], a["reason_code"]) == (True, "policy_shadow")
    with patch.object(settings, "rbac_enforce", True):
        a = _by(ua.plan_actions(_plan(), READER, issue_status="fix_planned", run_in_flight=False))["approve"]
        assert (a["allowed"], a["reason_code"]) == (False, "forbidden")


def test_a_closed_issue_blocks_approval_but_not_reject():
    acts = _by(ua.plan_actions(_plan(), WRITER, issue_status="resolved", run_in_flight=False))
    assert (acts["approve"]["allowed"], acts["approve"]["reason_code"]) == (False, "issue_closed")
    assert acts["reject"]["allowed"]


def test_approved_plan_execute_reasons_in_route_order():
    plan = _plan("approved")
    with patch.object(settings, "executor_enabled", False):
        a = _by(ua.plan_actions(plan, WRITER, issue_status="fix_approved", run_in_flight=True))["execute"]
        assert (a["allowed"], a["reason_code"]) == (False, "executor_disabled")
    with patch.object(settings, "executor_enabled", True):
        a = _by(ua.plan_actions(plan, WRITER, issue_status="fix_approved", run_in_flight=True))["execute"]
        assert (a["allowed"], a["reason_code"], a["effect"]) == (False, "run_in_flight", "queue_execution")


def test_change_plans_have_no_fix_actions():
    assert ua.plan_actions(_plan(kind="change"), WRITER, issue_status=None, run_in_flight=False) == []


def test_requester_change_approve_is_policy_shadow():
    cr = SimpleNamespace(id=3, status="planned", requested_by="user:alice", risk_level="L1")
    plan = SimpleNamespace(id=9, status="pending_approval")
    with patch.object(settings, "rbac_enforce", False), patch.object(settings, "change_management_enabled", True):
        a = _by(ua.change_actions(cr, WRITER, plan=plan))["approve"]
        assert (a["allowed"], a["reason_code"]) == (True, "policy_shadow")
        assert ua.strictly_allowed(WRITER, "change.approve", cr) is False


def test_change_approve_queues_only_with_executor_and_execute_permission():
    cr = SimpleNamespace(id=3, status="planned", requested_by="user:bob", risk_level="L1")
    with patch.object(settings, "executor_enabled", True), patch.object(settings, "rbac_enforce", True):
        assert ua.change_approve_effect(WRITER, cr) == "approve_and_queue_execution"
        assert ua.change_approve_effect(READER, cr) == "approve_only"
    with patch.object(settings, "executor_enabled", False):
        assert ua.change_approve_effect(WRITER, cr) == "approve_only"


def test_evaluation_writes_no_audit_row():
    with patch("agenticops.auth.authz._audit_denial") as audit, patch.object(settings, "rbac_enforce", True):
        ua.plan_actions(_plan(), READER, issue_status="fix_planned", run_in_flight=False)
        ua.strictly_allowed(READER, "plan.approve", _plan())
    audit.assert_not_called()
