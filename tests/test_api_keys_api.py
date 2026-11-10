"""API keys (MVP-2.8.0, owner 2026-11-10): «My API keys» and the admin's view — /api/api-keys, /api/users/{id}/api-keys.

- Keys are managed only from a signed-in session: a request that came through a key never creates or revokes keys,
  changes the password or manages users (403 session_required) — a leaked key could otherwise mint its successor.
- A key is ["read"] or ["read","write"], never more than its owner's role (a viewer: read only), never admin.
- A demotion that takes write away downgrades the user's keys to read; a promotion never upgrades them.
- The full key is returned once at creation and never listed, audited or shown to an admin.
The app is imported BEFORE sign-in is turned on and the middleware wrapped around it (see test_api_key_scope)."""
import inspect
import json
from datetime import datetime, timedelta, timezone
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
    Base.metadata.create_all(models_mod.get_engine())
    return SimpleNamespace(client=TestClient(APIAuthMiddleware(app)))


def _user(email, role="writer", settings_view=False):
    from agenticops.auth import AuthService
    is_admin, perms = grants(role, settings_view)
    u = AuthService.create_user(email=email, password=f"pw-{email}-0", is_admin=is_admin, permissions=perms)
    return u, AuthService.create_session(u.id)


def H(tok):
    return {"Authorization": f"Bearer {tok}"}


def _create(env, tok, **body):
    return env.client.post("/api/api-keys", headers=H(tok), json={"name": "k", "permissions": ["read"], **body})


# ── my keys ─────────────────────────────────────────────────────────────────────────────────────────────────


def test_create_list_revoke_and_the_key_is_shown_once(env):
    from agenticops.auth import AuthService
    ops, tok = _user("ops")
    r = _create(env, tok, name="Claude Code · laptop", permissions=["read", "write"], expires_days=90)
    assert r.status_code == 201, r.text
    body = r.json()
    key = body["key"]
    assert key.startswith("aiops_") and body["key_prefix"] == key[:len(body["key_prefix"])] and body["created_at"]
    assert AuthService.validate_api_key(key) is not None
    listed = env.client.get("/api/api-keys", headers=H(tok)).json()
    assert [k["name"] for k in listed] == ["Claude Code · laptop"]
    assert set(listed[0]) == {"id", "name", "key_prefix", "permissions", "is_active", "last_used_at", "expires_at", "created_at"}
    assert key not in json.dumps(listed)
    assert env.client.delete(f"/api/api-keys/{body['id']}", headers=H(tok)).status_code == 204
    assert AuthService.validate_api_key(key) is None
    assert env.client.get("/api/api-keys", headers=H(tok)).json() == []   # a deleted (revoked) key leaves the list


def test_scope_is_read_or_read_write_never_more_than_the_owner(env):
    _, viewer = _user("view", "viewer")
    _, writer = _user("ops", "writer")
    assert _create(env, viewer, permissions=["read"]).status_code == 201
    r = _create(env, viewer, permissions=["read", "write"])
    assert (r.status_code, r.json()["detail"]["code"]) == (403, "scope_exceeds_role")
    for bad in (["read", "admin"], ["write"], [], ["read", "write", "admin"]):
        r = _create(env, writer, permissions=bad)
        assert (r.status_code, r.json()["detail"]["code"]) == (422, "invalid_scope"), bad
    assert _create(env, writer, name="   ").json()["detail"]["code"] == "invalid_name"
    for bad in (0, 3651, -5):
        assert _create(env, writer, expires_days=bad).json()["detail"]["code"] == "invalid_expiry", bad
    assert _create(env, writer, expires_days=None).status_code == 201


def test_a_key_never_manages_keys_the_password_or_users(env):
    from agenticops.auth import AuthService
    root, root_tok = _user("root", "admin")
    ops, ops_tok = _user("ops", "writer")
    own_id = _create(env, ops_tok).json()["id"]
    rw = AuthService.create_api_key(user_id=ops.id, name="rw", permissions=["read", "write"])
    admin_key = AuthService.create_api_key(user_id=root.id, name="admin", permissions=["read", "write", "admin"])
    for method, path, body in (("POST", "/api/api-keys", {"name": "x", "permissions": ["read"]}),
                               ("DELETE", f"/api/api-keys/{own_id}", None),
                               ("GET", "/api/api-keys", None),
                               ("PUT", "/api/users/me/password", {"old_password": "pw-ops-0", "new_password": "pw-ops-1"})):
        r = env.client.request(method, path, headers=H(rw), json=body)
        assert (r.status_code, r.json()["detail"].get("code")) == (403, "session_required"), (method, path, r.text)
    for method, path in (("GET", "/api/users"), ("POST", f"/api/users/{ops.id}/reset-password"),
                         ("DELETE", f"/api/users/{ops.id}")):
        r = env.client.request(method, path, headers=H(admin_key))
        assert (r.status_code, r.json()["detail"].get("code")) == (403, "session_required"), (method, path, r.text)


def test_revoking_someone_elses_key_is_a_404(env):
    a, a_tok = _user("a")
    _, b_tok = _user("b")
    kid = _create(env, a_tok).json()["id"]
    r = env.client.delete(f"/api/api-keys/{kid}", headers=H(b_tok))
    assert (r.status_code, r.json()["detail"]["code"]) == (404, "not_found")


# ── the admin's view ───────────────────────────────────────────────────────────────────────────────────────


def test_an_admin_lists_and_revokes_someone_elses_keys(env):
    from agenticops.auth import AuthService
    from agenticops.auth.models import APIKey
    from agenticops.models import get_db_session
    _, root = _user("root", "admin")
    ops, ops_tok = _user("ops")
    live = _create(env, ops_tok, name="live").json()
    gone = _create(env, ops_tok, name="old").json()
    env.client.delete(f"/api/api-keys/{gone['id']}", headers=H(ops_tok))
    expired = _create(env, ops_tok, name="expired").json()
    with get_db_session() as s:                   # expired yesterday
        s.query(APIKey).filter_by(id=expired["id"]).one().expires_at = datetime.now(timezone.utc) - timedelta(days=1)
    rows = {u["email"]: u for u in env.client.get("/api/users", headers=H(root)).json()}
    assert rows["ops"]["active_api_keys"] == 1 and rows["root"]["active_api_keys"] == 0
    keys = env.client.get(f"/api/users/{ops.id}/api-keys", headers=H(root)).json()
    assert sorted(k["name"] for k in keys) == ["expired", "live"]       # the revoked «old» is no longer listed
    assert live["key"] not in json.dumps(keys)
    assert env.client.delete(f"/api/users/{ops.id}/api-keys/{live['id']}", headers=H(root)).status_code == 204
    assert AuthService.validate_api_key(live["key"]) is None
    assert env.client.get(f"/api/users/{ops.id}/api-keys", headers=H(ops_tok)).status_code == 403


# ── a demotion downgrades ──────────────────────────────────────────────────────────────────────────────────


def test_a_demotion_downgrades_the_keys_and_a_promotion_does_not_upgrade(env):
    from agenticops.audit.models import AuditLog
    from agenticops.models import get_db_session
    _, root = _user("root", "admin")
    ops, ops_tok = _user("ops")
    kid = _create(env, ops_tok, permissions=["read", "write"]).json()["id"]
    env.client.patch(f"/api/users/{ops.id}", headers=H(root), json={"role": "viewer"})
    perms = lambda: [k["permissions"] for k in env.client.get(f"/api/users/{ops.id}/api-keys", headers=H(root)).json()]
    assert perms() == [["read"]]
    env.client.patch(f"/api/users/{ops.id}", headers=H(root), json={"role": "writer"})
    assert perms() == [["read"]]
    with get_db_session() as s:
        assert s.query(AuditLog).filter_by(action="api_key.downgrade", entity_id=str(kid)).count() == 1


# ── audit ──────────────────────────────────────────────────────────────────────────────────────────────────


def test_keys_are_audited_and_never_the_key(env):
    from agenticops.audit.models import AuditLog
    from agenticops.models import get_db_session
    root, root_tok = _user("root", "admin")
    ops, ops_tok = _user("ops")
    a = _create(env, ops_tok, name="a").json()
    b = _create(env, ops_tok, name="b").json()
    env.client.delete(f"/api/api-keys/{a['id']}", headers=H(ops_tok))
    env.client.delete(f"/api/users/{ops.id}/api-keys/{b['id']}", headers=H(root_tok))
    with get_db_session() as s:
        rows = s.query(AuditLog).filter_by(entity_type="api_key").order_by(AuditLog.id).all()
        assert [x.action for x in rows] == ["api_key.create", "api_key.create", "api_key.revoke", "api_key.revoke"]
        assert rows[2].user_id == ops.id and rows[2].details.get("by_admin") is False
        assert rows[3].user_id == root.id and rows[3].details.get("by_admin") is True
        assert rows[0].details.get("key_prefix") == a["key_prefix"] and rows[0].details.get("owner_id") == ops.id
        dumped = json.dumps([[x.details, x.old_values, x.new_values, x.entity_name] for x in rows])
    assert a["key"] not in dumped and b["key"] not in dumped


def test_the_key_routes_are_plain_def():
    from agenticops.web.routers import auth as auth_router
    from agenticops.web.routers import users as users_router
    names = {"api_create_api_key", "api_list_api_keys", "api_revoke_api_key", "api_change_password"}
    eps = {r.endpoint.__name__: r.endpoint for r in auth_router.router.routes if r.endpoint.__name__ in names}
    assert set(eps) == names and not any(inspect.iscoroutinefunction(e) for e in eps.values())
    uk = [r.endpoint for r in users_router.router.routes if "api-keys" in r.path]
    assert len(uk) == 3 and not any(inspect.iscoroutinefunction(e) for e in uk)   # list, revoke, issue


# ── an admin issues a key for someone (MVP-2.8.0 user management, owner 2026-11-10) ───────────────────────


def _issue(env, admin_tok, user_id, **body):
    return env.client.post(f"/api/users/{user_id}/api-keys", headers=H(admin_tok),
                           json={"name": "for you", "permissions": ["read"], "expires_days": 90, **body})


def test_revoked_keys_leave_both_lists(env):
    _, root = _user("root", "admin")
    ops, ops_tok = _user("ops")
    keep = _create(env, ops_tok, name="keep").json()
    gone = _create(env, ops_tok, name="gone").json()
    env.client.delete(f"/api/api-keys/{gone['id']}", headers=H(ops_tok))
    assert [k["name"] for k in env.client.get("/api/api-keys", headers=H(ops_tok)).json()] == ["keep"]
    assert [k["id"] for k in env.client.get(f"/api/users/{ops.id}/api-keys", headers=H(root)).json()] == [keep["id"]]


def test_an_admin_issues_a_key_that_belongs_to_the_user(env):
    from agenticops.audit.models import AuditLog
    from agenticops.auth import AuthService
    from agenticops.models import get_db_session
    _, root = _user("root", "admin")
    ops, _ = _user("ops")
    r = _issue(env, root, ops.id, permissions=["read", "write"])
    assert r.status_code == 201, r.text
    key = r.json()["key"]
    owner = AuthService.validate_api_key(key)
    assert owner is not None and owner[0].id == ops.id
    with get_db_session() as s:
        row = s.query(AuditLog).filter_by(action="api_key.create").one()
        assert row.user_email == "root" and row.details["owner_id"] == ops.id and row.details["by_admin"] is True
        dumped = json.dumps([row.details, row.old_values, row.new_values, row.entity_name])
    assert key not in dumped


def test_an_admin_cannot_exceed_the_users_role(env):
    _, root = _user("root", "admin")
    viewer, _ = _user("view", "viewer")
    ops, _ = _user("ops")
    r = _issue(env, root, viewer.id, permissions=["read", "write"])
    assert (r.status_code, r.json()["detail"]["code"]) == (403, "scope_exceeds_role")
    r = _issue(env, root, ops.id, permissions=["read", "write", "admin"])
    assert (r.status_code, r.json()["detail"]["code"]) == (422, "invalid_scope")


def test_no_key_for_a_disabled_or_deleted_user(env):
    _, root = _user("root", "admin")
    off, _ = _user("off")
    gone, _ = _user("gone")
    env.client.patch(f"/api/users/{off.id}", headers=H(root), json={"is_active": False})
    env.client.delete(f"/api/users/{gone.id}", headers=H(root))
    r = _issue(env, root, off.id)
    assert (r.status_code, r.json()["detail"]["code"]) == (409, "user_inactive")
    r = _issue(env, root, gone.id)
    assert (r.status_code, r.json()["detail"]["code"]) == (404, "not_found")


def test_only_a_signed_in_admin_issues_keys(env):
    from agenticops.auth import AuthService
    root, _ = _user("root", "admin")
    ops, ops_tok = _user("ops")
    assert _issue(env, ops_tok, root.id).status_code == 403
    admin_key = AuthService.create_api_key(user_id=root.id, name="admin", permissions=["read", "write", "admin"])
    r = _issue(env, admin_key, ops.id)
    assert (r.status_code, r.json()["detail"]["code"]) == (403, "session_required")
