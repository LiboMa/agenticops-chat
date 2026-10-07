"""Who may see a report (MVP-2.7.0 S6): a report saved from a private chat is its creator's (and admins'); every
other report is the workspace's. Every report route applies it; an invisible report reads like a missing one."""
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from starlette.testclient import TestClient

from agenticops.auth.actor import Actor
from agenticops.models import Base, ChatMessage, ChatSession, Report, get_session

ALICE = Actor("user", "alice@example.com", 1, ("read", "write"))
BOB = Actor("user", "bob@example.com", 2, ("read", "write"))
ADMIN = Actor("user", "admin@example.com", 3, ("read", "write", "admin"))


@pytest.fixture
def env(tmp_path, monkeypatch):
    import agenticops.models as models_mod
    import agenticops.audit.models  # noqa: F401
    from agenticops.config import settings
    from agenticops.web import deps
    from agenticops.web.app import app
    monkeypatch.setattr(models_mod, "_engine", None)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/rep.db")
    monkeypatch.setattr(settings, "api_auth_enabled", True)
    monkeypatch.setattr(settings, "rbac_enforce", False)
    Base.metadata.create_all(models_mod.get_engine())
    who = {"actor": ALICE}
    app.dependency_overrides[deps.current_actor] = lambda: who["actor"]
    client = TestClient(app)

    def as_(actor):
        who["actor"] = actor
        return client
    yield SimpleNamespace(as_=as_)
    app.dependency_overrides.pop(deps.current_actor, None)


def _chat(owner, visibility):
    s = get_session()
    try:
        now = datetime.now(timezone.utc)
        row = ChatSession(session_id=str(uuid.uuid4()), name="c", owner_user_id=owner, visibility=visibility,
                          created_at=now, updated_at=now, last_activity_at=now)
        s.add(row); s.flush()
        s.add_all([ChatMessage(session_id=row.id, role="user", content="what broke?"),
                   ChatMessage(session_id=row.id, role="assistant", content="nginx ran out of workers")])
        s.commit()
        return row.session_id
    finally:
        s.close()


def _workspace_report():
    s = get_session()
    try:
        r = Report(report_type="daily", title="daily", summary="s", content_markdown="all fine today")
        s.add(r); s.commit()
        return r.id
    finally:
        s.close()


def _private_report(env):
    sid = _chat(owner=1, visibility="private")
    r = env.as_(ALICE).post("/api/reports/from-session", json={"session_id": sid})
    assert r.status_code == 201, r.text
    return r.json()


def test_a_report_saved_from_a_private_chat_is_private_to_its_creator(env):
    rep = _private_report(env)
    assert rep["visibility"] == "private" and rep["owned_by_me"] is True
    assert env.as_(ALICE).get(f"/api/reports/{rep['id']}").json()["owned_by_me"] is True


def test_a_report_from_a_workspace_chat_is_workspace(env):
    sid = _chat(owner=None, visibility="workspace")
    rep = env.as_(BOB).post("/api/reports/from-session", json={"session_id": sid}).json()
    assert rep["visibility"] == "workspace"


def test_every_report_route_hides_a_private_report(env):
    rid = _private_report(env)["id"]
    bob = env.as_(BOB)
    assert rid not in [r["id"] for r in bob.get("/api/reports").json()]
    assert bob.get(f"/api/reports/{rid}").status_code == 404
    assert bob.post(f"/api/reports/{rid}/publish", json={"channel_name": "x", "formats": ["html"]}).status_code == 404


def test_rendering_routes_hide_a_private_report(env):
    rid = _private_report(env)["id"]
    assert env.as_(ALICE).get(f"/api/content/report/{rid}/rendering?version=1&language=en").status_code == 200
    bob = env.as_(BOB)
    assert bob.get(f"/api/content/report/{rid}/rendering?version=1&language=en").status_code == 404
    assert bob.post(f"/api/content/report/{rid}/translations", json={"source_version": 1, "languages": ["zh"]}).status_code == 404


def test_export_hides_a_private_report(env):
    rid = _private_report(env)["id"]
    assert env.as_(ALICE).get(f"/api/reports/{rid}/export?version=1&language=en").status_code == 200
    assert env.as_(BOB).get(f"/api/reports/{rid}/export?version=1&language=en").status_code == 404


def test_admin_sees_private_reports(env):
    rid = _private_report(env)["id"]
    assert env.as_(ADMIN).get(f"/api/reports/{rid}").status_code == 200
    assert rid in [r["id"] for r in env.as_(ADMIN).get("/api/reports").json()]


def test_workspace_reports_are_visible_to_all(env):
    rid = _workspace_report()
    assert env.as_(BOB).get(f"/api/reports/{rid}").json()["visibility"] == "workspace"
    assert rid in [r["id"] for r in env.as_(BOB).get("/api/reports").json()]
