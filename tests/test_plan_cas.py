"""FixPlan status writes are compare-and-set (MVP-2.7.0 S3): two approvals of one plan cannot both win, and
withdrawing an approved plan returns its issue to root_cause_identified (the 2.6.1 back-edge)."""
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from agenticops.models import (Base, FixPlan, HealthIssue, PlanStatusConflict, RCAResult, get_session,
                               transition_plan)


@pytest.fixture
def client(tmp_path):
    import agenticops.models as models_mod
    import agenticops.audit.models  # noqa: F401
    from agenticops.config import settings
    from agenticops.web.app import app
    models_mod._engine = None
    settings.database_url = f"sqlite:///{tmp_path}/cas.db"
    Base.metadata.create_all(models_mod.get_engine())
    yield TestClient(app)
    models_mod._engine = None


def _plan(plan_status="pending_approval", issue_status="fix_planned"):
    s = get_session()
    try:
        issue = HealthIssue(title="t", description="d", severity="low", source="test", status=issue_status, resource_id="r")
        s.add(issue); s.flush()
        rca = RCAResult(health_issue_id=issue.id, root_cause="x", confidence=0.9)
        s.add(rca); s.flush()
        plan = FixPlan(health_issue_id=issue.id, rca_result_id=rca.id, risk_level="L1", title="p", summary="s",
                       status=plan_status, approved_by="user:alice" if plan_status == "approved" else None)
        s.add(plan); s.commit()
        return plan.id, issue.id
    finally:
        s.close()


def test_two_sessions_cannot_both_move_the_plan(client):
    pid, _ = _plan()
    a, b = get_session(), get_session()
    try:
        pa, pb = a.get(FixPlan, pid), b.get(FixPlan, pid)       # both read pending_approval
        transition_plan(pa, "approved"); a.commit()
        with pytest.raises(PlanStatusConflict):
            transition_plan(pb, "approved")
        b.rollback()
    finally:
        a.close(); b.close()
    s = get_session()
    assert s.get(FixPlan, pid).status == "approved"
    s.close()


def test_a_plan_not_in_a_session_is_still_validated_and_assigned():
    plan = FixPlan(status="draft")
    transition_plan(plan, "approved")
    assert plan.status == "approved"


def test_withdrawing_an_approved_plan_returns_the_issue(client):
    pid, iid = _plan(plan_status="approved", issue_status="fix_approved")
    r = client.post(f"/api/fix-plans/{pid}/reject", json={"reason": "wrong target"})
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    s = get_session()
    assert s.get(HealthIssue, iid).status == "root_cause_identified"
    s.close()


def test_rejecting_a_pending_plan_leaves_the_issue_planned(client):
    pid, iid = _plan()
    assert client.post(f"/api/fix-plans/{pid}/reject", json={"reason": "no"}).status_code == 200
    s = get_session()
    assert s.get(HealthIssue, iid).status == "fix_planned"
    s.close()


def test_a_second_approval_of_the_same_plan_is_409_and_runs_once(client):
    from agenticops.services.plan_content import current_hash
    pid, _ = _plan()
    s = get_session(); h = current_hash(s, s.get(FixPlan, pid)); s.close()
    with patch("agenticops.services.pipeline_service.trigger_auto_execute") as run:
        assert client.put(f"/api/fix-plans/{pid}/approve", json={"content_hash": h}).status_code == 200
        assert client.put(f"/api/fix-plans/{pid}/approve", json={"content_hash": h}).status_code == 409
    assert run.call_count == 1
