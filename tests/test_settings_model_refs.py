"""Model lists, model settings, Bedrock turned off, readiness (MVP-2.9.0 N35 task 6).

One list of models for every picker: Bedrock's (while Bedrock is on) and every enabled chat model of an enabled
provider, each with where it comes from and what it can do. The model settings beyond the agents' own are read and
changed through /api/settings by an administrator (agent models too, now); a value is a Bedrock id while Bedrock is
on, or an enabled chat model of an enabled provider — nothing else is stored. Settings whose model cannot be used are
listed. A chat whose model is gone fails its send with `model_unavailable` and says which model and why. The setup
overview verifies Main on whatever provider it runs on.
"""
import json
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from starlette.testclient import TestClient

from tests.llm_fake_server import ADMIN, FakeLLMServer, add_model, add_provider, llm_db

URL = "/api/settings"


@pytest.fixture
def env(tmp_path, monkeypatch):
    import agenticops.audit.models  # noqa: F401
    import agenticops.auth.models  # noqa: F401
    from agenticops.auth.service import AuthService
    from agenticops.services import model_service
    from agenticops.web.app import APIAuthMiddleware, app
    from agenticops.llm.registry import MODEL_SETTING_FIELDS
    settings = llm_db(tmp_path, monkeypatch, "n35-settings.db")
    # PATCH /api/settings sets these on the shared settings object: put each back after the test (they leaked into
    # every later file — a skill generation then asked for «local-llm», a provider only this test had)
    for field in MODEL_SETTING_FIELDS:
        monkeypatch.setattr(settings, field, getattr(settings, field))
    monkeypatch.setattr(settings, "api_auth_enabled", True)
    monkeypatch.setattr(settings, "rbac_enforce", False)
    written = []
    monkeypatch.setattr("agenticops.config.save_to_yaml", lambda updates: written.append(dict(updates)))
    monkeypatch.setattr(model_service, "_models_cache", (0.0, []))
    monkeypatch.setattr(model_service, "_fetch_bedrock_models", lambda region="us-east-1": [])   # → the fallback list

    def login(email, **kw):
        user = AuthService.create_user(email, "pw-123456", **kw)
        return {"Authorization": f"Bearer {AuthService.create_session(user.id)}"}
    with FakeLLMServer() as fake:
        add_provider("local-llm", f"{fake.base}/v1", display_name="Local LLM")
        add_model("local-llm", "fake-chat-1", supports_tools=True, context_window=32768)
        add_model("local-llm", "fake-embed-1", purpose="embedding")
        yield SimpleNamespace(client=TestClient(APIAuthMiddleware(app)), settings=settings, written=written,
                              fake=fake, login=login, monkeypatch=monkeypatch,
                              open_client=TestClient(app))      # sign-in off: the app as tests import it, no middleware


def _audits():
    from agenticops.audit.models import AuditLog
    from agenticops.models import get_db_session
    with get_db_session() as s:
        return [(r.entity_id, r.old_values, r.new_values) for r in s.query(AuditLog).filter_by(entity_name="settings")]


# ── one list ─────────────────────────────────────────────────────────────────

def test_presets_merge_and_skip_bedrock_when_off(env):
    from agenticops.llm import registry
    from agenticops.services import model_service
    from agenticops.web.app import _allowed_model_ids
    presets = model_service.get_model_presets()
    keys = {"label", "value", "context_window", "provider", "provider_label", "purpose", "capabilities", "priced"}
    assert all(keys <= set(p) for p in presets)
    bedrock = [p for p in presets if p["provider"] == "bedrock"]
    assert bedrock and {p["provider_label"] for p in bedrock} == {"Amazon Bedrock"}
    from agenticops.agents.preamble import claude_reasoning
    claudes = [p for p in bedrock if "anthropic.claude" in p["value"]]
    assert claudes and claudes[0]["capabilities"] == {"tools": True, "images": True, "documents": True,
                                                      "reasoning": claude_reasoning(claudes[0]["value"])}
    assert all(p["capabilities"]["reasoning"] == claude_reasoning(p["value"]) for p in claudes)  # the shape it is sent
    ours = [p for p in presets if p["provider"] == "local-llm"]
    assert [p["value"] for p in ours] == ["local-llm::fake-chat-1"]            # the embedding model is no chat model
    assert ours[0]["provider_label"] == "Local LLM" and ours[0]["capabilities"]["tools"] is True
    assert "local-llm::fake-chat-1" in _allowed_model_ids()

    registry.set_bedrock_enabled(False, ADMIN)
    env.monkeypatch.setattr(model_service, "_fetch_bedrock_models", MagicMock(side_effect=AssertionError("listed")))
    with patch("agenticops.config.get_bedrock_boto_session", side_effect=AssertionError("Bedrock was asked")):
        assert [p["value"] for p in model_service.get_model_presets()] == ["local-llm::fake-chat-1"]
        assert _allowed_model_ids() == {"local-llm::fake-chat-1"}               # no Bedrock alias either


# ── the model settings ───────────────────────────────────────────────────────

def test_get_settings_shows_the_model_settings(env):
    admin = env.login("root", is_admin=True)
    env.monkeypatch.setattr(env.settings, "bedrock_model_id_cheap", "local-llm::fake-chat-1")
    env.monkeypatch.setattr(env.settings, "galaxy_model_id", "")
    env.monkeypatch.setattr(env.settings, "executor_simple_model_id", "")
    env.monkeypatch.setattr(env.settings, "agent_executor_model_id", "global.anthropic.claude-opus-5-5")
    body = env.client.get(URL, headers=admin).json()
    ms = body["model_settings"]
    assert set(ms) == {"tier_default", "tier_cheap", "tier_strong", "executor_simple", "security",
                       "report_translation", "signal_gate", "rca_critic", "galaxy"}
    assert ms["tier_cheap"] == {"value": "local-llm::fake-chat-1", "effective": "local-llm::fake-chat-1", "default": None}
    assert ms["galaxy"] == {"value": "", "effective": "local-llm::fake-chat-1", "default": "local-llm::fake-chat-1"}
    assert ms["executor_simple"]["effective"] == "global.anthropic.claude-opus-5-5"
    assert body["model_issues"] == []
    assert any(p["value"] == "local-llm::fake-chat-1" for p in body["model_presets"])


def test_patch_model_settings_validates_refs_and_writes_yaml(env):
    from agenticops.llm import registry
    admin = env.login("root", is_admin=True)
    env.monkeypatch.setattr(env.settings, "bedrock_model_id_cheap", "global.anthropic.claude-haiku-4-5-20251001-v1:0")
    env.monkeypatch.setattr(env.settings, "security_model_id", "")
    r = env.client.patch(URL, json={"model_settings": {"tier_cheap": "local-llm::fake-chat-1", "security": ""}},
                         headers=admin)
    assert r.status_code == 200, r.text
    assert env.settings.bedrock_model_id_cheap == "local-llm::fake-chat-1"
    assert env.written[-1] == {"bedrock_model_id_cheap": "local-llm::fake-chat-1", "security_model_id": ""}
    assert r.json()["model_settings"]["security"]["effective"] == "local-llm::fake-chat-1"
    assert ("bedrock_model_id_cheap", {"bedrock_model_id_cheap": "global.anthropic.claude-haiku-4-5-20251001-v1:0"},
            {"bedrock_model_id_cheap": "local-llm::fake-chat-1"}) in _audits()

    before = env.settings.bedrock_model_id_strong
    for body, code, setting in (
            ({"tier_strong": "local-llm::not-listed"}, "unknown_model", "tier_strong"),
            ({"security": "local-llm::fake-embed-1"}, "unknown_model", "security"),       # an embedding model
            ({"rca_critic": "nowhere::m"}, "unknown_model", "rca_critic"),
            ({"tier_default": ""}, "unknown_model", "tier_default"),                      # a tier is never empty
            ({"tier_strong": "local-llm::fake-chat-1", "galaxy": "bad::"}, "unknown_model", "galaxy")):
        r = env.client.patch(URL, json={"model_settings": body}, headers=admin)
        assert r.status_code == 400 and r.json()["code"] == code and r.json()["setting"] == setting, (body, r.text)
    assert env.settings.bedrock_model_id_strong == before                                   # nothing was applied
    r = env.client.patch(URL, json={"model_settings": {"nonsense": "x"}}, headers=admin)
    assert r.status_code == 400

    r = env.client.patch(URL, json={"agent_models": {"main": {"model_id": "local-llm::not-listed"}}}, headers=admin)
    assert r.status_code == 400 and r.json()["code"] == "unknown_model"
    r = env.client.patch(URL, json={"agent_models": {"main": {"model_id": "local-llm::fake-chat-1"}}}, headers=admin)
    assert r.status_code == 200 and env.settings.agent_main_model_id == "local-llm::fake-chat-1"

    registry.set_bedrock_enabled(False, ADMIN)
    r = env.client.patch(URL, json={"model_settings": {"tier_strong": "global.anthropic.claude-opus-5-5"}}, headers=admin)
    assert r.status_code == 400 and r.json()["code"] == "bedrock_off"
    r = env.client.patch(URL, json={"agent_models": {"rca": {"model_id": "global.anthropic.claude-opus-5-5"}}},
                         headers=admin)
    assert r.status_code == 400 and r.json()["code"] == "bedrock_off"


def test_agent_models_patch_needs_an_admin_now(env):
    writer = env.login("ops", permissions=["read", "write"])
    for body in ({"agent_models": {"main": {"max_tokens": 8000}}}, {"model_settings": {"galaxy": ""}},
                 {"galaxy_model_id": ""}):
        assert env.client.patch(URL, json=body, headers=writer).status_code == 403, body
    assert env.client.patch(URL, json={"auto_rca_enabled": True}, headers=writer).status_code == 200


def test_model_issues_lists_settings_pointing_at_a_disabled_provider(env):
    from agenticops.llm import registry
    admin = env.login("root", is_admin=True)
    add_provider("parked", f"{env.fake.base}/v1", enabled=False)
    add_model("parked", "m1")
    env.monkeypatch.setattr(env.settings, "agent_reporter_model_id", "parked::m1")      # set by hand in the yaml
    env.monkeypatch.setattr(env.settings, "rca_critic_model_id", "gone::m2")
    issues = {i["setting"]: i for i in env.client.get(URL, headers=admin).json()["model_issues"]}
    assert issues["agent_reporter_model_id"] == {"setting": "agent_reporter_model_id", "value": "parked::m1",
                                                 "reason": "provider_disabled", "inherited": False}
    assert issues["rca_critic_model_id"]["reason"] == "unknown_provider"
    assert "agent_main_model_id" not in issues

    registry.set_bedrock_enabled(False, ADMIN)
    with patch("agenticops.config.get_bedrock_boto_session", side_effect=AssertionError("Bedrock was asked")):
        issues = {i["setting"]: i for i in env.client.get(URL, headers=admin).json()["model_issues"]}
    assert set(registry.bedrock_references()) <= set(issues)
    assert {issues[f]["reason"] for f in registry.bedrock_references()} == {"bedrock_off"}


# ── a chat whose model is gone ───────────────────────────────────────────────

def _frames(text: str) -> list[tuple[str, dict]]:
    out = []
    for block in text.replace("\r\n", "\n").split("\n\n"):
        ev, data = "message", []
        for line in block.split("\n"):
            if line.startswith("event:"):
                ev = line[6:].strip()
            elif line.startswith("data:"):
                data.append(line[5:].strip())
        if data:
            out.append((ev, json.loads("\n".join(data))))
    return out


@pytest.mark.parametrize("model,reason_words", [("gone::m", "no provider «gone»"),
                                                ("global.anthropic.claude-opus-5-5", "turned off")])
def test_chat_send_with_an_unavailable_model_fails_explicitly(env, model, reason_words):
    from agenticops.llm import registry
    from agenticops.models import ChatMessage, ChatSession, get_db_session
    import agenticops.web.app as webapp
    env.monkeypatch.setattr(env.settings, "api_auth_enabled", False)
    env.monkeypatch.setattr(webapp, "_generate_session_title", lambda *_a: None)
    webapp._chat_sessions.clear()
    registry.set_bedrock_enabled(False, ADMIN)
    now = datetime.now(timezone.utc)
    with get_db_session() as s:
        row = ChatSession(session_id=str(uuid.uuid4()), name="Chat", created_at=now, updated_at=now,
                          last_activity_at=now, model_id=model)
        s.add(row)
        s.flush()
        sid, pk = row.session_id, row.id
    with patch("agenticops.config.get_bedrock_boto_session", side_effect=AssertionError("Bedrock was asked")):
        r = env.open_client.post(f"/api/chat/sessions/{sid}/messages",
                            json={"content": "hi", "client_message_id": str(uuid.uuid4())})
    errors = [d for ev, d in _frames(r.text) if ev == "error"]
    assert len(errors) == 1 and errors[0]["code"] == "model_unavailable"
    assert model in errors[0]["detail"] and reason_words in errors[0]["detail"]
    with get_db_session() as s:
        states = [m.dispatch_state for m in s.query(ChatMessage).filter_by(session_id=pk).order_by(ChatMessage.id)]
    assert states == ["failed", "failed"]


def test_a_session_model_must_be_on_the_list(env):
    from agenticops.models import ChatSession, get_db_session
    env.monkeypatch.setattr(env.settings, "api_auth_enabled", False)
    now = datetime.now(timezone.utc)
    with get_db_session() as s:
        row = ChatSession(session_id=str(uuid.uuid4()), name="Chat", created_at=now, updated_at=now, last_activity_at=now)
        s.add(row)
        s.flush()
        sid = row.session_id
    assert env.open_client.patch(f"/api/chat/sessions/{sid}", json={"model_id": "local-llm::fake-chat-1"}).status_code == 200
    assert env.open_client.patch(f"/api/chat/sessions/{sid}", json={"model_id": "local-llm::fake-embed-1"}).status_code == 400


# ── the setup overview ───────────────────────────────────────────────────────

def test_readiness_verifies_a_ref_main(env):
    from agenticops.llm import registry
    from agenticops.services import readiness
    env.monkeypatch.setattr(env.settings, "agent_main_model_id", "local-llm::fake-chat-1")
    from agenticops.auth.actor import Actor
    actor = Actor("user", "root", permissions=("read", "write", "admin"))
    view = readiness.readiness(actor, can_verify=True)["model"]
    assert view["state"] == "configured" and view["provider"] == "local-llm"
    assert view["endpoint"] == f"{env.fake.base}/v1" and view["region"] is None
    with patch("agenticops.config.get_bedrock_boto_session", side_effect=AssertionError("Bedrock was asked")):
        out = readiness.verify_model(actor)
    assert out["ok"] is True
    assert [r["path"] for r in env.fake.requests if r["method"] == "POST"] == ["/v1/chat/completions"]
    assert readiness.readiness(actor, can_verify=True)["model"]["state"] == "verified"
    env.fake.require_key = "sk-RIGHT-0001"                           # a refused call keeps no sentence of the provider's
    out = readiness.verify_model(actor)
    assert out["ok"] is False and out["detail"] == "AuthenticationError (401)"
    env.fake.require_key = None
    readiness.verify_model(actor)
    registry.update("local-llm", {"base_url": f"{env.fake.base}/v2"}, ADMIN)                # pointed elsewhere:
    assert readiness.readiness(actor, can_verify=True)["model"]["state"] == "configured"    # the old check no longer counts
    env.monkeypatch.setattr(env.settings, "agent_main_model_id", "global.anthropic.claude-opus-5-5")
    view = readiness.readiness(actor, can_verify=True)["model"]
    assert view["provider"] == "bedrock" and view["region"] == env.settings.bedrock_region and view["endpoint"] is None


def test_a_refused_galaxy_model_leaves_the_rest_of_the_request_unapplied(env):
    """Review of MVP-2.9.0, Spec ⑥: galaxy_model_id's own check (it must be one of the listed models) ran after the
    other model settings of the same request had been written — a request answered 400 had already changed them."""
    h = env.login("root", is_admin=True)
    before = env.settings.security_model_id
    r = env.client.patch(URL, headers=h, json={"model_settings": {"security": "local-llm::fake-chat-1"},
                                               "galaxy_model_id": "global.anthropic.not-a-listed-model"})
    assert r.status_code == 400 and "galaxy_model_id" in r.text
    assert env.settings.security_model_id == before
    assert env.written == []
