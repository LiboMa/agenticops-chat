"""Chat upload settings API: admins change the limits at runtime, every change is audited (2026-11-07)."""
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import agenticops.web.app  # noqa: F401 — imported at collection (the auth middleware is added only when auth is on at import)

from agenticops.config import ChatUploadSettings

URL = "/api/settings/chat-upload"


@pytest.fixture
def env(tmp_path, monkeypatch):
    import agenticops.audit.models  # noqa: F401
    import agenticops.auth.models  # noqa: F401
    import agenticops.models as models_mod
    from agenticops.auth.service import AuthService
    from agenticops.config import settings
    from agenticops.services import runtime_settings
    from agenticops.web.app import APIAuthMiddleware, app
    monkeypatch.setattr(models_mod, "_engine", None)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/cfg.db")
    monkeypatch.setattr(settings, "chat_upload", ChatUploadSettings())
    monkeypatch.setattr(settings, "api_auth_enabled", True)
    models_mod.init_db()
    runtime_settings.reset_cache()

    def login(email, **kw):
        user = AuthService.create_user(email, "pw-123456", **kw)
        return {"Authorization": f"Bearer {AuthService.create_session(user.id)}"}
    yield SimpleNamespace(client=TestClient(APIAuthMiddleware(app)), login=login, settings=settings,
                          monkeypatch=monkeypatch)
    runtime_settings.reset_cache()


def _audits():
    from agenticops.audit.models import AuditLog
    from agenticops.models import get_db_session
    with get_db_session() as db:
        return [(a.action, a.entity_type, a.entity_id, a.actor, a.old_values, a.new_values)
                for a in db.query(AuditLog).filter(AuditLog.entity_type == "runtime_setting").order_by(AuditLog.id)]


def test_get_shape(env):
    h = env.login("root@x", is_admin=True)
    body = env.client.get(URL, headers=h).json()
    assert body["effective"]["max_files"] == 20 and body["defaults"]["max_file_mb"] == 50
    assert body["overridden"] == [] and body["can_edit"] is True
    assert ".heic" in body["supported"]["image"] and ".xlsx" in body["supported"]["office"]
    assert "" in body["supported"]["text"] and body["supported"]["pdf"] == [".pdf"]
    assert body["ranges"]["max_files"] == [1, 50] and body["ranges"]["history_images_max"] == [0, 20]
    assert body["updated_by"] is None and body["updated_at"] is None


def test_patch_and_get_and_bootstrap_reflect(env):
    h = env.login("root@x", is_admin=True)
    r = env.client.patch(URL, headers=h, json={"max_files": 5, "allowed_extensions": [".pdf", ".png"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["effective"]["max_files"] == 5 and sorted(body["overridden"]) == ["allowed_extensions", "max_files"]
    assert body["updated_by"] == "user:root@x" and body["updated_at"]
    up = env.client.get("/api/ui/bootstrap", headers=h).json()["upload_policy"]
    assert up["max_files"] == 5 and up["extensions"] == [".pdf", ".png"]


def test_patch_422_field(env):
    h = env.login("root@x", is_admin=True)
    r = env.client.patch(URL, headers=h, json={"max_file_mb": 999})
    assert r.status_code == 422
    assert r.json()["code"] == "invalid_upload_config" and r.json()["field"] == "max_file_mb"
    r = env.client.patch(URL, headers=h, json={"max_total_mb": 10})
    assert r.status_code == 422 and r.json()["field"] == "max_total_mb"
    assert env.client.patch(URL, headers=h, json=[1, 2]).status_code == 422
    assert _audits() == []


def test_non_admin_403_when_auth_on(env):
    h = env.login("writer@x")
    assert env.client.get(URL, headers=h).json()["can_edit"] is False
    assert env.client.patch(URL, headers=h, json={"max_files": 3}).status_code == 403
    assert env.client.delete(URL, headers=h).status_code == 403
    assert env.client.get(URL, headers=h).json()["effective"]["max_files"] == 20


def test_admin_api_key_without_admin_scope_cannot_edit(env):
    from agenticops.auth.service import AuthService
    user = AuthService.create_user("keyed@x", "pw-123456", is_admin=True)
    key = AuthService.create_api_key(user.id, "read-only", permissions=["read"])
    h = {"Authorization": f"Bearer {key}"}
    assert env.client.get(URL, headers=h).json()["can_edit"] is False
    assert env.client.patch(URL, headers=h, json={"max_files": 3}).status_code == 403


def test_viewer_403_on_patch_and_reads_with_settings_read(env):
    viewer = env.login("v@x", permissions=["read"])
    editor = env.login("e@x", permissions=["read", "settings_read"])
    assert env.client.get(URL, headers=viewer).status_code == 403
    body = env.client.get(URL, headers=editor).json()
    assert body["can_edit"] is False and body["effective"]["max_files"] == 20
    for h in (viewer, editor):
        assert env.client.patch(URL, headers=h, json={"max_files": 3}).status_code == 403
        assert env.client.delete(URL, headers=h).status_code == 403


def test_audit_row_per_change(env):
    h = env.login("root@x", is_admin=True)
    env.client.patch(URL, headers=h, json={"max_files": 5})
    env.client.patch(URL, headers=h, json={"history_images_max": 2})
    env.client.delete(URL, headers=h)
    rows = _audits()
    assert [(r[0], r[2], r[3]) for r in rows] == [("update", "chat_upload", "user:root@x"),
                                                 ("update", "chat_upload", "user:root@x"),
                                                 ("reset", "chat_upload", "user:root@x")]
    assert rows[0][4] == {"max_files": 20} and rows[0][5] == {"max_files": 5}
    assert rows[1][5] == {"history_images_max": 2}


def test_reset(env):
    h = env.login("root@x", is_admin=True)
    env.client.patch(URL, headers=h, json={"max_files": 5})
    body = env.client.delete(URL, headers=h).json()
    assert body["effective"]["max_files"] == 20 and body["overridden"] == []


def test_survives_restart(env):
    from agenticops.services import runtime_settings
    h = env.login("root@x", is_admin=True)
    env.client.patch(URL, headers=h, json={"text_max_chars": 5000})
    runtime_settings.reset_cache()
    assert env.client.get(URL, headers=h).json()["effective"]["text_max_chars"] == 5000


def test_auth_off_anyone_may_edit(env):
    env.monkeypatch.setattr(env.settings, "api_auth_enabled", False)
    from agenticops.web.app import app
    client = TestClient(app)
    assert client.get(URL).json()["can_edit"] is True
    assert client.patch(URL, json={"max_files": 7}).json()["effective"]["max_files"] == 7
