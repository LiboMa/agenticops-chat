"""Model connection settings (2026-11-08): how long a model stream may send nothing before it is cut (the read
timeout). The yaml block is the default; admins override it at runtime (DB `runtime_settings`, key `model_runtime`),
every change audited. Every agent build takes it through `preamble.bedrock_model_kwargs`."""
import pathlib
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import agenticops.web.app  # noqa: F401 — imported at collection (the auth middleware is added only when auth is on at import)

from agenticops.config import ModelRuntimeSettings

URL = "/api/settings/model-runtime"


@pytest.fixture
def db(tmp_path, monkeypatch):
    import agenticops.models as models_mod
    from agenticops.config import settings
    from agenticops.services import runtime_settings
    monkeypatch.setattr(models_mod, "_engine", None)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/mr.db")
    monkeypatch.setattr(settings, "model_runtime", ModelRuntimeSettings())
    models_mod.init_db()
    runtime_settings.reset_cache()
    yield settings
    runtime_settings.reset_cache()


def test_defaults_without_yaml_block():
    assert ModelRuntimeSettings().stream_read_timeout_seconds == 600


def test_yaml_block_loaded():
    from agenticops.config import settings
    assert settings.model_runtime.stream_read_timeout_seconds >= 60


def test_override_applies_and_survives_cache_reset(db):
    from agenticops.agents import model_runtime
    from agenticops.services import runtime_settings
    assert model_runtime.effective().stream_read_timeout_seconds == 600
    model_runtime.save_patch({"stream_read_timeout_seconds": 900}, "user:root")
    runtime_settings.reset_cache()
    assert model_runtime.effective().stream_read_timeout_seconds == 900
    assert model_runtime.overrides() == {"stream_read_timeout_seconds": 900}


@pytest.mark.parametrize("patch,field", [
    ({"stream_read_timeout_seconds": 59}, "stream_read_timeout_seconds"),
    ({"stream_read_timeout_seconds": 3601}, "stream_read_timeout_seconds"),
    ({"stream_read_timeout_seconds": "soon"}, "stream_read_timeout_seconds"),
    ({"connect_timeout": 5}, "connect_timeout"),
])
def test_bad_patch_refused_naming_the_field(db, patch, field):
    from agenticops.agents import model_runtime
    with pytest.raises(model_runtime.ModelRuntimeError) as e:
        model_runtime.validate_patch(patch)
    assert e.value.field == field


def test_a_stale_override_is_dropped_not_fatal(db, caplog):
    from agenticops.agents import model_runtime
    from agenticops.services import runtime_settings
    runtime_settings.put(model_runtime.KEY, {"stream_read_timeout_seconds": 5}, "user:root")
    runtime_settings.reset_cache()
    assert model_runtime.effective().stream_read_timeout_seconds == 600
    assert "dropped" in caplog.text


def test_reset_restores_the_default(db):
    from agenticops.agents import model_runtime
    model_runtime.save_patch({"stream_read_timeout_seconds": 1200}, "user:root")
    model_runtime.reset("user:root")
    assert model_runtime.effective().stream_read_timeout_seconds == 600


@pytest.mark.parametrize("model_id", ["global.anthropic.claude-fable-5-1", "openai.gpt-oss-120b-1:0"])
def test_every_model_build_gets_the_read_timeout(db, model_id):
    from agenticops.agents import model_runtime
    from agenticops.agents.preamble import bedrock_model_kwargs
    assert bedrock_model_kwargs(model_id)["boto_client_config"].read_timeout == 600
    model_runtime.save_patch({"stream_read_timeout_seconds": 1500}, "user:root")
    assert bedrock_model_kwargs(model_id)["boto_client_config"].read_timeout == 1500


def test_no_build_site_sets_its_own_client_config():
    """bedrock_model_kwargs carries boto_client_config: a site that also passes one is a duplicate-argument error."""
    agents = pathlib.Path(__file__).resolve().parents[1] / "src" / "agenticops"
    for path in [*agents.glob("agents/*_agent.py"), agents / "cli" / "context.py"]:
        assert "boto_client_config=" not in path.read_text(encoding="utf-8"), path.name


# ── API ──────────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def env(tmp_path, monkeypatch):
    import agenticops.audit.models  # noqa: F401
    import agenticops.auth.models  # noqa: F401
    import agenticops.models as models_mod
    import agenticops.web.app as webapp
    from agenticops.auth.service import AuthService
    from agenticops.config import settings
    from agenticops.services import runtime_settings
    from agenticops.web.app import APIAuthMiddleware, app
    monkeypatch.setattr(models_mod, "_engine", None)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/mr-api.db")
    monkeypatch.setattr(settings, "model_runtime", ModelRuntimeSettings())
    monkeypatch.setattr(settings, "api_auth_enabled", True)
    models_mod.init_db()
    runtime_settings.reset_cache()
    cleared = []
    monkeypatch.setattr(webapp._chat_sessions, "clear", lambda: cleared.append(1))

    def login(email, **kw):
        user = AuthService.create_user(email, "pw-123456", **kw)
        return {"Authorization": f"Bearer {AuthService.create_session(user.id)}"}
    yield SimpleNamespace(client=TestClient(APIAuthMiddleware(app)), login=login, cleared=cleared)
    runtime_settings.reset_cache()


def _audits():
    from agenticops.audit.models import AuditLog
    from agenticops.models import get_db_session
    with get_db_session() as db:
        return [(a.action, a.entity_id, a.old_values, a.new_values)
                for a in db.query(AuditLog).filter(AuditLog.entity_type == "runtime_setting").order_by(AuditLog.id)]


def test_get_shape(env):
    body = env.client.get(URL, headers=env.login("root@x", is_admin=True)).json()
    assert body["effective"] == {"stream_read_timeout_seconds": 600} == body["defaults"]
    assert body["overridden"] == [] and body["can_edit"] is True
    assert body["ranges"] == {"stream_read_timeout_seconds": [60, 3600]}


def test_patch_is_audited_and_rebuilds_the_chat_agents(env):
    h = env.login("root@x", is_admin=True)
    r = env.client.patch(URL, headers=h, json={"stream_read_timeout_seconds": 900})
    assert r.status_code == 200, r.text
    assert r.json()["effective"]["stream_read_timeout_seconds"] == 900 and r.json()["overridden"] == ["stream_read_timeout_seconds"]
    assert _audits() == [("update", "model_runtime", {"stream_read_timeout_seconds": 600}, {"stream_read_timeout_seconds": 900})]
    assert env.cleared == [1]   # the next turn builds its agent with the new value


def test_patch_out_of_range_is_422_naming_the_field(env):
    r = env.client.patch(URL, headers=env.login("root@x", is_admin=True), json={"stream_read_timeout_seconds": 10})
    assert r.status_code == 422 and r.json()["code"] == "invalid_model_runtime"
    assert r.json()["field"] == "stream_read_timeout_seconds" and _audits() == []


def test_non_admin_cannot_change_it(env):
    h = env.login("ops@x")
    assert env.client.patch(URL, headers=h, json={"stream_read_timeout_seconds": 900}).status_code == 403
    assert env.client.delete(URL, headers=h).status_code == 403
    assert env.client.get(URL, headers=h).json()["can_edit"] is False


def test_reset_is_audited(env):
    h = env.login("root@x", is_admin=True)
    env.client.patch(URL, headers=h, json={"stream_read_timeout_seconds": 900})
    body = env.client.delete(URL, headers=h).json()
    assert body["effective"]["stream_read_timeout_seconds"] == 600 and body["overridden"] == []
    assert [a[0] for a in _audits()] == ["update", "reset"]
