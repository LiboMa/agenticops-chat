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
         patch("agenticops.services.pipeline_service.trigger_auto_execute"):
        out = _slash_approve(None, [str(plan.id), "looks", "good"])
    assert "approved by cli:malibo" in out
    db.refresh(plan)
    assert plan.approved_by == "cli:malibo"
    rows = _audits(db, "plan.approved")
    assert rows[0].details["reason"] == "looks good"
