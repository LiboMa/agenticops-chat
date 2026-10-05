# tests/test_ui_bootstrap.py
"""Workspace UI bootstrap + preferences (MVP-2.7.0 S2, contract workspace-ui-1).

GET /api/ui/bootstrap and GET/PATCH /api/users/me/preferences identify the signed-in user from the Bearer
token in BOTH auth modes (the web UI always signs in); preferences are revisioned and every write must name
the revision it read (If-Match) — a stale one is 412, a missing one 428. Nothing secret is ever in bootstrap."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from starlette.testclient import TestClient

from agenticops.models import Base

ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads((ROOT / "tests/fixtures/ui_last_route_cases.json").read_text())


@pytest.fixture
def env(tmp_path, monkeypatch):
    import agenticops.models as models_mod
    import agenticops.auth.models  # noqa: F401
    from agenticops.auth.service import AuthService
    from agenticops.config import settings
    from agenticops.web.app import app
    monkeypatch.setattr(models_mod, "_engine", None)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/ui.db")
    monkeypatch.setattr(settings, "api_auth_enabled", False)  # the default: the UI still signs in
    models_mod.init_db()

    def login(email):
        user = AuthService.create_user(email, "pw-123456")
        return {"Authorization": f"Bearer {AuthService.create_session(user.id)}"}, user.id
    return SimpleNamespace(client=TestClient(app), login=login, settings=settings)


def _prefs(env, headers):
    r = env.client.get("/api/users/me/preferences", headers=headers)
    assert r.status_code == 200, r.text
    return r


# ── bootstrap ──────────────────────────────────────────────────────────────

CONTRACT_KEYS = {"contract_version", "deployment_id", "user_id", "locale", "features", "upload_policy", "preferences"}
EXTENSIONS = {"user", "auth_enabled", "version"}  # documented 2.7.0 additions (the contract allows extra fields)


def test_bootstrap_needs_a_signed_in_user(env):
    assert env.client.get("/api/ui/bootstrap").status_code == 401
    assert env.client.get("/api/ui/bootstrap", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_bootstrap_has_exactly_the_contract_fields_plus_the_documented_extensions(env):
    headers, uid = env.login("alice@example.com")
    body = env.client.get("/api/ui/bootstrap", headers=headers).json()
    assert set(body) == CONTRACT_KEYS | EXTENSIONS
    assert body["contract_version"] == "workspace-ui-1"
    assert body["user_id"] == uid and body["user"] == {"id": uid, "email": "alice@example.com", "name": None,
                                                        "is_admin": False}
    assert body["auth_enabled"] is False
    assert set(body["preferences"]) == {"revision", "locale", "home", "last_route", "nav_groups_open"}


def test_bootstrap_features_say_only_what_is_built(env, monkeypatch):
    headers, _ = env.login("alice@example.com")
    monkeypatch.setattr(env.settings, "change_management_enabled", True)
    features = env.client.get("/api/ui/bootstrap", headers=headers).json()["features"]
    assert features == {"context_chat": False, "revision_guards": False, "content_rendering": False,
                        "report_export": False, "attention": False, "change_management": True, "chat_replay": False}
    monkeypatch.setattr(env.settings, "change_management_enabled", False)
    assert env.client.get("/api/ui/bootstrap", headers=headers).json()["features"]["change_management"] is False


def test_bootstrap_upload_policy_follows_the_servers_dispatch(env):
    from agenticops.chat import file_reader as fr
    headers, _ = env.login("alice@example.com")
    up = env.client.get("/api/ui/bootstrap", headers=headers).json()["upload_policy"]
    assert (up["max_files"], up["image_max_bytes"], up["document_max_bytes"], up["text_fallback_max_bytes"]) == (
        fr.MAX_UPLOAD_FILES, fr.MAX_IMAGE_SIZE, fr.MAX_DOCUMENT_SIZE, fr.MAX_FILE_SIZE)
    assert ".png" in up["image_extensions"] and ".bmp" not in up["image_extensions"]  # .bmp is not an image upload
    assert ".pdf" in up["document_extensions"] and ".md" in up["document_extensions"]
    assert ".log" in up["text_extensions"] and ".md" not in up["text_extensions"]  # a .md is sent as a document
    assert not set(up["document_extensions"]) & set(up["text_extensions"])


def test_bootstrap_carries_no_secret(env, monkeypatch):
    for name in ("webhook_secret", "change_intake_secret", "admin_password", "itsm_servicenow_password"):
        monkeypatch.setattr(env.settings, name, f"S3CRET-{name}", raising=False)
    headers, _ = env.login("alice@example.com")
    text = env.client.get("/api/ui/bootstrap", headers=headers).text
    assert "S3CRET" not in text
    assert not any(word in text.lower() for word in ("secret", "password", "token", "access_key"))


def test_deployment_id_is_stable_and_stored_in_the_database(env):
    import agenticops.models as models_mod
    headers, _ = env.login("alice@example.com")
    first = env.client.get("/api/ui/bootstrap", headers=headers).json()["deployment_id"]
    models_mod.init_db()  # a restart
    assert len(first) >= 16
    assert env.client.get("/api/ui/bootstrap", headers=headers).json()["deployment_id"] == first


def test_an_api_key_caller_gets_bootstrap_with_auth_off(env):
    from agenticops.auth.service import AuthService
    _, uid = env.login("ci@example.com")
    key = AuthService.create_api_key(uid, "ci")
    assert env.client.get("/api/ui/bootstrap", headers={"Authorization": f"Bearer {key}"}).status_code == 200


# ── preferences ────────────────────────────────────────────────────────────

def test_preferences_start_at_revision_one_with_an_etag(env):
    headers, _ = env.login("alice@example.com")
    r = _prefs(env, headers)
    assert r.json() == {"revision": 1, "locale": "en", "home": "resume", "last_route": None, "nav_groups_open": []}
    assert r.headers["etag"] == '"1"'


def test_a_write_must_name_the_revision_it_read(env):
    headers, _ = env.login("alice@example.com")
    r = env.client.patch("/api/users/me/preferences", headers=headers, json={"home": "reports"})
    assert r.status_code == 428 and r.json()["code"] == "if_match_required"
    r = env.client.patch("/api/users/me/preferences", headers={**headers, "If-Match": '"7"'}, json={"home": "reports"})
    assert r.status_code == 412 and r.json()["code"] == "revision_mismatch"
    r = env.client.patch("/api/users/me/preferences", headers={**headers, "If-Match": '"1"'}, json={"home": "reports"})
    assert r.status_code == 200, r.text
    assert (r.json()["revision"], r.json()["home"], r.headers["etag"]) == (2, "reports", '"2"')
    # the same stale revision again is now a conflict (two tabs, one saved first)
    r = env.client.patch("/api/users/me/preferences", headers={**headers, "If-Match": '"1"'}, json={"home": "chat"})
    assert r.status_code == 412
    assert _prefs(env, headers).json()["home"] == "reports"


@pytest.mark.parametrize("if_match", ['"1"', 'W/"1"', "1"])
def test_if_match_accepts_the_etag_forms(env, if_match):
    headers, _ = env.login("alice@example.com")
    r = env.client.patch("/api/users/me/preferences", headers={**headers, "If-Match": if_match}, json={"locale": "zh"})
    assert r.status_code == 200 and r.json()["locale"] == "zh"


def test_a_wildcard_write_merges_one_field_without_touching_the_others(env):
    """last_route is written often (throttled) from every tab: `If-Match: *` merges it and never overwrites home."""
    headers, _ = env.login("alice@example.com")
    env.client.patch("/api/users/me/preferences", headers={**headers, "If-Match": '"1"'}, json={"home": "issues"})
    r = env.client.patch("/api/users/me/preferences", headers={**headers, "If-Match": "*"},
                         json={"last_route": "/app/issues/42"})
    assert r.status_code == 200
    assert (r.json()["home"], r.json()["last_route"], r.json()["revision"]) == ("issues", "/app/issues/42", 3)


@pytest.mark.parametrize("body", [
    {}, {"home": "dashboard"}, {"locale": "fr"}, {"nav_groups_open": ["tools", "tools"]},
    {"nav_groups_open": ["admin"]}, {"theme": "dark"}, {"last_route": 42},
])
def test_an_invalid_write_is_422(env, body):
    headers, _ = env.login("alice@example.com")
    r = env.client.patch("/api/users/me/preferences", headers={**headers, "If-Match": "*"}, json=body)
    assert r.status_code == 422, (body, r.text)


@pytest.mark.parametrize("route", CASES["accept"])
def test_an_allow_listed_last_route_is_kept(env, route):
    headers, _ = env.login("alice@example.com")
    r = env.client.patch("/api/users/me/preferences", headers={**headers, "If-Match": "*"}, json={"last_route": route})
    assert r.status_code == 200 and r.json()["last_route"] == route


@pytest.mark.parametrize("route", CASES["reject"])
def test_a_route_outside_the_allow_list_is_refused(env, route):
    headers, _ = env.login("alice@example.com")
    r = env.client.patch("/api/users/me/preferences", headers={**headers, "If-Match": "*"}, json={"last_route": route})
    assert r.status_code == 422, route


def test_preferences_are_per_user(env):
    alice, _ = env.login("alice@example.com")
    bob, _ = env.login("bob@example.com")
    env.client.patch("/api/users/me/preferences", headers={**alice, "If-Match": '"1"'}, json={"home": "reports"})
    assert _prefs(env, bob).json()["home"] == "resume"
    assert env.client.get("/api/ui/bootstrap", headers=alice).json()["preferences"]["home"] == "reports"


def test_preferences_need_a_signed_in_user(env):
    assert env.client.get("/api/users/me/preferences").status_code == 401
    assert env.client.patch("/api/users/me/preferences", headers={"If-Match": "*"}, json={"home": "chat"}).status_code == 401


# ── odds and ends the shell relies on ──────────────────────────────────────

def test_cors_lets_the_browser_send_if_match_on_a_patch(env, monkeypatch):
    from agenticops.web import app as app_mod
    src = (ROOT / "src/agenticops/web/app.py").read_text()
    assert '"PATCH"' in src and '"If-Match"' in src and 'expose_headers=["ETag"]' in src
    assert app_mod  # imported


def test_old_anomaly_links_land_on_cases(env):
    r = env.client.get("/anomalies", follow_redirects=False)
    assert (r.status_code, r.headers["location"]) == (302, "/app/issues")
    r = env.client.get("/anomaly/5", follow_redirects=False)
    assert (r.status_code, r.headers["location"]) == (302, "/app/issues/5")


def test_the_cli_banner_names_the_web_ui_not_the_dashboard():
    src = (ROOT / "src/agenticops/cli/main.py").read_text()
    assert "Dashboard : http" not in src and "Web dashboard : http" not in src


@pytest.mark.parametrize("if_match", [b"\xb2", b"\xb9", b"0", b"-1", b"abc", b'"1x"'])
def test_a_malformed_if_match_is_428_not_a_crash(env, if_match):
    """A raw 0xB2 byte reaches the server as '²', which str.isdigit() accepts and int() refuses (was a 500)."""
    headers, _ = env.login("alice@example.com")
    r = env.client.patch("/api/users/me/preferences", headers={**headers, "If-Match": if_match}, json={"home": "chat"})
    assert r.status_code == 428, (if_match, r.status_code)


def test_an_if_match_list_matches_any_of_its_revisions(env):
    headers, _ = env.login("alice@example.com")
    r = env.client.patch("/api/users/me/preferences", headers={**headers, "If-Match": '"7", "1"'}, json={"home": "chat"})
    assert r.status_code == 200 and r.json()["revision"] == 2
    r = env.client.patch("/api/users/me/preferences", headers={**headers, "If-Match": '"7", "8"'}, json={"home": "issues"})
    assert r.status_code == 412


def test_an_unauthenticated_write_is_401_before_its_body_is_judged(env):
    r = env.client.patch("/api/users/me/preferences", headers={"If-Match": "*"}, json={"home": "nonsense", "x": 1})
    assert r.status_code == 401
