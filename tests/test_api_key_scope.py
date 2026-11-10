"""API keys (MVP-2.8.0, owner 2026-11-10): a read-only key is read-only, and no key makes a human decision.

Before: a key's scope only narrowed the actor's permissions, which RBAC shadow mode does not enforce — so a writer's
«read-only» key could write, and its chat turn ran the full agent; a read-write key could approve and run a plan.
Now a request authenticated by a key without `write` is a viewer for that request (APIAuthMiddleware, actor
read_only), and the rbac rule `no-api-key-human-decisions` (enforce: always) refuses approve / reject / execute /
accept / resolve for any request that came through a key, the agent tools of its chat turns included.

The app is imported BEFORE sign-in is turned on (app.py attaches APIAuthMiddleware at import when it is on, and it
would stay for every later test); the middleware is wrapped around the app here instead."""
from types import SimpleNamespace

import pytest
from starlette.testclient import TestClient

from agenticops.auth.roles import grants
from agenticops.models import Base


@pytest.fixture
def env(tmp_path, monkeypatch):
    import agenticops.audit.models  # noqa: F401
    import agenticops.auth.models  # noqa: F401
    import agenticops.models as models_mod
    from agenticops.config import settings
    from agenticops.web.app import APIAuthMiddleware, app
    monkeypatch.setattr(models_mod, "_engine", None)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/keys.db")
    monkeypatch.setattr(settings, "api_auth_enabled", True)
    monkeypatch.setattr(settings, "rbac_enforce", False)          # shadow mode: the default
    Base.metadata.create_all(models_mod.get_engine())
    return SimpleNamespace(client=TestClient(APIAuthMiddleware(app)), settings=settings)


def _user(email, role="writer"):
    from agenticops.auth import AuthService
    is_admin, perms = grants(role)
    u = AuthService.create_user(email=email, password=f"pw-{email}-0", is_admin=is_admin, permissions=perms)
    return u, AuthService.create_session(u.id)


def _key(user, perms):
    from agenticops.auth import AuthService
    return AuthService.create_api_key(user_id=user.id, name="k", permissions=perms)


def H(tok):
    return {"Authorization": f"Bearer {tok}"}


def _issue_and_plan():
    from agenticops.models import FixPlan, HealthIssue, RCAResult, get_session
    s = get_session()
    try:
        i = HealthIssue(title="t", description="d", severity="low", source="test", status="fix_planned", resource_id="i-1")
        s.add(i); s.flush()
        rca = RCAResult(health_issue_id=i.id, root_cause="x", confidence=0.9, critic_verdict="supported")
        s.add(rca); s.flush()
        p = FixPlan(health_issue_id=i.id, rca_result_id=rca.id, plan_kind="fix", risk_level="L2", title="p", summary="s",
                    status="pending_approval", steps=[{"command": "aws ec2 describe-instances"}])
        s.add(p); s.commit()
        return i.id, p.id
    finally:
        s.close()


def _plan_status(pid):
    from agenticops.models import FixPlan, get_session
    s = get_session()
    try:
        return s.query(FixPlan).filter_by(id=pid).one().status
    finally:
        s.close()


# ── a read-only key is read-only ──────────────────────────────────────────────────────────────────────────


def test_a_writers_read_only_key_reads_but_never_writes_even_in_shadow_mode(env):
    ops, ops_session = _user("ops", "writer")
    key = _key(ops, ["read"])
    iid, _ = _issue_and_plan()
    assert env.client.get("/api/health-issues", headers=H(key)).status_code == 200
    r = env.client.post(f"/api/health-issues/{iid}/notes", headers=H(key), json={"content": "from a read key"})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "read_only"
    # the same user signed in writes as before
    assert env.client.post(f"/api/health-issues/{iid}/notes", headers=H(ops_session), json={"content": "me"}).status_code == 201


def test_a_read_only_key_is_a_read_only_actor_and_marked_as_via_a_key():
    from agenticops.auth.actor import actor_from_request
    user = SimpleNamespace(id=2, email="ops", permissions=["read", "write"], is_admin=False)
    read_key = SimpleNamespace(permissions=["read"])
    rw_key = SimpleNamespace(permissions=["read", "write"])
    a = actor_from_request(SimpleNamespace(state=SimpleNamespace(user=user, api_key=read_key)))
    assert a.read_only is True and a.via_api_key is True and a.permissions == ("read",)
    b = actor_from_request(SimpleNamespace(state=SimpleNamespace(user=user, api_key=rw_key)))
    assert b.read_only is False and b.via_api_key is True
    c = actor_from_request(SimpleNamespace(state=SimpleNamespace(user=user, api_key=None)))
    assert c.read_only is False and c.via_api_key is False


def test_the_run_context_carries_via_api_key_to_the_tools():
    from agenticops.auth.actor import actor_from_run_context
    from agenticops.run_context import RunContext
    a = actor_from_run_context(RunContext(actor="user:ops", actor_user_id=2, actor_permissions=("read", "write"),
                                          via_api_key=True))
    assert a.via_api_key is True and a.key == "user:ops"


# ── no key makes a human decision ─────────────────────────────────────────────────────────────────────────


def test_a_read_write_key_writes_notes_but_never_approves_even_in_shadow_mode(env):
    ops, _ = _user("ops", "writer")
    key = _key(ops, ["read", "write"])
    iid, pid = _issue_and_plan()
    assert env.client.post(f"/api/health-issues/{iid}/notes", headers=H(key), json={"content": "ok"}).status_code == 201
    r = env.client.put(f"/api/fix-plans/{pid}/approve", headers=H(key), json={"content_hash": "x"})
    assert r.status_code == 403, r.text
    assert "human_session_required" in r.text
    assert _plan_status(pid) == "pending_approval"


def test_the_rule_is_always_enforced_for_every_human_decision():
    from agenticops.auth.actor import Actor
    from agenticops.auth.authz import get_rbac_policy
    policy = get_rbac_policy()
    via_key = Actor("user", "ops", 2, ("read", "write", "admin"), via_api_key=True)
    session = Actor("user", "ops", 2, ("read", "write", "admin"))
    subject = SimpleNamespace(requested_by="user:someone-else", risk_level="L1")
    for perm in ("plan.approve", "plan.reject", "plan.execute", "change.approve", "change.reject", "change.execute"):
        allowed, reason, rule, always = policy.decide(via_key, perm, subject)
        assert (allowed, rule, always) == (False, "no-api-key-human-decisions", True), perm
        assert "human_session_required" in reason
        assert policy.decide(session, perm, subject)[0] is True, perm


def test_an_agent_tool_in_a_key_chat_cannot_approve(env):
    from agenticops.run_context import RunContext, reset_run_context, set_run_context
    from agenticops.tools.metadata_tools import approve_fix_plan
    ops, _ = _user("ops", "writer")
    _, pid = _issue_and_plan()
    token = set_run_context(RunContext(actor="user:ops", actor_user_id=ops.id, actor_permissions=("read", "write"),
                                       via_api_key=True, agent_name="main"))
    try:
        out = approve_fix_plan(pid, "ops")
    finally:
        reset_run_context(token)
    assert _plan_status(pid) == "pending_approval", out
    assert "human_session_required" in out, out
