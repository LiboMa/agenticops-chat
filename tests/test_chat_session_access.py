# tests/test_chat_session_access.py
"""Who may see a chat session (MVP-2.7.0 S1b).

A session a logged-in user creates is theirs and private; legacy rows and sessions made without an owner
(auth off, IM, CLI) are workspace sessions everyone sees. A session the caller may not see is a 404 on every
route — list, read, history, send, update, delete, save-as-report — and nothing runs for it first."""
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import event
from starlette.testclient import TestClient

from agenticops.auth.actor import Actor
from agenticops.models import Base, ChatMessage, ChatSession, SessionSummary, get_session

ALICE = Actor("user", "alice@example.com", 1, ("read", "write"))
BOB = Actor("user", "bob@example.com", 2, ("read", "write"))
ADMIN = Actor("user", "admin@example.com", 3, ("read", "write", "admin"))


@pytest.fixture
def env(tmp_path, monkeypatch):
    import agenticops.models as models_mod
    from agenticops.config import settings
    from agenticops.web import deps
    from agenticops.web.app import app
    monkeypatch.setattr(models_mod, "_engine", None)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/chat.db")
    monkeypatch.setattr(settings, "api_auth_enabled", True)
    monkeypatch.setattr(settings, "rbac_enforce", False)
    Base.metadata.create_all(models_mod.get_engine())
    who = {"actor": ALICE}
    app.dependency_overrides[deps.current_actor] = lambda: who["actor"]
    client = TestClient(app)  # bare — no `with`, so the lifespan never starts

    def as_(actor):
        who["actor"] = actor
        return client
    yield SimpleNamespace(client=client, as_=as_, settings=settings, engine=models_mod.get_engine())
    app.dependency_overrides.pop(deps.current_actor, None)


def _new(env, actor, name="s"):
    r = env.as_(actor).post("/api/chat/sessions", json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()


def _add_message(sid, content="hello"):
    s = get_session()
    try:
        row = s.query(ChatSession).filter_by(session_id=sid).one()
        s.add(ChatMessage(session_id=row.id, role="user", content=content))
        s.commit()
        return row.id
    finally:
        s.close()


def test_a_logged_in_users_new_session_is_theirs_and_private(env):
    body = _new(env, ALICE)
    assert (body["visibility"], body["owned_by_me"]) == ("private", True)
    s = get_session()
    try:
        assert s.query(ChatSession).filter_by(session_id=body["session_id"]).one().owner_user_id == ALICE.user_id
    finally:
        s.close()


def test_a_private_session_is_a_404_on_every_route_for_someone_else(env):
    sid = _new(env, ALICE)["session_id"]
    _add_message(sid)
    bob = env.as_(BOB)
    assert sid not in [x["session_id"] for x in bob.get("/api/chat/sessions").json()]
    assert bob.get(f"/api/chat/sessions/{sid}").status_code == 404
    assert bob.get(f"/api/chat/sessions/{sid}/messages").status_code == 404
    assert bob.post(f"/api/chat/sessions/{sid}/messages", json={"content": "hi"}).status_code == 404
    assert bob.patch(f"/api/chat/sessions/{sid}", json={"name": "mine now"}).status_code == 404
    assert bob.delete(f"/api/chat/sessions/{sid}").status_code == 404
    assert bob.post("/api/reports/from-session", json={"session_id": sid}).status_code == 404
    # the 404 says the same as for a session that does not exist
    assert bob.get(f"/api/chat/sessions/{sid}").json() == bob.get("/api/chat/sessions/nope").json()
    # and the owner still has it
    assert env.as_(ALICE).get(f"/api/chat/sessions/{sid}").status_code == 200


def test_an_admin_sees_every_session(env):
    sid = _new(env, ALICE)["session_id"]
    admin = env.as_(ADMIN)
    assert sid in [x["session_id"] for x in admin.get("/api/chat/sessions").json()]
    body = admin.get(f"/api/chat/sessions/{sid}").json()
    assert (body["visibility"], body["owned_by_me"]) == ("private", False)


def test_a_workspace_session_is_everyones(env):
    sid = _new(env, ALICE)["session_id"]
    r = env.as_(ALICE).patch(f"/api/chat/sessions/{sid}", json={"visibility": "workspace"})
    assert r.status_code == 200 and r.json()["visibility"] == "workspace"
    bob = env.as_(BOB)
    assert sid in [x["session_id"] for x in bob.get("/api/chat/sessions").json()]
    assert bob.get(f"/api/chat/sessions/{sid}").json()["owned_by_me"] is False
    assert bob.patch(f"/api/chat/sessions/{sid}", json={"name": "renamed"}).status_code == 200


def test_only_the_owner_or_an_admin_changes_who_sees_a_session(env):
    sid = _new(env, ALICE)["session_id"]
    env.as_(ALICE).patch(f"/api/chat/sessions/{sid}", json={"visibility": "workspace"})
    assert env.as_(BOB).patch(f"/api/chat/sessions/{sid}", json={"visibility": "private"}).status_code == 403
    assert env.as_(ADMIN).patch(f"/api/chat/sessions/{sid}", json={"visibility": "private"}).status_code == 200
    assert env.as_(BOB).get(f"/api/chat/sessions/{sid}").status_code == 404
    assert env.as_(ALICE).patch(f"/api/chat/sessions/{sid}", json={"visibility": "secret"}).status_code == 422


def test_a_session_with_no_owner_cannot_become_private(env):
    s = get_session()
    s.add(ChatSession(session_id="legacy-1", name="old"))  # a pre-2.7.0 row: no owner, workspace
    s.commit(); s.close()
    r = env.as_(ADMIN).patch("/api/chat/sessions/legacy-1", json={"visibility": "private"})
    assert r.status_code == 409
    assert env.as_(BOB).get("/api/chat/sessions/legacy-1").json()["visibility"] == "workspace"


def test_streaming_does_not_reveal_an_invisible_session(env):
    from agenticops.web import app as app_mod
    sid = _new(env, ALICE)["session_id"]
    app_mod._streaming_sessions.add(sid)
    try:
        assert env.as_(BOB).patch(f"/api/chat/sessions/{sid}", json={"effort": "deep"}).status_code == 404
        assert env.as_(ALICE).patch(f"/api/chat/sessions/{sid}", json={"effort": "deep"}).status_code == 409
    finally:
        app_mod._streaming_sessions.discard(sid)


def test_send_to_never_runs_for_a_session_the_caller_cannot_see(env):
    sid = _new(env, ALICE)["session_id"]
    sent = SimpleNamespace(message="sent")
    with patch("agenticops.chat.send_to.execute_send_to", return_value=sent) as run:
        assert env.as_(BOB).post(f"/api/chat/sessions/{sid}/messages",
                                 json={"content": "/send_to ops hello"}).status_code == 404
        assert env.as_(BOB).post("/api/chat/sessions/does-not-exist/messages",
                                 json={"content": "/send_to ops hello"}).status_code == 404
        run.assert_not_called()
        r = env.as_(ALICE).post(f"/api/chat/sessions/{sid}/messages", json={"content": "/send_to ops hello"})
        assert r.status_code == 200
        run.assert_called_once()


def test_delete_removes_the_sessions_summaries(env):
    sid = _new(env, ALICE)["session_id"]
    pk = _add_message(sid)
    s = get_session()
    s.add(SessionSummary(session_id=pk, summary_text="secret summary", message_range_start=1, message_range_end=1))
    s.commit(); s.close()
    assert env.as_(ALICE).delete(f"/api/chat/sessions/{sid}").status_code == 204
    s = get_session()
    try:
        assert s.query(SessionSummary).filter_by(session_id=pk).count() == 0
    finally:
        s.close()


def test_the_list_counts_messages_in_one_query(env):
    for i in range(6):
        _add_message(_new(env, ALICE, name=f"s{i}")["session_id"])
    statements = []
    listener = lambda *a: statements.append(a[2])  # noqa: E731 — (conn, cursor, statement, ...)
    event.listen(env.engine, "before_cursor_execute", listener)
    try:
        rows = env.as_(ALICE).get("/api/chat/sessions").json()
    finally:
        event.remove(env.engine, "before_cursor_execute", listener)
    assert [r["message_count"] for r in rows] == [1] * 6
    assert len([q for q in statements if "chat_messages" in q]) == 1


def test_with_auth_off_every_session_is_visible_and_new_ones_have_no_owner(env, monkeypatch):
    sid = _new(env, ALICE)["session_id"]  # made private while auth was on
    monkeypatch.setattr(env.settings, "api_auth_enabled", False)
    anon = env.as_(Actor("web", "anonymous"))
    assert anon.get(f"/api/chat/sessions/{sid}").status_code == 200
    assert sid in [x["session_id"] for x in anon.get("/api/chat/sessions").json()]
    body = _new(env, Actor("web", "anonymous"))
    assert (body["visibility"], body["owned_by_me"]) == ("workspace", False)


def test_an_api_key_caller_resolves_to_an_actor(tmp_path, monkeypatch):
    """PARK-S5: validate_api_key returned a User expired by its session's commit, so reading its
    permissions (actor_from_request) raised DetachedInstanceError — a 500 on any route that names the actor."""
    import agenticops.models as models_mod
    from agenticops.auth.actor import actor_from_request
    from agenticops.auth.service import AuthService
    from agenticops.config import settings
    monkeypatch.setattr(models_mod, "_engine", None)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/keys.db")
    import agenticops.auth.models  # noqa: F401
    Base.metadata.create_all(models_mod.get_engine())
    user = AuthService.create_user("carol@example.com", "pw")
    key = AuthService.create_api_key(user.id, "ci", permissions=["read"])
    found_user, found_key = AuthService.validate_api_key(key)
    actor = actor_from_request(SimpleNamespace(state=SimpleNamespace(user=found_user, api_key=found_key)))
    assert (actor.key, actor.user_id) == ("user:carol@example.com", found_user.id)
    assert "read" in actor.permissions


def test_the_2_7_0_migration_makes_every_existing_session_a_workspace_session(tmp_path):
    from sqlalchemy import create_engine, inspect, text
    import agenticops.models as models_mod
    engine = create_engine(f"sqlite:///{tmp_path}/legacy.db")
    with engine.begin() as c:
        c.execute(text("CREATE TABLE chat_sessions (id INTEGER PRIMARY KEY, session_id VARCHAR(36), name VARCHAR(200))"))
        c.execute(text("INSERT INTO chat_sessions (session_id, name) VALUES ('old', 'old')"))
    models_mod._run_migrate_2_7_0(engine)
    cols = {c["name"] for c in inspect(engine).get_columns("chat_sessions")}
    assert {"owner_user_id", "visibility"} <= cols
    with engine.connect() as c:
        assert c.execute(text("SELECT owner_user_id, visibility FROM chat_sessions")).one() == (None, "workspace")
    assert models_mod._statements_2_7_0(inspect(engine), engine.dialect) == []  # idempotent


def test_the_2_7_0_migration_ddl_on_postgresql():
    from sqlalchemy.dialects import postgresql
    import agenticops.models as models_mod
    insp = SimpleNamespace(has_table=lambda t: t == "chat_sessions",
                           get_columns=lambda t: [{"name": "id"}, {"name": "session_id"}])
    assert models_mod._statements_2_7_0(insp, postgresql.dialect()) == [
        "ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS owner_user_id INTEGER",
        "ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS visibility VARCHAR(16) NOT NULL DEFAULT 'workspace'",
    ]


def test_registration_answers_with_the_new_user(tmp_path, monkeypatch):
    """create_user returned a User expired by its session's commit: POST /api/auth/register answered every
    registration with a DetachedInstanceError (as a 400) — the owner could not create the users S1 needs."""
    import agenticops.models as models_mod
    from agenticops.config import settings
    from agenticops.web.app import app
    monkeypatch.setattr(models_mod, "_engine", None)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/reg.db")
    r = TestClient(app).post("/api/auth/register", json={"email": "dave@example.com", "password": "pw-123456"})
    assert r.status_code == 201, r.text
    assert r.json()["email"] == "dave@example.com"
