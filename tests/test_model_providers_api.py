"""The model-provider API and CLI (MVP-2.9.0 N35 task 4) — real users, sessions and API keys on a temp DB, the HTTP
layer through the app with sign-in on, the provider's own HTTP against the local fake server."""
import json
from types import SimpleNamespace

import pytest
from starlette.testclient import TestClient
from typer.testing import CliRunner

from agenticops.auth.roles import grants
from tests.llm_fake_server import FakeLLMServer, llm_db


@pytest.fixture
def env(tmp_path, monkeypatch):
    import agenticops.audit.models  # noqa: F401
    import agenticops.auth.models  # noqa: F401
    from agenticops.web.app import app
    settings = llm_db(tmp_path, monkeypatch, "n35-api.db")
    monkeypatch.setattr(settings, "api_auth_enabled", True)
    with FakeLLMServer() as fake:
        yield SimpleNamespace(client=TestClient(app), settings=settings, fake=fake)


def _user(email, role="writer", settings_view=False):
    from agenticops.auth import AuthService
    is_admin, perms = grants(role, settings_view)
    user = AuthService.create_user(email=email, password=f"pw-{email}-0", is_admin=is_admin, permissions=perms)
    return user, AuthService.create_session(user.id)


def H(token):
    return {"Authorization": f"Bearer {token}"}


def _new(env, tok, **over):
    body = {"name": "local-llm", "preset": "litellm_proxy", "base_url": f"{env.fake.base}/v1",
            "api_key": "sk-API-SECRET-0001"}
    body.update(over)
    return env.client.post("/api/model-providers", headers=H(tok), json=body)


def test_crud_round_trip_and_masking(env):
    _, tok = _user("root", "admin")
    r = _new(env, tok)
    assert r.status_code == 201 and r.json()["has_api_key"] is True
    listed = env.client.get("/api/model-providers", headers=H(tok))
    assert listed.status_code == 200
    body = listed.json()
    assert [p["name"] for p in body["providers"]] == ["local-llm"]
    assert body["bedrock"]["enabled"] is True and body["can_edit"] is True
    assert {p["preset"] for p in body["presets"]} >= {"ollama", "openrouter", "vllm", "litellm_proxy", "sub2api"}
    r = env.client.patch("/api/model-providers/local-llm", headers=H(tok), json={"api_key": "****0001", "timeout_seconds": 90})
    assert r.status_code == 200 and r.json()["timeout_seconds"] == 90 and r.json()["has_api_key"] is True
    r = env.client.patch("/api/model-providers/local-llm", headers=H(tok), json={"clear_api_key": True})
    assert r.json()["has_api_key"] is False
    every = json.dumps([listed.json(), r.json()])
    assert "sk-API-SECRET-0001" not in every
    assert env.client.delete("/api/model-providers/local-llm", headers=H(tok)).status_code == 204
    assert env.client.get("/api/model-providers", headers=H(tok)).json()["providers"] == []


def test_refusals_have_codes(env):
    _, tok = _user("root", "admin")
    _new(env, tok)
    for body, code in (({"name": "local-llm"}, "name_taken"), ({"name": "bedrock"}, "reserved_name"),
                       ({"name": "x2", "base_url": "ftp://x"}, "invalid_base_url")):
        r = _new(env, tok, **body)
        assert r.status_code in (409, 422) and r.json()["detail"]["code"] == code
    assert env.client.patch("/api/model-providers/nope", headers=H(tok), json={}).json()["detail"]["code"] == "not_found"


def test_writes_need_an_admin(env):
    from agenticops.auth import AuthService
    root, admin_tok = _user("root", "admin")
    _, writer_tok = _user("ops", "writer")
    _, viewer_tok = _user("demo", "viewer")
    _, auditor_tok = _user("auditor", "viewer", settings_view=True)
    read_key = AuthService.create_api_key(user_id=root.id, name="ro", permissions=["read"])
    _new(env, admin_tok)
    writes = [("POST", "/api/model-providers", {"name": "other", "base_url": "http://h/v1"}),
              ("PATCH", "/api/model-providers/local-llm", {"timeout_seconds": 30}),
              ("DELETE", "/api/model-providers/local-llm", None),
              ("PUT", "/api/model-providers/bedrock", {"enabled": False}),
              ("POST", "/api/model-providers/local-llm/refresh-models", {}),
              ("POST", "/api/model-providers/local-llm/test", {"model_id": "fake-chat-1"})]
    for tok in (writer_tok, viewer_tok, read_key):
        for method, path, body in writes:
            r = env.client.request(method, path, headers=H(tok), json=body)
            assert r.status_code == 403, (tok, method, path, r.status_code)
    assert env.client.get("/api/model-providers", headers=H(viewer_tok)).status_code == 403
    assert env.client.get("/api/model-providers", headers=H(writer_tok)).status_code == 200      # as Settings is
    assert env.client.get("/api/model-providers", headers=H(auditor_tok)).status_code == 200


def test_delete_in_use_is_409_with_refs(env, monkeypatch):
    _, tok = _user("root", "admin")
    _new(env, tok)
    monkeypatch.setattr(env.settings, "agent_reporter_model_id", "local-llm::fake-chat-1")
    r = env.client.delete("/api/model-providers/local-llm", headers=H(tok))
    assert r.status_code == 409 and r.json()["detail"] == {
        "detail": "«local-llm» is in use by: agent_reporter_model_id", "code": "in_use", "refs": ["agent_reporter_model_id"]}


def test_bedrock_switch_returns_the_settings_that_point_at_it(env):
    _, tok = _user("root", "admin")
    r = env.client.put("/api/model-providers/bedrock", headers=H(tok), json={"enabled": False})
    assert r.status_code == 200 and r.json()["enabled"] is False and "agent_main_model_id" in r.json()["references"]
    assert env.client.get("/api/model-providers", headers=H(tok)).json()["bedrock"]["enabled"] is False
    assert env.client.put("/api/model-providers/bedrock", headers=H(tok), json={"enabled": "no"}).status_code == 422


def test_models_and_the_test_route_use_the_fake_server(env):
    _, tok = _user("root", "admin")
    _new(env, tok)
    r = env.client.post("/api/model-providers/local-llm/refresh-models", headers=H(tok))
    assert r.json() == {"added": 2, "updated": 0, "unchanged": 0, "error": None}
    # nothing is read off a model's name (review of 2.9.0): the embedding model is marked by an admin
    r = env.client.patch("/api/model-providers/local-llm/models/fake-embed-1", headers=H(tok), json={"purpose": "embedding"})
    assert r.status_code == 200 and r.json()["purpose"] == "embedding"
    models = env.client.get("/api/model-providers/local-llm/models?purpose=chat", headers=H(tok)).json()
    assert [m["model_id"] for m in models] == ["fake-chat-1"] and models[0]["tools"] is None
    r = env.client.post("/api/model-providers/local-llm/test", headers=H(tok), json={"model_id": "fake-chat-1"})
    assert r.status_code == 200 and r.json()["tools"]["ok"] is True
    m = env.client.get("/api/model-providers/local-llm/models?purpose=chat", headers=H(tok)).json()[0]
    assert m["tools"] is True and m["tools_probe"] == "passed"
    r = env.client.patch("/api/model-providers/local-llm/models/fake-chat-1", headers=H(tok), json={"context_window": 64000})
    assert r.status_code == 200 and r.json()["context_window"] == 64000 and r.json()["manual_fields"] == ["context_window"]
    r = env.client.post("/api/model-providers/local-llm/models", headers=H(tok), json={"model_id": "vendor/model:7b"})
    assert r.status_code == 201
    r = env.client.patch("/api/model-providers/local-llm/models/vendor/model:7b", headers=H(tok), json={"enabled": False})
    assert r.status_code == 200 and r.json()["enabled"] is False          # a model id with a slash reaches its row


def test_cli_list_and_test(env):
    from agenticops.cli.main import app as cli
    _, tok = _user("root", "admin")
    _new(env, tok)
    runner = CliRunner()
    out = runner.invoke(cli, ["providers", "list"])
    assert out.exit_code == 0 and "local-llm" in out.output and "bedrock" in out.output
    assert "sk-API-SECRET-0001" not in out.output
    out = runner.invoke(cli, ["providers", "test", "local-llm", "--model", "fake-chat-1"])
    assert out.exit_code == 0 and "tools" in out.output
    env.fake.tools_supported = False
    out = runner.invoke(cli, ["providers", "test", "local-llm", "--model", "fake-chat-1"])
    assert out.exit_code == 1 and "no tool call" in out.output
    out = runner.invoke(cli, ["providers", "test", "nope"])
    assert out.exit_code == 1


def test_a_model_write_drops_every_cached_model(env):
    """Turning Bedrock off (or editing a provider) drops what was built with the old answer: the chat agents of the IM
    bots and the knowledge base's embedding client — the cached Titan client kept calling Bedrock (final review)."""
    import agenticops.kb.embeddings as kb_emb
    from agenticops.im.session_manager import IMChatSessionManager
    _, tok = _user("root", "admin")
    im = IMChatSessionManager()
    im._agents["feishu:chat-1"] = object()
    kb_emb._embedding_client, kb_emb._client_initialized = object(), True
    assert env.client.put("/api/model-providers/bedrock", headers=H(tok), json={"enabled": False}).status_code == 200
    assert im._agents == {} and kb_emb._client_initialized is False
    kb_emb._client_initialized = True
    _new(env, tok)
    env.client.patch("/api/model-providers/local-llm", headers=H(tok), json={"timeout_seconds": 45})
    assert kb_emb._client_initialized is False


def test_keys_and_header_values_are_printable(env):
    """A key or header value with a control character is refused when written: the HTTP library's error would quote
    it whole (final review)."""
    _, tok = _user("root", "admin")
    r = _new(env, tok, api_key="sk-live\n0001")
    assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_key"
    r = _new(env, tok, extra_headers={"X-Token": "abc\tdef"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_headers"
