"""Test a provider before saving it (MVP-2.9.0 review, Spec ③; the design: «保存之前可以先点「测试连接」»).

`POST /api/model-providers/test-draft` runs the connection test — list, one chat, one tool call — on what the form
holds, and writes nothing: no provider row, no last test, no model rows. A new provider is checked as a save would
check it; an edit is the stored provider with the form laid over it the way a save lays it (an empty or masked key
keeps the stored one, a masked header value keeps its value)."""
import pytest

from tests.test_model_providers_api import H, _new, _user, env  # noqa: F401 — the shared fixture

SECRET = "sk-API-SECRET-0001"


def _draft(env, tok, **body):
    return env.client.post("/api/model-providers/test-draft", headers=H(tok), json=body)


def _form(env, **over):
    body = {"name": "local-llm", "preset": "litellm_proxy", "base_url": f"{env.fake.base}/v1", "api_key": SECRET}
    body.update(over)
    return body


def _rows():
    from agenticops.llm.models import ModelProvider, ProviderModel
    from agenticops.models import get_db_session
    with get_db_session() as s:
        return ([(p.name, p.base_url, p.last_test) for p in s.query(ModelProvider).all()],
                s.query(ProviderModel).count())


def test_a_new_provider_is_tested_before_it_exists(env):
    _, tok = _user("root", "admin")
    r = _draft(env, tok, **_form(env))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["list"]["ok"] and body["chat"]["ok"] and body["tools"]["ok"]
    assert body["model_id"] == "fake-chat-1"            # the first CHAT model of the listing, not the embedding one
    assert _rows() == ([], 0)                            # nothing was written


def test_a_wrong_key_fails_and_nothing_is_stored(env):
    _, tok = _user("root", "admin")
    env.fake.require_key = "sk-the-right-one"
    body = _draft(env, tok, **_form(env, model_id="fake-chat-1")).json()
    assert body["list"]["ok"] is False and body["chat"]["ok"] is False
    assert SECRET not in str(body)
    assert _rows() == ([], 0)


def test_an_edit_uses_the_stored_key_and_leaves_the_stored_provider_alone(env):
    _, tok = _user("root", "admin")
    env.fake.require_key = SECRET
    assert _new(env, tok).status_code == 201
    before = _rows()
    ok = _draft(env, tok, provider="local-llm", base_url=f"{env.fake.base}/v1", api_key="", model_id="fake-chat-1").json()
    assert ok["chat"]["ok"] is True                      # an empty key field: the stored key
    masked = _draft(env, tok, provider="local-llm", api_key="****0001", model_id="fake-chat-1").json()
    assert masked["chat"]["ok"] is True                  # the mask the list shows: the stored key too
    bad = _draft(env, tok, provider="local-llm", base_url="http://127.0.0.1:9/v1", model_id="fake-chat-1").json()
    assert bad["list"]["ok"] is False and bad["chat"]["ok"] is False
    assert _rows() == before                             # neither the address nor a last test was written


def test_a_masked_header_value_keeps_the_stored_one(env):
    _, tok = _user("root", "admin")
    assert _new(env, tok, extra_headers={"X-Org": "org-secret-7"}).status_code == 201
    env.fake.requests.clear()
    r = _draft(env, tok, provider="local-llm", extra_headers={"X-Org": "****"}, model_id="fake-chat-1")
    assert r.status_code == 200
    assert env.fake.requests and all(q["headers"].get("x-org") == "org-secret-7" for q in env.fake.requests)


def test_a_draft_is_checked_as_a_save_would_check_it(env):
    _, tok = _user("root", "admin")
    assert _draft(env, tok, **_form(env, name="Bad Name")).json()["detail"]["code"] == "invalid_name"
    assert _draft(env, tok, **_form(env, base_url="ftp://x")).json()["detail"]["code"] == "invalid_base_url"
    assert _draft(env, tok, **_form(env, api_key="sk\tbad")).json()["detail"]["code"] == "invalid_key"
    assert _new(env, tok).status_code == 201
    taken = _draft(env, tok, **_form(env))
    assert taken.status_code == 409 and taken.json()["detail"]["code"] == "name_taken"
    assert _draft(env, tok, provider="nope", model_id="m").status_code == 404


def test_no_model_to_try_is_said(env):
    _, tok = _user("root", "admin")
    env.fake.models = ["fake-embed-1"]
    r = _draft(env, tok, **_form(env))
    assert r.status_code == 422 and r.json()["detail"]["code"] == "no_model"


def test_only_an_administrator_tests_a_draft(env):
    _, writer = _user("writer@x", "writer")
    assert _draft(env, writer, **_form(env)).status_code == 403
