"""Task 9 (Change Management P1): agent tool / auto-pipeline / CLI approvals go through authz,
write a same-transaction audit row, and bind the approver to the acting identity.

Rule under test: the LLM-supplied `approved_by` string NEVER becomes the approver.
  - with a Run Context  → the context actor approves; the string is only audited (details.claimed_name)
  - without a Run Context → a context-less tool call is an agent acting, never a human
"""

from unittest.mock import patch

import pytest

from agenticops.models import Base, FixPlan, HealthIssue, RCAResult, get_session
from agenticops.run_context import run_context


@pytest.fixture
def db(tmp_path):
    import agenticops.models as models_mod
    import agenticops.audit.models  # noqa: F401 — registers audit_logs before create_all
    from agenticops.config import settings
    models_mod._engine = None
    settings.database_url = f"sqlite:///{tmp_path}/approval.db"
    Base.metadata.create_all(models_mod.get_engine())
    s = get_session()
    yield s
    s.close()
    models_mod._engine = None


def _plan(db, status="draft", risk="L1"):
    issue = HealthIssue(title="t", description="d", severity="low", source="test", status="fix_planned", resource_id="r")
    db.add(issue); db.flush()
    rca = RCAResult(health_issue_id=issue.id, root_cause="x", confidence=0.9)
    db.add(rca); db.flush()
    plan = FixPlan(health_issue_id=issue.id, rca_result_id=rca.id, risk_level=risk, title="p", summary="s", status=status)
    db.add(plan); db.commit()
    return plan


def _audits(db, action):
    from agenticops.audit.models import AuditLog
    return db.query(AuditLog).filter_by(action=action).all()


def test_tool_approve_uses_run_context_actor(db):
    from agenticops.tools.metadata_tools import approve_fix_plan
    plan = _plan(db)
    with run_context(actor="user:alice", actor_user_id=3, actor_permissions=("read", "write")), \
         patch("agenticops.services.pipeline_service.trigger_auto_execute"), \
         patch("agenticops.services.notification_service.notify_fix_approved"):
        out = approve_fix_plan(fix_plan_id=plan.id, approved_by="Some Name")
    assert "approved by user:alice" in out
    db.refresh(plan)
    assert plan.approved_by == "user:alice"
    rows = _audits(db, "plan.approved")
    assert len(rows) == 1 and rows[0].actor == "user:alice" and rows[0].details["claimed_name"] == "Some Name"
    assert rows[0].user_id == 3


def test_tool_approve_without_context_acts_as_agent(db):
    """No Run Context = an agent is acting. A non-agent claimed name is audited, never honoured."""
    from agenticops.tools.metadata_tools import approve_fix_plan
    plan = _plan(db)
    with patch("agenticops.services.pipeline_service.trigger_auto_execute"), \
         patch("agenticops.services.notification_service.notify_fix_approved"):
        out = approve_fix_plan(fix_plan_id=plan.id, approved_by="operator:admin")
    assert "approved by agent:unattributed" in out
    db.refresh(plan)
    assert plan.status == "approved"
    assert plan.approved_by == "agent:unattributed"
    rows = _audits(db, "plan.approved")
    assert len(rows) == 1
    assert rows[0].actor == "agent:unattributed"
    assert rows[0].details["claimed_name"] == "operator:admin"


def test_tool_approve_without_context_l2_is_parked(db):
    """A human-looking name cannot lift the agent ceiling: L2 without a context is parked for a human."""
    from agenticops.tools.metadata_tools import approve_fix_plan
    plan = _plan(db, risk="L2")
    out = approve_fix_plan(fix_plan_id=plan.id, approved_by="John Doe")
    assert "requires human approval" in out
    db.refresh(plan)
    assert plan.status == "pending_approval" and plan.approved_by is None
    assert len(_audits(db, "authz.denied")) == 1
    assert _audits(db, "plan.approved") == []


def test_agent_cannot_approve_l2_even_in_shadow_mode(db):
    from agenticops.config import settings
    from agenticops.tools.metadata_tools import approve_fix_plan
    plan = _plan(db, risk="L2")
    with patch.object(settings, "rbac_enforce", False):
        out = approve_fix_plan(fix_plan_id=plan.id, approved_by="agent:sre_agent")
    assert "requires human approval" in out
    db.refresh(plan)
    assert plan.status == "pending_approval" and plan.approved_by is None
    assert len(_audits(db, "authz.denied")) == 1


def test_auto_approve_writes_audit_with_rule(db):
    from agenticops.config import settings
    from agenticops.services.pipeline_service import trigger_auto_approve
    plan = _plan(db)
    with patch.object(settings, "auto_fix_enabled", True), patch.object(settings, "executor_auto_approve_l0_l1", True), \
         patch.object(settings, "policy_engine_enabled", True), \
         patch("agenticops.services.pipeline_service.trigger_auto_execute"):
        trigger_auto_approve(plan.id)
    db.refresh(plan)
    assert plan.status == "approved" and plan.approved_by == "agent:auto-pipeline"
    rows = _audits(db, "plan.approved")
    assert len(rows) == 1 and rows[0].actor == "agent:auto-pipeline"
    assert rows[0].details["policy_rule"] == "auto-approve-low-risk"


def test_cli_approve_binds_cli_actor(db):
    from agenticops.cli.main import _slash_approve
    plan = _plan(db)
    with patch("getpass.getuser", return_value="malibo"), \
         patch("agenticops.cli.main.init_db"), \
         patch("agenticops.services.pipeline_service.trigger_auto_execute") as trigger:
        out = _slash_approve(None, [str(plan.id), "looks", "good"])
    assert "approved by cli:malibo" in out
    # CLI approve never chains into execution: the operator runs /execute explicitly
    trigger.assert_not_called()
    assert out.endswith(f"Execute with: /execute {plan.id}")
    db.refresh(plan)
    assert plan.approved_by == "cli:malibo"
    rows = _audits(db, "plan.approved")
    assert rows[0].details["reason"] == "looks good"


# ── Final fix wave, group 1 (I-1 + M-6): a self-declared agent identity is a privilege CEILING ─────


def test_agent_claim_inside_human_context_parks_l3_and_does_not_chain(db):
    """I-1: inside a chat turn the context actor approves, but an `agent:`-declared approval is ALSO held
    to the agent ceiling — the claim can only lower authority. L3 parks, nothing chains, the denial row
    carries the claimed name."""
    from agenticops.tools.metadata_tools import approve_fix_plan
    plan = _plan(db, risk="L3")
    with run_context(actor="web:anonymous"), \
         patch("agenticops.services.pipeline_service.trigger_auto_execute") as trigger, \
         patch("agenticops.services.notification_service.notify_fix_approved") as notify:
        out = approve_fix_plan(fix_plan_id=plan.id, approved_by="agent:sre")
    assert "requires human approval" in out and "pending_approval" in out
    trigger.assert_not_called()
    notify.assert_not_called()
    db.refresh(plan)
    assert plan.status == "pending_approval" and plan.approved_by is None
    assert _audits(db, "plan.approved") == []
    rows = _audits(db, "authz.denied")
    assert len(rows) == 1
    assert rows[0].details["claimed_name"] == "agent:sre"
    assert rows[0].details["context_actor"] == "web:anonymous"
    assert rows[0].details["rule"] == "no-agent-approval-above-l1"


def test_agent_claim_inside_human_context_still_approves_l1(db):
    """The ceiling only bites above L1: an `agent:`-declared L1 approval goes through as the context actor."""
    from agenticops.tools.metadata_tools import approve_fix_plan
    plan = _plan(db, risk="L1")
    with run_context(actor="web:anonymous"), \
         patch("agenticops.services.pipeline_service.trigger_auto_execute") as trigger, \
         patch("agenticops.services.notification_service.notify_fix_approved"):
        out = approve_fix_plan(fix_plan_id=plan.id, approved_by="agent:sre")
    assert "approved by web:anonymous" in out
    trigger.assert_called_once()
    db.refresh(plan)
    assert plan.status == "approved" and plan.approved_by == "web:anonymous"
    rows = _audits(db, "plan.approved")
    assert len(rows) == 1 and rows[0].actor == "web:anonymous" and rows[0].details["claimed_name"] == "agent:sre"
    assert _audits(db, "authz.denied") == []


def test_human_claim_inside_human_context_approves_l3_unchanged(db):
    """A human-looking claimed name is not an agent claim: no ceiling check, the L3 approval is unchanged."""
    from agenticops.tools.metadata_tools import approve_fix_plan
    plan = _plan(db, risk="L3")
    with run_context(actor="web:anonymous"), \
         patch("agenticops.services.pipeline_service.trigger_auto_execute") as trigger, \
         patch("agenticops.services.notification_service.notify_fix_approved"):
        out = approve_fix_plan(fix_plan_id=plan.id, approved_by="alice")
    assert "approved by web:anonymous" in out
    trigger.assert_called_once()
    db.refresh(plan)
    assert plan.status == "approved" and plan.approved_by == "web:anonymous"
    rows = _audits(db, "plan.approved")
    assert len(rows) == 1 and rows[0].details["claimed_name"] == "alice"
    assert _audits(db, "authz.denied") == []


def test_context_less_unknown_agent_name_is_unattributed(db):
    """M-6: without a Run Context the stored agent identity comes from the fixed known set — an LLM-chosen
    name outside it is audited as the claim and stored as agent:unattributed."""
    from agenticops.tools.metadata_tools import approve_fix_plan
    plan = _plan(db, risk="L1")
    with patch("agenticops.services.pipeline_service.trigger_auto_execute"), \
         patch("agenticops.services.notification_service.notify_fix_approved"):
        out = approve_fix_plan(fix_plan_id=plan.id, approved_by="agent:bogus")
    assert "approved by agent:unattributed" in out
    db.refresh(plan)
    assert plan.status == "approved" and plan.approved_by == "agent:unattributed"
    rows = _audits(db, "plan.approved")
    assert len(rows) == 1 and rows[0].actor == "agent:unattributed" and rows[0].details["claimed_name"] == "agent:bogus"


@pytest.mark.parametrize("name", ["main", "sre", "executor", "rca", "scan", "detect", "reporter", "auto-pipeline"])
def test_context_less_known_agent_name_is_kept(db, name):
    from agenticops.tools.metadata_tools import approve_fix_plan
    plan = _plan(db, risk="L1")
    with patch("agenticops.services.pipeline_service.trigger_auto_execute"), \
         patch("agenticops.services.notification_service.notify_fix_approved"):
        out = approve_fix_plan(fix_plan_id=plan.id, approved_by=f"agent:{name}")
    assert f"approved by agent:{name}" in out
    db.refresh(plan)
    assert plan.approved_by == f"agent:{name}"
    (row,) = _audits(db, "plan.approved")
    assert row.actor == f"agent:{name}" and "claimed_name" not in row.details
