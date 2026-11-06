# tests/test_viewer_role.py
"""Viewer accounts: a signed-in user whose own permissions lack "write" can browse and chat, and change nothing.

Layers under test: APIAuthMiddleware refuses every write outside the allowlist (walked over the real app's routes);
chat — a viewer writes only into its own sessions, runs no /channel or /send_to, and its turn never runs on a full
agent; the read-only agent's tools are exactly the allowlist; every CLI tool refuses a non-readonly command (and
kubectl secret reads) under RunContext.read_only; available_actions hide writes; self-registration is gone;
`aiops users` creates / lists / disables accounts.
"""
import re
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import pytest
from starlette.testclient import TestClient

from agenticops.auth.actor import Actor
from agenticops.auth.viewer import READ_ONLY_MESSAGE, is_viewer, viewer_may
from agenticops.models import Base, ChatSession, CommandAudit, get_session
from agenticops.run_context import get_run_context, run_context

SID = str(uuid.uuid4())
READ_ONLY_BODY = {"detail": {"detail": READ_ONLY_MESSAGE, "code": "read_only"}}


def _temp_db(tmp_path, monkeypatch, name="viewer.db"):
    import agenticops.audit.models  # noqa: F401  (command_audits / audit tables)
    import agenticops.auth.models  # noqa: F401  (users / sessions / api_keys)
    import agenticops.models as models_mod
    from agenticops.config import settings
    monkeypatch.setattr(models_mod, "_engine", None)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/{name}")
    Base.metadata.create_all(models_mod.get_engine())
    return settings


# ── the policy (pure) ─────────────────────────────────────────────────────────


def test_a_viewer_is_a_user_whose_own_flags_lack_write():
    assert is_viewer(SimpleNamespace(permissions=["read"]))
    assert is_viewer(SimpleNamespace(permissions=[]))
    assert is_viewer(SimpleNamespace(permissions=None))
    assert not is_viewer(SimpleNamespace(permissions=["read", "write"]))
    assert not is_viewer(SimpleNamespace(permissions=["read", "write", "admin"]))
    assert not is_viewer(None)


@pytest.mark.parametrize("method,path", [
    ("POST", "/api/auth/logout"), ("PUT", "/api/users/me/password"), ("PATCH", "/api/users/me/preferences"),
    ("POST", "/api/chat/sessions"), ("PATCH", f"/api/chat/sessions/{SID}"), ("DELETE", f"/api/chat/sessions/{SID}"),
    ("POST", f"/api/chat/sessions/{SID}/messages"),
    ("POST", "/api/graph/vpc/vpc-0abc123/dependency-chain"), ("POST", "/api/graph/vpc/vpc-0abc123/change-simulation"),
    ("GET", "/api/settings"), ("GET", "/api/health-issues/5"), ("get", "/api/accounts"),
])
def test_reads_and_the_allowlisted_writes_pass(method, path):
    assert viewer_may(method, path)


@pytest.mark.parametrize("method,path", [
    ("POST", f"/api/chat/sessions/{SID}"),             # a session id is never the create route
    ("PATCH", "/api/chat/sessions"), ("DELETE", "/api/chat/sessions"), ("POST", "/api/chat/sessions/"),
    ("POST", f"/api/chat/sessions/{SID}/messages/x"), ("PATCH", f"/api/chat/sessions/{SID}/messages"),
    ("PATCH", "/api/settings"), ("POST", "/api/api-keys"), ("DELETE", "/api/api-keys/1"),
    ("POST", "/api/health-issues/5/rca"), ("POST", "/api/galaxy/rebuild"), ("POST", "/api/reports/from-session"),
    ("PUT", "/api/users/me/preferences"), ("POST", "/api/auth/register"),
    ("POST", "/api/graph/vpc/a/b/dependency-chain"), ("post", "/api/scan"),
])
def test_every_other_write_is_refused(method, path):
    assert not viewer_may(method, path)


# ── the middleware, over every real route ─────────────────────────────────────


@pytest.fixture
def gate(tmp_path, monkeypatch):
    """APIAuthMiddleware in front of a stub that answers "passed" — the middleware alone decides, no handler runs."""
    from starlette.applications import Starlette
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route

    from agenticops.auth.service import AuthService
    from agenticops.web.app import APIAuthMiddleware

    settings = _temp_db(tmp_path, monkeypatch)
    monkeypatch.setattr(settings, "webhook_secret", "")
    monkeypatch.setattr(settings, "change_intake_secret", "")

    async def passed(_request):
        return PlainTextResponse("passed")

    inner = Starlette(routes=[Route("/{p:path}", passed, methods=["GET", "POST", "PUT", "PATCH", "DELETE"])])
    inner.add_middleware(APIAuthMiddleware)
    tokens = {}
    for name, kwargs in (("viewer", {"permissions": ["read"]}), ("writer", {}), ("admin", {"is_admin": True})):
        user = AuthService.create_user(email=name, password="pw-not-a-secret", **kwargs)
        tokens[name] = {"Authorization": f"Bearer {AuthService.create_session(user.id)}"}
        if name == "admin":
            tokens["admin_read_key"] = {"Authorization": f"Bearer {AuthService.create_api_key(user.id, 'k')}"}
    return SimpleNamespace(client=TestClient(inner), tokens=tokens)


def _mutating_api_routes():
    from agenticops.web.app import app
    out = []
    for r in app.routes:
        for m in sorted((getattr(r, "methods", None) or set()) & {"POST", "PUT", "PATCH", "DELETE"}):
            if r.path.startswith("/api/"):
                out.append((m, r.path, re.sub(r"\{[^}]+\}", "x1", r.path)))
    return out


def test_the_walk_covers_the_app_and_every_allowlist_entry_is_a_real_route():
    routes = _mutating_api_routes()
    assert len(routes) > 100
    allowed = {(m, concrete) for m, _p, concrete in routes if viewer_may(m, concrete)}
    assert allowed == {
        ("POST", "/api/auth/logout"), ("PUT", "/api/users/me/password"), ("PATCH", "/api/users/me/preferences"),
        ("POST", "/api/chat/sessions"), ("PATCH", "/api/chat/sessions/x1"), ("DELETE", "/api/chat/sessions/x1"),
        ("POST", "/api/chat/sessions/x1/messages"), ("POST", "/api/graph/vpc/x1/dependency-chain"),
        ("POST", "/api/graph/vpc/x1/change-simulation"),
    }


def test_a_viewer_is_refused_every_write_outside_the_allowlist(gate):
    from agenticops.web.app import _PUBLIC_PATHS  # sign-in itself: no identity yet, nothing to gate
    refused = 0
    for method, template, path in _mutating_api_routes():
        r = gate.client.request(method, path, headers=gate.tokens["viewer"])
        if viewer_may(method, path) or path in _PUBLIC_PATHS:
            assert (r.status_code, r.text) == (200, "passed"), (method, template)
        else:
            assert (r.status_code, r.json()) == (403, READ_ONLY_BODY), (method, template)
            refused += 1
    assert refused > 100


@pytest.mark.parametrize("who", ["writer", "admin", "admin_read_key"])
def test_writers_admins_and_api_keys_are_never_stopped_by_it(gate, who):
    """API-key scope semantics are unchanged: an admin's read-scoped key passes the middleware as before."""
    for method, template, path in _mutating_api_routes():
        r = gate.client.request(method, path, headers=gate.tokens[who])
        assert (r.status_code, r.text) == (200, "passed"), (who, method, template)


def test_a_viewer_still_reads(gate):
    for path in ("/api/settings", "/api/health-issues", "/api/chat/sessions", "/api/ui/bootstrap"):
        assert gate.client.get(path, headers=gate.tokens["viewer"]).text == "passed"


def test_self_registration_is_not_public_any_more(gate):
    r = gate.client.post("/api/auth/register", json={"email": "x", "password": "y"})
    assert r.status_code == 401 and r.json()["detail"].startswith("Authentication required")


# ── chat ──────────────────────────────────────────────────────────────────────

VIEWER = Actor("user", "viewer", 9, ("read",), read_only=True)
ALICE = Actor("user", "alice@example.com", 1, ("read", "write"))


@pytest.fixture
def chat(tmp_path, monkeypatch):
    from agenticops.web import deps
    from agenticops.web.app import app
    settings = _temp_db(tmp_path, monkeypatch, "chat.db")
    monkeypatch.setattr(settings, "api_auth_enabled", True)
    who = {"actor": VIEWER}
    app.dependency_overrides[deps.current_actor] = lambda: who["actor"]
    client = TestClient(app)  # bare — no `with`, so the lifespan never starts

    def as_(actor):
        who["actor"] = actor
        return client
    yield SimpleNamespace(client=client, as_=as_)
    app.dependency_overrides.pop(deps.current_actor, None)


def _workspace_session() -> str:
    """An ownerless session (legacy / IM / CLI): everyone sees it."""
    sid = str(uuid.uuid4())
    s = get_session()
    try:
        s.add(ChatSession(session_id=sid, name="shared", visibility="workspace"))
        s.commit()
    finally:
        s.close()
    return sid


def _send(client, sid, content):
    return client.post(f"/api/chat/sessions/{sid}/messages",
                       json={"content": content, "client_message_id": str(uuid.uuid4())})


def test_a_viewer_chats_in_its_own_session_on_the_read_only_agent(chat, monkeypatch):
    import agenticops.web.app as webapp
    r = chat.as_(VIEWER).post("/api/chat/sessions", json={"name": "demo"})
    assert r.status_code == 201 and r.json()["owned_by_me"] is True
    sid = r.json()["session_id"]
    seen = {}

    class _Agent:
        async def stream_async(self, _content):
            seen["read_only_ctx"] = get_run_context().read_only
            yield {"data": "ok"}

    def get_or_create(session_id, read_only=False):
        seen["read_only_arg"] = read_only
        return _Agent()

    monkeypatch.setattr(webapp._chat_sessions, "get_or_create", get_or_create)
    assert _send(chat.client, sid, "list open issues").status_code == 200
    assert seen == {"read_only_arg": True, "read_only_ctx": True}
    assert chat.client.patch(f"/api/chat/sessions/{sid}", json={"name": "renamed"}).status_code == 200
    assert chat.client.delete(f"/api/chat/sessions/{sid}").status_code in (200, 204)


def test_a_viewer_writes_nothing_into_a_workspace_session(chat, monkeypatch):
    import agenticops.web.app as webapp
    sid = _workspace_session()
    monkeypatch.setattr(webapp._chat_sessions, "get_or_create", Mock(side_effect=AssertionError("no agent")))
    viewer = chat.as_(VIEWER)
    assert viewer.get(f"/api/chat/sessions/{sid}").status_code == 200          # reading it is fine
    r = _send(viewer, sid, "hi")
    assert (r.status_code, r.json()) == (403, READ_ONLY_BODY)
    assert viewer.patch(f"/api/chat/sessions/{sid}", json={"name": "mine"}).status_code == 403
    assert viewer.delete(f"/api/chat/sessions/{sid}").status_code == 403
    assert chat.as_(ALICE).patch(f"/api/chat/sessions/{sid}", json={"name": "ok"}).status_code == 200  # as before


@pytest.mark.parametrize("command", ["/channel list", "/channels", "/send_to ops R#1", "/sendto ops hi"])
def test_a_viewer_runs_no_channel_or_send_to_command(chat, command):
    sid = chat.as_(VIEWER).post("/api/chat/sessions", json={"name": "demo"}).json()["session_id"]
    with patch("agenticops.chat.channel.execute_channel", side_effect=AssertionError("ran")), \
         patch("agenticops.chat.send_to.execute_send_to", side_effect=AssertionError("ran")):
        r = _send(chat.client, sid, command)
    assert (r.status_code, r.json()) == (403, READ_ONLY_BODY)


def test_a_viewer_turn_never_runs_on_a_full_agent_and_back(tmp_path, monkeypatch):
    from agenticops.web import session_manager as sm
    _temp_db(tmp_path, monkeypatch, "cache.db")
    built = []

    def fake_create(**kw):
        agent = MagicMock()
        agent.messages = []
        built.append(kw.get("read_only", False))
        return agent

    monkeypatch.setattr(sm, "create_main_agent", fake_create)
    mgr = sm.ChatSessionManager()
    full = mgr.get_or_create("s1")                       # e.g. an admin posted into the viewer's session first
    assert mgr.get_or_create("s1") is full
    ro = mgr.get_or_create("s1", read_only=True)
    assert ro is not full and ro._aiops_read_only is True
    assert mgr.get_or_create("s1", read_only=True) is ro
    again = mgr.get_or_create("s1")
    assert again is not ro and again._aiops_read_only is False
    assert built == [False, True, False]


# ── the read-only agent ───────────────────────────────────────────────────────

READ_ONLY_TOOLS = {
    "get_active_account", "get_managed_resources", "get_health_issue", "get_resource_by_id", "get_rca_result",
    "get_fix_plan", "get_plan", "get_execution_result", "list_health_issues",
    "detect_network_anomalies", "analyze_network_segments", "detect_single_points_of_failure", "analyze_capacity_risk",
    "list_skills", "read_skill_reference", "list_monitoring_providers", "search_agent_memory",
    "list_schedules", "get_schedule_history", "list_cloud_accounts", "run_aws_cli_readonly", "run_kubectl",
}


def _build_read_only(change_management: bool):
    from agenticops.agents.main_agent import create_main_agent
    from agenticops.config import settings
    with patch.object(settings, "change_management_enabled", change_management), \
         patch("agenticops.agents.main_agent.Agent") as MockAgent, \
         patch("agenticops.agents.main_agent.BedrockModel"), \
         patch("agenticops.agents.main_agent.build_system_prompt", side_effect=lambda p, **kw: (p, kw)), \
         patch("agenticops.config.get_bedrock_boto_session", return_value=MagicMock()), \
         patch("agenticops.agents.main_agent._safe_mcp_clients") as mcp, \
         patch("agenticops.memory.curator.maybe_run_curator") as curator, \
         patch("agenticops.skills.curator.maybe_run_skills_curator") as skills_curator:
        create_main_agent(read_only=True)
    assert not (mcp.called or curator.called or skills_curator.called)
    kw = MockAgent.call_args.kwargs
    names = {getattr(t, "tool_name", None) or getattr(t, "__name__", str(t)) for t in kw["tools"]}
    return kw["system_prompt"], names


@pytest.mark.parametrize("change_management", [True, False])
def test_the_read_only_agent_has_exactly_the_allowlisted_tools(change_management):
    (prompt, prompt_kw), names = _build_read_only(change_management)
    change_reads = {"get_change_request", "list_change_requests"} if change_management else set()
    assert names == READ_ONLY_TOOLS | change_reads
    assert prompt_kw == {"include_account": False, "include_skills": False}   # no skills protocol, no memory
    for absent in ("scan_agent", "detect_agent", "rca_agent", "sre_agent", "sre_query", "executor_agent",
                   "reporter_agent", "activate_skill", "approve_fix_plan", "request_change", "review_change",
                   "execute_change", "create_health_issue", "update_health_issue_status", "run_task",
                   "skill_manage", "memory_manage", "share_content", "run_aws_cli", "run_on_host"):
        assert not re.search(rf"\b{absent}\b", prompt), absent
    assert "<<SUGGEST>>" in prompt


# ── the command layer ─────────────────────────────────────────────────────────


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    settings = _temp_db(tmp_path, monkeypatch, "cmd.db")
    monkeypatch.setattr(settings, "command_audit_enabled", True)
    s = get_session()
    yield s
    s.close()


def _rows(db):
    db.expire_all()
    return [(r.tool, r.outcome, r.reason) for r in db.query(CommandAudit).order_by(CommandAudit.id)]


def test_aws_cli_write_is_refused_even_when_confirmed(ledger):
    from agenticops.tools.aws_cli_tool import run_aws_cli
    with run_context(read_only=True), patch("agenticops.tools.aws_cli_tool._execute_aws_cli") as ex:
        out = run_aws_cli(command="aws ec2 stop-instances --instance-ids i-1", require_confirmation=True)
    assert "read-only" in out and not ex.called
    assert _rows(ledger) == [("run_aws_cli", "refused", "read_only_account")]


def test_run_on_host_write_is_refused(ledger):
    from agenticops.skills.execution import run_on_host
    with run_context(read_only=True), patch("agenticops.skills.execution._run_auto_ladder") as ladder:
        out = run_on_host(host_id="i-1", command="kill -9 1234", require_confirmation=True)
    assert "read-only" in out and not ladder.called
    assert _rows(ledger) == [("run_on_host", "refused", "read_only_account")]


@pytest.mark.parametrize("command", [
    "scale deployment/x --replicas=2", "delete pod x", "exec -it x -- sh",
    "get secret db -o yaml", "get secrets", "describe secret/db", "config view --raw",
])
def test_kubectl_writes_and_secret_reads_are_refused(ledger, command):
    from agenticops.skills.execution import run_kubectl
    with run_context(read_only=True), patch("agenticops.skills.execution._execute_kubectl") as ex:
        out = run_kubectl(cluster_name="c1", command=command, namespace="prod", require_confirmation=True)
    assert "read-only" in out and not ex.called
    assert _rows(ledger) == [("run_kubectl", "refused", "read_only_account")]


@pytest.mark.parametrize("command", ["get pods", "logs deploy/web --tail=50", "get configmap app-secretary"])
def test_kubectl_reads_still_run(ledger, command):
    from agenticops.skills.execution import run_kubectl
    with run_context(read_only=True), patch("agenticops.skills.execution._execute_kubectl", return_value="OK") as ex:
        assert run_kubectl(cluster_name="c1", command=command) == "OK"
    assert ex.called and _rows(ledger) == []


def test_provider_cli_tools_refuse_too(ledger):
    from agenticops.services.command_audit import guarded_run
    run = Mock(return_value="ok")
    with run_context(read_only=True):
        out = guarded_run(tool="provider_aws_cli", tier="write", command="aws ec2 delete-vpc --vpc-id vpc-1",
                          run=run, outcome_of=lambda t: ("executed", 0))
    assert "read-only" in out and not run.called
    assert _rows(ledger) == [("provider_aws_cli", "refused", "read_only_account")]


def test_outside_a_viewer_turn_nothing_changes(ledger):
    from agenticops.tools.aws_cli_tool import run_aws_cli
    with patch("agenticops.tools.aws_cli_tool._execute_aws_cli", return_value="ok") as ex:
        assert run_aws_cli(command="aws ec2 create-tags --resources i-1 --tags Key=a,Value=b",
                           require_confirmation=True) == "ok"
    assert ex.called and _rows(ledger) == [("run_aws_cli", "executed", None)]


# ── actor, available actions ──────────────────────────────────────────────────


def test_the_read_only_flag_comes_from_the_users_row_and_travels_in_the_run_context():
    from agenticops.auth.actor import actor_from_request, actor_from_run_context
    viewer = SimpleNamespace(id=9, email="viewer", permissions=["read"])
    writer = SimpleNamespace(id=1, email="w", permissions=["read", "write"])
    assert actor_from_request(SimpleNamespace(state=SimpleNamespace(user=viewer))).read_only is True
    key = SimpleNamespace(permissions=["read"])  # a read-scoped key does not make a writer a viewer
    assert actor_from_request(SimpleNamespace(state=SimpleNamespace(user=writer, api_key=key))).read_only is False
    with run_context(actor="user:viewer", actor_user_id=9, actor_permissions=("read",), read_only=True):
        assert actor_from_run_context(get_run_context()).read_only is True


def test_available_actions_offer_a_viewer_nothing():
    from agenticops.services.ui_actions import route_allows
    for permission in ("plan.approve", "plan.execute", "change.approve", "issue.note"):
        assert route_allows(VIEWER, permission, None) == (False, "read_only")


# ── self-registration, `aiops users` ──────────────────────────────────────────


def test_the_register_endpoint_is_gone():
    from agenticops.web import schemas
    from agenticops.web.app import _PUBLIC_PATHS, app
    assert "/api/auth/register" not in _PUBLIC_PATHS
    assert not [r for r in app.routes if getattr(r, "path", "") == "/api/auth/register"]
    assert not hasattr(schemas, "RegisterRequest")


def test_aiops_users_create_list_disable(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from agenticops.auth.models import User
    from agenticops.auth.service import AuthService
    from agenticops.cli.main import app
    _temp_db(tmp_path, monkeypatch, "users.db")
    runner = CliRunner()
    r = runner.invoke(app, ["users", "create", "viewer", "--viewer", "--display-name", "Demo"])
    assert r.exit_code == 0, r.output
    password = re.search(r"Password \(shown once\): (\S+)", r.output).group(1)
    assert AuthService.authenticate("viewer", password) is not None
    with __import__("agenticops.models", fromlist=["get_db_session"]).get_db_session() as db:
        u = db.query(User).filter_by(email="viewer").one()
        assert (u.permissions, u.is_admin, u.name) == (["read"], False, "Demo")
    assert runner.invoke(app, ["users", "create", "viewer"]).exit_code == 1        # a duplicate is refused
    assert runner.invoke(app, ["users", "create", "x", "--viewer", "--admin"]).exit_code == 2
    out = runner.invoke(app, ["users", "list"]).output
    assert "viewer" in out and "Demo" in out
    token = AuthService.create_session(AuthService.authenticate("viewer", password).id)
    assert runner.invoke(app, ["users", "disable", "viewer"]).exit_code == 0
    assert AuthService.validate_session(token) is None                              # its session stops at once
    assert AuthService.authenticate("viewer", password) is None
    assert runner.invoke(app, ["users", "disable", "nobody"]).exit_code == 1
