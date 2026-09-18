# tests/test_plan_transition_enforcement.py
"""Every status write on FixPlan must go through validate_plan_transition (MVP-2.6.0 S0)."""
import pytest
from unittest.mock import patch

from agenticops.models import Base, FixPlan, HealthIssue, RCAResult, get_engine, get_session


@pytest.fixture
def db(tmp_path):
    import agenticops.models as models_mod
    from agenticops.config import settings
    models_mod._engine = None
    settings.database_url = f"sqlite:///{tmp_path}/enforce.db"
    Base.metadata.create_all(models_mod.get_engine())
    s = get_session()
    yield s
    s.close()
    models_mod._engine = None


def _plan(db, status="draft", risk="L1") -> FixPlan:
    issue = HealthIssue(title="t", description="d", severity="low", source="test", status="fix_planned", resource_id="r")
    db.add(issue); db.flush()
    rca = RCAResult(health_issue_id=issue.id, root_cause="x", confidence=0.9)
    db.add(rca); db.flush()
    plan = FixPlan(health_issue_id=issue.id, rca_result_id=rca.id, risk_level=risk, title="p", summary="s", status=status)
    db.add(plan); db.commit()
    return plan


def test_tool_approve_refuses_executed_plan(db):
    from agenticops.tools.metadata_tools import approve_fix_plan
    plan = _plan(db, status="executed")
    out = approve_fix_plan(fix_plan_id=plan.id, approved_by="operator:admin")
    assert "Cannot transition plan" in out
    db.refresh(plan)
    assert plan.status == "executed"


def test_tool_save_execution_result_from_approved_goes_through_executing(db):
    from agenticops.tools.metadata_tools import save_execution_result
    plan = _plan(db, status="approved")
    with patch("agenticops.services.notification_service.notify_execution_result"), \
         patch("agenticops.services.notification_service.notify_im_origin"):
        out = save_execution_result(fix_plan_id=plan.id, health_issue_id=plan.health_issue_id, status="succeeded")
    assert "FixExecution #" in out
    db.refresh(plan)
    assert plan.status == "executed"


def test_tool_save_execution_result_refuses_draft(db):
    from agenticops.tools.metadata_tools import save_execution_result
    plan = _plan(db, status="draft")
    out = save_execution_result(fix_plan_id=plan.id, health_issue_id=plan.health_issue_id, status="succeeded")
    assert "not executable" in out
    db.refresh(plan)
    assert plan.status == "draft"


def test_api_approve_executed_plan_is_409(db):
    from starlette.testclient import TestClient
    from agenticops.web.app import app
    plan = _plan(db, status="executed")
    client = TestClient(app)
    r = client.put(f"/api/fix-plans/{plan.id}/approve", json={"approved_by": "tester"})
    assert r.status_code == 409


def test_executor_service_mark_crashed_uses_validator(db):
    from agenticops.models import FixExecution
    from agenticops.services.executor_service import ExecutorService
    plan = _plan(db, status="executing")
    ex = FixExecution(fix_plan_id=plan.id, health_issue_id=plan.health_issue_id, status="running", executed_by="t")
    db.add(ex); db.commit()
    ExecutorService()._mark_crashed(ex.id, plan.id, "boom")
    db.expire_all()
    assert db.get(FixPlan, plan.id).status == "failed"
