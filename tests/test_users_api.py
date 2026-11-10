"""User management (MVP-2.8.0 S2 rework, owner 2026-11-09): admins list, create (one-time password), change the
role of, disable / enable and reset the password of web accounts — /api/users. Real users, real sessions, real API
keys on a temp DB; the HTTP layer through the app with sign-in on (and off where it matters)."""
import inspect
import json
from types import SimpleNamespace

import pytest
from starlette.testclient import TestClient

from agenticops.auth.roles import grants, role_of
from agenticops.models import Base


@pytest.fixture
def env(tmp_path, monkeypatch):
    import agenticops.audit.models  # noqa: F401  (audit_logs)
    import agenticops.auth.models  # noqa: F401  (users / sessions / api_keys)
    import agenticops.models as models_mod
    from agenticops.config import settings
    # import the app BEFORE turning sign-in on: app.py attaches APIAuthMiddleware at import when it is on, and that
    # would stay for every later test in the process; /api/users checks the Bearer token itself
    # (web/deps.require_authenticated_user), so the middleware is not needed here
    from agenticops.web.app import app
    monkeypatch.setattr(models_mod, "_engine", None)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/users.db")
    monkeypatch.setattr(settings, "api_auth_enabled", True)
    Base.metadata.create_all(models_mod.get_engine())
    return SimpleNamespace(client=TestClient(app), settings=settings)   # bare: the lifespan never starts


def _user(email, role="writer", settings_view=False):
    from agenticops.auth import AuthService
    is_admin, perms = grants(role, settings_view)
    user = AuthService.create_user(email=email, password=f"pw-{email}-0", is_admin=is_admin, permissions=perms)
    return user, AuthService.create_session(user.id)


def H(token):
    return {"Authorization": f"Bearer {token}"}


def _sessions(user_id):
    from agenticops.auth.models import Session
    from agenticops.models import get_db_session
    with get_db_session() as s:
        return s.query(Session).filter_by(user_id=user_id).count()


# ── roles (pure) ────────────────────────────────────────────────────────────────────────────────────────────


def test_the_four_roles_round_trip():
    for role, sv, want in [("admin", False, (True, ["read", "write", "admin"])), ("writer", False, (False, ["read", "write"])),
                           ("viewer", False, (False, ["read"])), ("viewer", True, (False, ["read", "settings_read"]))]:
        assert grants(role, sv) == want
        assert role_of(SimpleNamespace(is_admin=want[0], permissions=want[1])) == (role, sv)
    with pytest.raises(ValueError):
        grants("writer", True)
    with pytest.raises(ValueError):
        grants("owner", False)


# ── who may ─────────────────────────────────────────────────────────────────────────────────────────────────


def test_an_admin_lists_every_user_with_its_role_and_state(env):
    admin, tok = _user("root", "admin")
    _user("ops", "writer")
    _user("view", "viewer", True)
    r = env.client.get("/api/users", headers=H(tok))
    assert r.status_code == 200
    rows = r.json()
    assert [u["email"] for u in rows] == ["ops", "root", "view"]
    assert set(rows[0]) == {"id", "email", "name", "role", "settings_view", "is_active", "last_login_at", "created_at",
                            "active_api_keys"}
    assert {u["email"]: (u["role"], u["settings_view"]) for u in rows} == {
        "ops": ("writer", False), "root": ("admin", False), "view": ("viewer", True)}


def test_only_an_admin_may(env):
    _user("root", "admin")
    _, writer = _user("ops", "writer")
    _, viewer = _user("view", "viewer")
    assert env.client.get("/api/users", headers=H(writer)).status_code == 403
    assert env.client.get("/api/users", headers=H(viewer)).status_code == 403
    assert env.client.get("/api/users").status_code == 401
    assert env.client.post("/api/users", headers=H(writer), json={"email": "x", "role": "viewer"}).status_code == 403


# ── create ──────────────────────────────────────────────────────────────────────────────────────────────────


def test_create_gives_a_one_time_password_that_signs_in(env):
    from agenticops.auth import AuthService
    from agenticops.auth.models import User
    from agenticops.models import get_db_session
    _, tok = _user("root", "admin")
    for email, role, sv in [("w", "writer", False), ("v", "viewer", False), ("vs", "viewer", True), ("a2", "admin", False)]:
        r = env.client.post("/api/users", headers=H(tok), json={"email": email, "name": "N", "role": role, "settings_view": sv})
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["user"]["email"] == email and body["user"]["role"] == role and len(body["password"]) >= 12
        assert AuthService.authenticate(email, body["password"]) is not None
        with get_db_session() as s:
            u = s.query(User).filter_by(email=email).one()
            assert (u.is_admin, list(u.permissions)) == grants(role, sv)
    listed = env.client.get("/api/users", headers=H(tok)).json()
    assert all("password" not in u for u in listed)


def test_create_refuses_a_taken_or_empty_name_and_settings_on_a_writer(env):
    _, tok = _user("root", "admin")
    _user("ops", "writer")
    r = env.client.post("/api/users", headers=H(tok), json={"email": "ops", "role": "viewer"})
    assert (r.status_code, r.json()["detail"]["code"]) == (409, "email_taken")
    r = env.client.post("/api/users", headers=H(tok), json={"email": "   ", "role": "viewer"})
    assert (r.status_code, r.json()["detail"]["code"]) == (422, "invalid_email")
    r = env.client.post("/api/users", headers=H(tok), json={"email": "w2", "role": "writer", "settings_view": True})
    assert (r.status_code, r.json()["detail"]["code"]) == (422, "invalid_role")


# ── change ──────────────────────────────────────────────────────────────────────────────────────────────────


def test_a_role_change_applies_on_the_next_request(env):
    from agenticops.auth import AuthService
    _, tok = _user("root", "admin")
    view, view_tok = _user("view", "viewer")
    assert "write" not in AuthService.validate_session(view_tok).permissions
    r = env.client.patch(f"/api/users/{view.id}", headers=H(tok), json={"role": "writer"})
    assert r.status_code == 200 and r.json()["role"] == "writer"
    assert "write" in AuthService.validate_session(view_tok).permissions
    assert env.client.patch("/api/users/99999", headers=H(tok), json={"role": "viewer"}).json()["detail"]["code"] == "not_found"


def test_nobody_disables_or_demotes_themselves(env):
    root, tok = _user("root", "admin")
    _user("root2", "admin")
    for patch in ({"is_active": False}, {"role": "writer"}):
        r = env.client.patch(f"/api/users/{root.id}", headers=H(tok), json=patch)
        assert (r.status_code, r.json()["detail"]["code"]) == (409, "self_change")


def test_the_service_keeps_the_last_admin(env):
    """Defence in depth under the route's admin gate: whoever asks, the last active admin is never disabled or demoted
    (service level — through the API the caller is itself an active admin)."""
    from agenticops.services import user_admin
    sole, _ = _user("root", "admin")
    someone = SimpleNamespace(id=999, email="nobody")
    for kw in ({"is_active": False}, {"role": "viewer"}):
        with pytest.raises(user_admin.UserAdminError) as e:
            user_admin.update_user(sole.id, caller=someone, **kw)
        assert (e.value.status, e.value.code) == (409, "last_admin")


def test_with_sign_in_off_only_an_admin_manages_users_and_not_themselves(env):
    """S2 rework review: with sign-in off a viewer could reset the admin's password, make itself admin and disable
    the admin — all written to the DB, so it stayed the admin once sign-in was turned on. The gate is the caller's
    own is_admin in both modes (the web always signs in)."""
    env.settings.api_auth_enabled = False
    root, root_tok = _user("root", "admin")
    view, view_tok = _user("view", "viewer")
    _, writer = _user("ops", "writer")
    assert env.client.get("/api/users", headers=H(writer)).status_code == 403
    assert env.client.post(f"/api/users/{root.id}/reset-password", headers=H(view_tok)).status_code == 403
    assert env.client.patch(f"/api/users/{view.id}", headers=H(view_tok), json={"role": "admin"}).status_code == 403
    assert env.client.patch(f"/api/users/{root.id}", headers=H(view_tok), json={"is_active": False}).status_code == 403
    assert env.client.get("/api/users", headers=H(root_tok)).status_code == 200
    r = env.client.patch(f"/api/users/{root.id}", headers=H(root_tok), json={"is_active": False})
    assert (r.status_code, r.json()["detail"]["code"]) == (409, "self_change")


def test_disable_ends_sessions_and_keys_and_enable_brings_neither_back(env):
    from agenticops.auth import AuthService
    _, tok = _user("root", "admin")
    ops, ops_tok = _user("ops", "writer")
    key = AuthService.create_api_key(user_id=ops.id, name="ci", permissions=["read"])
    assert AuthService.validate_api_key(key) is not None
    r = env.client.patch(f"/api/users/{ops.id}", headers=H(tok), json={"is_active": False})
    assert r.status_code == 200 and r.json()["is_active"] is False
    assert AuthService.validate_session(ops_tok) is None and AuthService.validate_api_key(key) is None
    assert _sessions(ops.id) == 0
    AuthService.create_session(ops.id)          # a leftover the CLI's disable would leave behind
    r = env.client.patch(f"/api/users/{ops.id}", headers=H(tok), json={"is_active": True})
    assert r.status_code == 200 and r.json()["is_active"] is True
    assert AuthService.validate_api_key(key) is None and _sessions(ops.id) == 0


def test_enabling_after_a_cli_disable_does_not_revive_api_keys(env):
    """S2 rework review: `aiops users disable` only flips is_active (keys and sessions stay); the web enable must
    still leave every old key revoked and every old session gone."""
    from agenticops.auth import AuthService
    from agenticops.auth.models import User
    from agenticops.models import get_db_session
    _, tok = _user("root", "admin")
    ops, ops_tok = _user("ops", "writer")
    key = AuthService.create_api_key(user_id=ops.id, name="ci", permissions=["read"])
    with get_db_session() as s:                  # what the CLI's disable does
        s.query(User).filter_by(id=ops.id).one().is_active = False
    assert AuthService.validate_api_key(key) is None
    r = env.client.patch(f"/api/users/{ops.id}", headers=H(tok), json={"is_active": True})
    assert r.status_code == 200
    assert AuthService.validate_api_key(key) is None and AuthService.validate_session(ops_tok) is None


# ── reset password ──────────────────────────────────────────────────────────────────────────────────────────


def test_reset_ends_the_users_sessions_but_keeps_the_callers_own(env):
    from agenticops.auth import AuthService
    root, tok = _user("root", "admin")
    ops, ops_tok = _user("ops", "writer")
    r = env.client.post(f"/api/users/{ops.id}/reset-password", headers=H(tok))
    assert r.status_code == 200
    new = r.json()["password"]
    assert AuthService.validate_session(ops_tok) is None
    assert AuthService.authenticate("ops", new) is not None and AuthService.authenticate("ops", "pw-ops-0") is None
    other_tab = AuthService.create_session(root.id)
    r = env.client.post(f"/api/users/{root.id}/reset-password", headers=H(tok))
    assert r.status_code == 200
    assert AuthService.validate_session(tok) is not None          # the admin who asked keeps this browser
    assert AuthService.validate_session(other_tab) is None        # their other browsers sign out


# ── audit ───────────────────────────────────────────────────────────────────────────────────────────────────


def test_every_change_is_audited_and_never_the_password(env):
    from agenticops.audit.models import AuditLog
    from agenticops.models import get_db_session
    root, tok = _user("root", "admin")
    passwords = []
    r = env.client.post("/api/users", headers=H(tok), json={"email": "ops", "role": "viewer"})
    uid = r.json()["user"]["id"]
    passwords.append(r.json()["password"])
    env.client.patch(f"/api/users/{uid}", headers=H(tok), json={"role": "writer"})
    env.client.patch(f"/api/users/{uid}", headers=H(tok), json={"is_active": False})
    env.client.patch(f"/api/users/{uid}", headers=H(tok), json={"is_active": True})
    passwords.append(env.client.post(f"/api/users/{uid}/reset-password", headers=H(tok)).json()["password"])
    with get_db_session() as s:
        rows = s.query(AuditLog).filter_by(entity_type="user").order_by(AuditLog.id).all()
        assert [x.action for x in rows] == ["user.create", "user.update", "user.disable", "user.enable",
                                            "user.reset_password"]
        assert all(x.user_id == root.id and x.entity_id == str(uid) for x in rows)
        assert rows[1].old_values == {"role": "viewer", "settings_view": False}
        assert rows[1].new_values == {"role": "writer", "settings_view": False}
        dumped = json.dumps([[x.details, x.old_values, x.new_values] for x in rows])
    assert not any(p in dumped for p in passwords)


def test_the_routes_are_plain_def():
    from agenticops.web.routers import users
    endpoints = [r.endpoint for r in users.router.routes]
    assert len(endpoints) == 8 and not any(inspect.iscoroutinefunction(e) for e in endpoints)   # + 3 key routes + delete
