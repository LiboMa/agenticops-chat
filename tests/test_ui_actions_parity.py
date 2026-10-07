"""ui_actions.allowed must be what the route does (MVP-2.7.0 S3): every fix-plan / change decision, for each actor,
in shadow and enforce mode, against the real endpoint."""
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from agenticops.auth.actor import Actor
from agenticops.models import Base, CloudAccount, CloudResource, FixPlan, HealthIssue, RCAResult, get_session

ACTORS = {
    "anonymous": Actor("web", "anonymous"),
    "writer": Actor("user", "alice", 1, ("read", "write")),
    "reader": Actor("user", "rita", 2, ("read",)),
    "admin": Actor("user", "root", 3, ("read", "write", "admin")),
    "agent": Actor("agent", "sre"),
    "webhook": Actor("webhook", "jira"),
}


@pytest.fixture
def client(tmp_path, monkeypatch):
    import agenticops.models as models_mod
    import agenticops.audit.models  # noqa: F401
    from agenticops.config import settings
    from agenticops.web.app import app
    monkeypatch.setattr(models_mod, "_engine", None)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/parity.db")
    monkeypatch.setattr(settings, "executor_enabled", True)
    monkeypatch.setattr(settings, "change_management_enabled", True)
    Base.metadata.create_all(models_mod.get_engine())
    # tests.test_changes_api._planned() grounds its change on the account 'dev' and its instance i-0abc
    s = get_session()
    acct = CloudAccount(name="dev", provider="aws", is_enabled=True, credentials={}, regions=["ap-southeast-1"]); s.add(acct); s.flush()
    s.add(CloudResource(account_id=acct.id, provider="aws", region="ap-southeast-1", resource_type="EC2Instance", resource_id="i-0abc", name="web"))
    s.commit(); s.close()
    yield TestClient(app)
    app.dependency_overrides.clear()


def _plan(status, risk):
    s = get_session()
    try:
        issue = HealthIssue(title="t", description="d", severity="low", source="test",
                            status="fix_approved" if status == "approved" else "fix_planned", resource_id="r")
        s.add(issue); s.flush()
        rca = RCAResult(health_issue_id=issue.id, root_cause="x", confidence=0.9)
        s.add(rca); s.flush()
        plan = FixPlan(health_issue_id=issue.id, rca_result_id=rca.id, risk_level=risk, title="p", summary="s",
                       status=status, approved_by="user:bob" if status == "approved" else None)
        s.add(plan); s.flush()
        from agenticops.services.plan_content import stamp_content
        stamp_content(s, plan); s.commit()
        return plan.id, plan.content_hash
    finally:
        s.close()


def _actions(client, pid):
    return {a["action"]: a for a in client.get(f"/api/fix-plans/{pid}").json()["available_actions"]}


@pytest.mark.parametrize("enforce", [False, True])
@pytest.mark.parametrize("who", list(ACTORS))
@pytest.mark.parametrize("decision,status,risk", [
    ("approve", "pending_approval", "L1"), ("approve", "pending_approval", "L2"), ("approve", "draft", "L1"),
    ("reject", "pending_approval", "L1"), ("reject", "approved", "L1"), ("execute", "approved", "L1"),
])
def test_fix_plan_actions_match_the_routes(client, monkeypatch, enforce, who, decision, status, risk):
    from agenticops.config import settings
    from agenticops.web import deps
    from agenticops.web.app import app
    monkeypatch.setattr(settings, "rbac_enforce", enforce)
    app.dependency_overrides[deps.current_actor] = lambda: ACTORS[who]
    pid, h = _plan(status, risk)
    action = _actions(client, pid)[decision]
    with patch("agenticops.services.pipeline_service.trigger_auto_execute"):
        if decision == "approve":
            r = client.put(f"/api/fix-plans/{pid}/approve", json={"content_hash": h})
        elif decision == "reject":
            r = client.post(f"/api/fix-plans/{pid}/reject", json={"reason": "no"})
        else:
            r = client.post(f"/api/fix-plans/{pid}/execute")
    assert (200 <= r.status_code < 300) == action["allowed"], (who, enforce, r.status_code, action)


@pytest.mark.parametrize("enforce", [False, True])
@pytest.mark.parametrize("who", ["writer", "admin", "reader", "anonymous"])
def test_change_approve_matches_the_route(client, monkeypatch, enforce, who):
    """writer IS the requester (SoD): shadow lets it through, enforce refuses it."""
    from tests.test_changes_api import _planned
    from agenticops.config import settings
    from agenticops.web import deps
    from agenticops.web.app import app
    monkeypatch.setattr(settings, "rbac_enforce", enforce)
    monkeypatch.setattr(settings, "change_auto_approve_standard", False)
    cr_id = _planned()
    app.dependency_overrides[deps.current_actor] = lambda: ACTORS[who]
    detail = client.get(f"/api/changes/{cr_id}").json()
    action = {a["action"]: a for a in detail["available_actions"]}["approve"]
    plan_hash = detail["plans"][0]["content_hash"]
    r = client.post(f"/api/changes/{cr_id}/approve", json={"reason": "ok", "content_hash": plan_hash})
    assert (200 <= r.status_code < 300) == action["allowed"], (who, enforce, r.status_code, action)
