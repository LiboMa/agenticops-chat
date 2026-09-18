"""Identity-bound approval, reject endpoint, tightened PUT, kind filter (MVP-2.6.0 S1)."""
import pytest
from starlette.testclient import TestClient

from agenticops.models import Base, FixPlan, HealthIssue, RCAResult, get_session


@pytest.fixture
def client(tmp_path):
    import agenticops.models as models_mod
    import agenticops.audit.models  # noqa: F401
    from agenticops.config import settings
    from agenticops.web.app import app
    models_mod._engine = None
    settings.database_url = f"sqlite:///{tmp_path}/api.db"
    Base.metadata.create_all(models_mod.get_engine())
    yield TestClient(app)
    models_mod._engine = None


def _plan(status="pending_approval", risk="L1", **fields) -> int:
    s = get_session()
    try:
        issue = HealthIssue(title="t", description="d", severity="low", source="test", status="fix_planned", resource_id="r")
        s.add(issue); s.flush()
        rca = RCAResult(health_issue_id=issue.id, root_cause="x", confidence=0.9)
        s.add(rca); s.flush()
        plan = FixPlan(health_issue_id=issue.id, rca_result_id=rca.id, risk_level=risk, title="p", summary="s",
                       status=status, **fields)
        s.add(plan); s.commit()
        return plan.id
    finally:
        s.close()


def _audit_rows(action=None):
    from agenticops.audit.models import AuditLog
    s = get_session()
    try:
        q = s.query(AuditLog)
        if action:
            q = q.filter_by(action=action)
        return q.all()
    finally:
        s.close()


def test_approve_binds_identity_not_body(client, monkeypatch):
    from unittest.mock import patch
    pid = _plan()
    with patch("agenticops.services.pipeline_service.trigger_auto_execute"):
        r = client.put(f"/api/fix-plans/{pid}/approve", json={"approved_by": "Mallory", "reason": "looks fine"})
    assert r.status_code == 200
    body = r.json()
    assert body["approved_by"] == "web:anonymous"      # auth disabled → anonymous actor, never the client string
    rows = _audit_rows("plan.approved")
    assert len(rows) == 1
    assert rows[0].actor == "web:anonymous"
    assert rows[0].details["claimed_name"] == "Mallory" and rows[0].details["reason"] == "looks fine"
    assert rows[0].old_values == {"status": "pending_approval"} and rows[0].new_values == {"status": "approved"}


def test_approve_without_body_uses_actor(client):
    from unittest.mock import patch
    pid = _plan()
    with patch("agenticops.services.pipeline_service.trigger_auto_execute"):
        r = client.put(f"/api/fix-plans/{pid}/approve")          # no body at all (curl / CLI style)
    assert r.status_code == 200 and r.json()["approved_by"] == "web:anonymous"
    rows = _audit_rows("plan.approved")
    assert len(rows) == 1 and "claimed_name" not in rows[0].details and rows[0].details["reason"] is None


def test_reject_endpoint_requires_reason(client):
    pid = _plan()
    r = client.post(f"/api/fix-plans/{pid}/reject", json={})
    assert r.status_code == 422
    r = client.post(f"/api/fix-plans/{pid}/reject", json={"reason": "not needed"})
    assert r.status_code == 200
    assert r.json()["status"] == "rejected" and r.json()["rejected_by"] == "web:anonymous"
    assert r.json()["rejection_reason"] == "not needed"
    assert len(_audit_rows("plan.rejected")) == 1


def test_approve_already_decided_plan_is_409(client):
    """M-13: approving an already-approved or rejected plan is a state conflict (409, like reject), not a bad
    request; nothing is re-approved, nothing chains, no audit row."""
    from unittest.mock import patch
    approved = _plan(status="approved", approved_by="user:alice")
    rejected = _plan(status="rejected", rejected_by="user:alice", rejection_reason="no")
    with patch("agenticops.services.pipeline_service.trigger_auto_execute") as trigger:
        assert client.put(f"/api/fix-plans/{approved}/approve", json={}).status_code == 409
        assert client.put(f"/api/fix-plans/{rejected}/approve", json={}).status_code == 409
    trigger.assert_not_called()
    row = client.get(f"/api/fix-plans/{rejected}").json()
    assert row["status"] == "rejected" and row["rejected_by"] == "user:alice" and row["approved_by"] is None
    assert client.get(f"/api/fix-plans/{approved}").json()["approved_by"] == "user:alice"
    assert _audit_rows("plan.approved") == []


def test_reject_terminal_plan_is_409(client):
    pid = _plan(status="executed")
    r = client.post(f"/api/fix-plans/{pid}/reject", json={"reason": "late"})
    assert r.status_code == 409


def test_reject_already_rejected_plan_is_409_and_preserves_original(client):
    # validate_plan_transition short-circuits on current == new, so without an explicit guard a second
    # reject would silently overwrite rejected_by / rejected_at / rejection_reason (rejected is terminal)
    pid = _plan(status="rejected", rejected_by="user:alice", rejection_reason="original")
    r = client.post(f"/api/fix-plans/{pid}/reject", json={"reason": "again"})
    assert r.status_code == 409
    r = client.put(f"/api/fix-plans/{pid}", json={"status": "rejected"})
    assert r.status_code == 409
    row = client.get(f"/api/fix-plans/{pid}").json()
    assert row["status"] == "rejected" and row["rejected_by"] == "user:alice" and row["rejection_reason"] == "original"
    assert _audit_rows("plan.rejected") == []


def test_second_reject_does_not_overwrite_the_first(client):
    pid = _plan()
    assert client.post(f"/api/fix-plans/{pid}/reject", json={"reason": "first"}).status_code == 200
    assert client.post(f"/api/fix-plans/{pid}/reject", json={"reason": "second"}).status_code == 409
    assert client.put(f"/api/fix-plans/{pid}", json={"status": "rejected"}).status_code == 409
    row = client.get(f"/api/fix-plans/{pid}").json()
    assert row["rejection_reason"] == "first" and row["rejected_by"] == "web:anonymous"
    assert len(_audit_rows("plan.rejected")) == 1


def test_put_no_longer_accepts_status_or_approver(client):
    pid = _plan(status="draft")
    r = client.put(f"/api/fix-plans/{pid}", json={"approved_by": "x"})
    assert r.status_code == 422
    r = client.put(f"/api/fix-plans/{pid}", json={"status": "approved"})
    assert r.status_code == 400
    r = client.put(f"/api/fix-plans/{pid}", json={"title": "renamed"})
    assert r.status_code == 200 and r.json()["title"] == "renamed"


def test_put_status_rejected_is_a_deprecated_alias(client):
    pid = _plan(status="draft")
    r = client.put(f"/api/fix-plans/{pid}", json={"status": "rejected"})
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    assert r.json()["rejection_reason"] == "(rejected via deprecated PUT status)"
    assert len(_audit_rows("plan.rejected")) == 1


def test_execute_records_actor(client):
    from unittest.mock import patch
    from agenticops.config import settings
    pid = _plan(status="approved")
    with patch.object(settings, "executor_enabled", True):
        r = client.post(f"/api/fix-plans/{pid}/execute", json={})
    assert r.status_code == 202
    assert r.json()["executed_by"] == "web:anonymous"
    assert len(_audit_rows("plan.execute_requested")) == 1


def test_list_kind_filter_and_new_fields(client):
    _plan(status="draft")
    r = client.get("/api/fix-plans?kind=fix")
    assert r.status_code == 200 and len(r.json()) == 1
    row = r.json()[0]
    assert row["plan_kind"] == "fix" and row["change_request_id"] is None and "rejected_by" in row
    assert client.get("/api/fix-plans?kind=change").json() == []


def test_current_actor_stamps_run_context_seen_by_handler(client):
    """The dependency must run in the request's own context (async def): a sync dependency runs in a
    threadpool under a COPIED context and its update_run_context() is invisible to the handler."""
    from unittest.mock import patch
    from agenticops.audit.service import AuditService
    from agenticops.run_context import get_run_context
    seen = {}
    real_log = AuditService.log

    def spy(*args, **kwargs):
        ctx = get_run_context()
        seen.update(actor=ctx.actor, permissions=ctx.actor_permissions)
        return real_log(*args, **kwargs)

    pid = _plan()
    with patch.object(AuditService, "log", staticmethod(spy)):
        r = client.post(f"/api/fix-plans/{pid}/reject", json={"reason": "ctx check"})
    assert r.status_code == 200
    assert seen["actor"] == "web:anonymous"
    assert seen["permissions"] == ()


def test_current_actor_stamps_user_permissions_on_run_context():
    """Ruling 3: with api_auth_enabled the user's rbac flags must ride on the Run Context, or Task 9
    agent tools rebuilding the actor from it would shadow-deny every authenticated user."""
    import asyncio
    from types import SimpleNamespace
    from agenticops.run_context import get_run_context, run_context
    from agenticops.web.deps import current_actor
    user = SimpleNamespace(id=5, email="admin", permissions=["read", "write"])
    req = SimpleNamespace(state=SimpleNamespace(user=user))

    async def go():
        actor = await current_actor(req)
        return actor, get_run_context()

    with run_context():  # keep the stamp out of the test process's own context
        actor, ctx = asyncio.run(go())
    assert actor.key == "user:admin"
    assert (ctx.actor, ctx.actor_user_id, ctx.actor_permissions) == ("user:admin", 5, ("read", "write"))
    assert get_run_context().actor == "system"
