"""Deleting a user (MVP-2.8.0, owner 2026-11-10: «Admin user可以删除用户»).

A delete is soft: the row stays with `deleted_at` set, so
- the login name is never given to anyone else (the unique email; records name people by `user:<email>`),
- private chats and reports keep pointing at a row nobody else can ever get,
- and no sign-in path (password, session, API key) accepts the user again, even if `is_active` were flipped back.
Real users, sessions and keys on a temp DB, the HTTP layer through the app (imported before sign-in is turned on)."""
from datetime import datetime, timezone
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
    from agenticops.web.app import app
    monkeypatch.setattr(models_mod, "_engine", None)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/del.db")
    monkeypatch.setattr(settings, "api_auth_enabled", True)
    Base.metadata.create_all(models_mod.get_engine())
    return SimpleNamespace(client=TestClient(app), settings=settings)


def _user(email, role="writer"):
    from agenticops.auth import AuthService
    is_admin, perms = grants(role)
    user = AuthService.create_user(email=email, password=f"pw-{email}-0", is_admin=is_admin, permissions=perms)
    return user, AuthService.create_session(user.id)


def H(token):
    return {"Authorization": f"Bearer {token}"}


# ── T1: the marker and the sign-in gates ────────────────────────────────────────────────────────────────────


def test_the_migration_adds_users_deleted_at_once(tmp_path):
    from sqlalchemy import create_engine, inspect, text
    import agenticops.auth.models  # noqa: F401  (users in the metadata the DDL is built from)
    import agenticops.models as models_mod
    engine = create_engine(f"sqlite:///{tmp_path}/legacy.db")
    with engine.begin() as c:
        c.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, email VARCHAR(255) UNIQUE, password_hash VARCHAR(255),"
                       " is_admin BOOLEAN, is_active BOOLEAN, permissions JSON)"))
        c.execute(text("INSERT INTO users (email, password_hash, is_admin, is_active, permissions) "
                       "VALUES ('old', 'x', 0, 1, '[\"read\"]')"))
    models_mod._run_migrate_2_7_0(engine)
    assert "deleted_at" in {c["name"] for c in inspect(engine).get_columns("users")}
    with engine.connect() as c:
        assert c.execute(text("SELECT deleted_at FROM users")).one() == (None,)
    assert models_mod._statements_2_7_0(inspect(engine), engine.dialect) == []   # once


def test_a_deleted_user_never_signs_in_even_if_reactivated_by_hand(env):
    from agenticops.auth import AuthService
    from agenticops.auth.models import User
    from agenticops.models import get_db_session
    ops, session = _user("ops")
    key = AuthService.create_api_key(user_id=ops.id, name="k", permissions=["read"])
    assert AuthService.authenticate("ops", "pw-ops-0") is not None and AuthService.validate_session(session) is not None
    with get_db_session() as s:   # deleted, then is_active flipped back by hand: still nothing gets in
        u = s.query(User).filter_by(id=ops.id).one()
        u.deleted_at = datetime.now(timezone.utc)
        u.is_active = True
    assert AuthService.authenticate("ops", "pw-ops-0") is None
    assert AuthService.validate_session(session) is None
    assert AuthService.validate_api_key(key) is None
    assert env.client.get("/api/users/me", headers=H(session)).status_code == 401


# ── T2: an admin deletes a user ─────────────────────────────────────────────────────────────────────────────


def _sessions(user_id):
    from agenticops.auth.models import Session
    from agenticops.models import get_db_session
    with get_db_session() as s:
        return s.query(Session).filter_by(user_id=user_id).count()


def _staged(owner_key, att_id, session_id=None):
    from agenticops.chat.attachments import store
    from agenticops.models import ChatAttachment, get_db_session
    with get_db_session() as s:
        s.add(ChatAttachment(id=att_id, owner_key=owner_key, session_id=session_id, filename="a.txt", ext=".txt",
                             kind="text", size=1, status="ready"))
    d = store.staging_dir(att_id)
    d.mkdir(parents=True, exist_ok=True)
    (d / "original").write_text("x")
    return d


def _attachment(att_id):
    from agenticops.models import ChatAttachment, get_db_session
    with get_db_session() as s:
        return s.get(ChatAttachment, att_id) is not None


def _change(requested_by, status):
    from agenticops.models import ChangeRequest, get_db_session
    with get_db_session() as s:
        cr = ChangeRequest(title="t", description="d", requested_by=requested_by, status=status)
        s.add(cr)
        s.flush()
        return cr.id


def test_delete_ends_sessions_keys_and_staged_uploads(env, tmp_path, monkeypatch):
    from agenticops.auth import AuthService
    monkeypatch.setattr(env.settings, "chat_attachments_dir", str(tmp_path / "att"))
    _, root = _user("root", "admin")
    ops, ops_session = _user("ops")
    key = AuthService.create_api_key(user_id=ops.id, name="k", permissions=["read"])
    mine = _staged("user:ops", "a" * 32)
    other = _staged("user:root", "b" * 32)
    r = env.client.delete(f"/api/users/{ops.id}", headers=H(root))
    assert r.status_code == 204, r.text
    assert _sessions(ops.id) == 0 and AuthService.validate_api_key(key) is None
    assert not _attachment("a" * 32) and not mine.exists()
    assert _attachment("b" * 32) and other.exists()                 # someone else's upload is untouched


def test_a_deleted_user_leaves_every_admin_view(env):
    _, root = _user("root", "admin")
    ops, _ = _user("ops")
    assert env.client.delete(f"/api/users/{ops.id}", headers=H(root)).status_code == 204
    assert "ops" not in [u["email"] for u in env.client.get("/api/users", headers=H(root)).json()]
    for method, path, body in (("GET", f"/api/users/{ops.id}/api-keys", None),
                               ("PATCH", f"/api/users/{ops.id}", {"role": "viewer"}),
                               ("POST", f"/api/users/{ops.id}/reset-password", None),
                               ("DELETE", f"/api/users/{ops.id}", None)):
        r = env.client.request(method, path, headers=H(root), json=body)
        assert (r.status_code, r.json()["detail"]["code"]) == (404, "not_found"), (method, path, r.text)


def test_delete_refuses_self_and_the_last_admin(env):
    from agenticops.services import user_admin
    root, root_tok = _user("root", "admin")
    r = env.client.delete(f"/api/users/{root.id}", headers=H(root_tok))
    assert (r.status_code, r.json()["detail"]["code"]) == (409, "self_change")
    with pytest.raises(user_admin.UserAdminError) as e:
        user_admin.delete_user(root.id, caller=None)
    assert (e.value.status, e.value.code) == (409, "last_admin")


def test_delete_refuses_open_requests_and_names_them(env):
    from agenticops.models import ChangeRequest, get_db_session
    _, root = _user("root", "admin")
    ops, _ = _user("ops")
    _change("user:ops", "planned")                                 # not waiting on the requester: no block
    draft = _change("user:ops", "draft")
    review = _change("user:ops", "under_review")                  # the review may hand it back to the requester
    r = env.client.delete(f"/api/users/{ops.id}", headers=H(root))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "has_open_requests"
    assert r.json()["detail"]["refs"] == [f"C#{draft}", f"C#{review}"]
    with get_db_session() as s:
        for cid in (draft, review):
            s.get(ChangeRequest, cid).status = "cancelled"
    assert env.client.delete(f"/api/users/{ops.id}", headers=H(root)).status_code == 204


def test_a_deleted_name_is_never_reused(env):
    from agenticops.auth import AuthService
    _, root = _user("root", "admin")
    ops, _ = _user("ops")
    env.client.delete(f"/api/users/{ops.id}", headers=H(root))
    r = env.client.post("/api/users", headers=H(root), json={"email": "ops", "name": None, "role": "writer", "settings_view": False})
    assert (r.status_code, r.json()["detail"]["code"]) == (409, "name_taken_by_deleted")
    with pytest.raises(ValueError):
        AuthService.create_user(email="ops", password="pw-new-123", is_admin=False, permissions=["read"])


def test_private_chats_and_reports_stay_private(env):
    from agenticops.auth.actor import Actor
    from agenticops.models import ChatSession, Report, get_db_session
    from agenticops.services import chat_access, report_access
    root, root_tok = _user("root", "admin")
    ops, _ = _user("ops")
    bob, _ = _user("bob")
    with get_db_session() as s:
        s.add(ChatSession(session_id="s-ops", name="mine", owner_user_id=ops.id, visibility="private"))
        s.add(Report(title="r", report_type="custom", summary="s", content_markdown="x", owner_user_id=ops.id,
                     visibility="private"))
    env.client.delete(f"/api/users/{ops.id}", headers=H(root_tok))
    other = Actor("user", "bob", bob.id, ("read", "write"))
    admin = Actor("user", "root", root.id, ("read", "write", "admin"))
    with get_db_session() as s:
        chat, report = s.query(ChatSession).one(), s.query(Report).one()
        assert not chat_access.can_see(chat, other) and chat_access.can_see(chat, admin)
        assert not report_access.can_see(report, other) and report_access.can_see(report, admin)
        assert chat_access.visible_filter(s.query(ChatSession), other).count() == 0
        assert report_access.visible_filter(s.query(Report), other).count() == 0


def test_delete_is_audited_once(env):
    from agenticops.audit.models import AuditLog
    from agenticops.models import get_db_session
    _, root = _user("root", "admin")
    ops, _ = _user("ops")
    env.client.delete(f"/api/users/{ops.id}", headers=H(root))
    with get_db_session() as s:
        rows = s.query(AuditLog).filter_by(action="user.delete").all()
        assert len(rows) == 1 and rows[0].entity_name == "ops" and rows[0].user_email == "root"


def test_the_delete_route_is_plain_def():
    import inspect
    from agenticops.web.routers import users as users_router
    ep = [r.endpoint for r in users_router.router.routes if r.path == "/api/users/{user_id}" and "DELETE" in r.methods]
    assert len(ep) == 1 and not inspect.iscoroutinefunction(ep[0])
