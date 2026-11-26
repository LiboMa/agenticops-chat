"""The models a provider offers and the connection test (MVP-2.9.0 N35 task 3).

`catalog.refresh` reads a provider's model list (OpenAI-compatible `GET {base}/models` — plain, OpenRouter with prices,
context length and tool support, vLLM with `max_model_len` — or Anthropic-compatible `GET {base}/v1/models`) and keeps
the rows: what an admin set by hand survives a refresh, a failed read keeps what there was. `probe.test` reads the
list, sends a short chat and one tool call, and stores the outcome without overwriting what an admin set.
"""
import time

import pytest

from tests.llm_fake_server import ADMIN, FakeLLMServer, add_model, add_provider, llm_db


@pytest.fixture
def fake(tmp_path, monkeypatch):
    llm_db(tmp_path, monkeypatch, "n35-catalog.db")
    with FakeLLMServer() as server:
        yield server


def _rows(provider):
    from agenticops.llm import catalog
    return {m.model_id: m for m in catalog.list_models(provider)}


# ── reading a list ───────────────────────────────────────────────────────────

def test_refresh_parses_a_plain_listing(fake):
    from agenticops.llm import catalog
    add_provider("plain", f"{fake.base}/v1")
    assert catalog.refresh("plain", ADMIN) == {"added": 2, "updated": 0, "unchanged": 0, "error": None}
    rows = _rows("plain")
    # no list field says what a model is for, and the name is not read (review of 2.9.0, Standards 1): both are chat
    # models until an admin marks the embedding one
    assert rows["fake-chat-1"].purpose == "chat" and rows["fake-embed-1"].purpose == "chat"
    assert rows["fake-chat-1"].accepts_temperature is None and rows["fake-chat-1"].prompt_cache is None
    assert rows["fake-chat-1"].supports_tools is None and rows["fake-chat-1"].context_window is None
    assert catalog.refresh("plain", ADMIN) == {"added": 0, "updated": 0, "unchanged": 2, "error": None}


def test_refresh_reads_openrouter_prices_context_and_tools(fake):
    from agenticops.llm import catalog
    fake.list_shape = "openrouter"
    add_provider("openrouter", f"{fake.base}/v1", api_key="sk-or")
    catalog.refresh("openrouter", ADMIN)
    chat, embed = _rows("openrouter")["fake-chat-1"], _rows("openrouter")["fake-embed-1"]
    assert chat.context_window == 131072 and chat.label == "Fake fake-chat-1"
    assert chat.price_input == pytest.approx(3.0) and chat.price_output == pytest.approx(15.0)
    assert chat.supports_tools is True and embed.supports_tools is False
    assert chat.accepts_temperature is True and embed.accepts_temperature is False    # its supported_parameters
    assert chat.supports_images is True
    assert fake.requests[-1]["headers"]["authorization"] == "Bearer sk-or"


def test_refresh_reads_vllm_max_model_len(fake):
    from agenticops.llm import catalog
    fake.list_shape = "vllm"
    add_provider("vllm", f"{fake.base}/v1")
    catalog.refresh("vllm", ADMIN)
    assert _rows("vllm")["fake-chat-1"].context_window == 32768


def test_refresh_reads_an_anthropic_listing(fake):
    from agenticops.llm import catalog
    fake.models = ["claude-sonnet-4-6"]
    add_provider("relay", fake.base, kind="anthropic_compatible", api_key="sk-rel")
    catalog.refresh("relay", ADMIN)
    row = _rows("relay")["claude-sonnet-4-6"]
    assert row.label == "CLAUDE-SONNET-4-6" and row.purpose == "chat"
    sent = fake.requests[-1]
    assert sent["path"] == "/v1/models" and sent["headers"]["anthropic-version"] and sent["headers"]["x-api-key"] == "sk-rel"


def test_manual_fields_survive_a_refresh(fake):
    from agenticops.llm import catalog
    fake.list_shape = "openrouter"
    add_provider("openrouter", f"{fake.base}/v1", api_key="sk-or")
    catalog.refresh("openrouter", ADMIN)
    catalog.patch_model("openrouter", "fake-chat-1", {"context_window": 8000, "supports_tools": False}, ADMIN)
    catalog.refresh("openrouter", ADMIN)                         # the same list says 131072 and tools again
    row = _rows("openrouter")["fake-chat-1"]
    assert row.context_window == 8000 and row.supports_tools is False          # the admin's values stand
    assert set(row.manual_fields) == {"context_window", "supports_tools"}
    fake.list_shape = "plain"
    catalog.refresh("openrouter", ADMIN)
    assert _rows("openrouter")["fake-chat-1"].price_input == pytest.approx(3.0)  # not in the new list: kept


def test_listing_failure_keeps_the_models(fake):
    from agenticops.llm import catalog
    add_provider("plain", f"{fake.base}/v1", api_key="sk-good")
    fake.require_key = "sk-good"
    catalog.refresh("plain", ADMIN)
    fake.require_key = "other"
    out = catalog.refresh("plain", ADMIN)
    assert out["error"] and "401" in out["error"] and "sk-good" not in out["error"]
    assert set(_rows("plain")) == {"fake-chat-1", "fake-embed-1"}


def test_add_and_patch_by_hand(fake):
    from agenticops.llm import catalog, registry
    add_provider("sub", fake.base, kind="anthropic_compatible", api_key="k")
    catalog.add_manual("sub", {"model_id": "claude-opus-5-5", "context_window": 200000, "supports_tools": True,
                               "reasoning": "anthropic_adaptive_summarized", "price_input": 5, "price_output": 25},
                      ADMIN)
    row = _rows("sub")["claude-opus-5-5"]
    assert row.source == "manual" and row.reasoning == "anthropic_adaptive_summarized" and row.price_output == 25
    with pytest.raises(registry.ProviderError) as e:
        catalog.add_manual("sub", {"model_id": "claude-opus-5-5"}, ADMIN)
    assert e.value.code == "model_exists"
    for bad in ({"reasoning": "magic"}, {"reasoning": "anthropic_thinking"}, {"purpose": "vision"},
                {"context_window": -1}, {"price_input": -2}):
        with pytest.raises(registry.ProviderError) as e:
            catalog.patch_model("sub", "claude-opus-5-5", bad, ADMIN)
        assert e.value.code == "invalid_model_field"


def test_a_model_in_use_cannot_be_turned_off(fake, monkeypatch):
    from agenticops.config import settings
    from agenticops.llm import catalog, registry
    add_provider("plain", f"{fake.base}/v1")
    catalog.refresh("plain", ADMIN)
    monkeypatch.setattr(settings, "bedrock_model_id_cheap", "plain::fake-chat-1")
    with pytest.raises(registry.ProviderError) as e:
        catalog.patch_model("plain", "fake-chat-1", {"enabled": False}, ADMIN)
    assert e.value.code == "in_use" and e.value.extra == {"refs": ["bedrock_model_id_cheap"]}
    catalog.patch_model("plain", "fake-embed-1", {"enabled": False}, ADMIN)
    assert _rows("plain")["fake-embed-1"].enabled is False


def test_all_presets_lists_enabled_models_of_enabled_providers(fake):
    from agenticops.llm import catalog, registry
    fake.list_shape = "openrouter"
    add_provider("openrouter", f"{fake.base}/v1", api_key="k", display_name="OpenRouter")
    catalog.refresh("openrouter", ADMIN)
    catalog.patch_model("openrouter", "fake-embed-1", {"purpose": "embedding"}, ADMIN)    # an admin says what it is
    add_provider("off", f"{fake.base}/v1", enabled=False)
    add_model("off", "m1")
    presets = catalog.all_presets()
    assert [p["value"] for p in presets] == ["openrouter::fake-chat-1"]
    p = presets[0]
    assert p["provider"] == "openrouter" and p["provider_label"] == "OpenRouter" and p["purpose"] == "chat"
    assert p["capabilities"] == {"tools": True, "images": True, "documents": False, "reasoning": "none"}
    assert p["priced"] is True and p["context_window"] == 131072
    assert [p["value"] for p in catalog.all_presets(purpose="embedding")] == ["openrouter::fake-embed-1"]


# ── the connection test ──────────────────────────────────────────────────────

def test_probe_reports_each_step(fake):
    from agenticops.llm import catalog, probe, registry
    add_provider("plain", f"{fake.base}/v1")
    catalog.refresh("plain", ADMIN)
    out = probe.test("plain", "fake-chat-1")
    assert out["list"]["ok"] and out["list"]["count"] == 2
    assert out["chat"]["ok"] and out["tools"]["ok"]
    assert all(isinstance(out[k]["ms"], int) for k in ("list", "chat", "tools"))
    row = _rows("plain")["fake-chat-1"]
    assert row.tools_probe == "passed" and row.supports_tools is None             # the probe is its own field
    assert catalog.effective_tools(row) is True
    assert {r["path"] for r in fake.requests} >= {"/v1/models", "/v1/chat/completions"}
    assert [r for r in fake.requests if r["body"] and r["body"].get("tools")]    # one request carried a tool
    assert registry.list_public()[0]["last_test"]["model_id"] == "fake-chat-1"


def test_probe_records_a_model_that_does_not_call_tools(fake):
    from agenticops.llm import catalog, probe
    add_provider("plain", f"{fake.base}/v1")
    catalog.refresh("plain", ADMIN)
    catalog.patch_model("plain", "fake-chat-1", {"supports_tools": True}, ADMIN)
    fake.tools_supported = False
    out = probe.test("plain", "fake-chat-1")
    assert out["chat"]["ok"] and not out["tools"]["ok"] and "no tool call" in out["tools"]["error"]
    row = _rows("plain")["fake-chat-1"]
    assert row.tools_probe == "failed" and row.supports_tools is True             # the admin's value stands


def test_probe_works_before_the_list_is_read(fake):
    from agenticops.llm import probe
    add_provider("anth", fake.base, kind="anthropic_compatible", api_key="k")
    out = probe.test("anth", "claude-sonnet-4-6")
    assert out["list"]["ok"] and out["chat"]["ok"] and out["tools"]["ok"]


def test_probe_times_out_on_time(fake, monkeypatch):
    from agenticops.config import settings
    from agenticops.llm import probe
    monkeypatch.setattr(settings.model_providers, "test_timeout_seconds", 5)
    add_provider("slow", f"{fake.base}/v1", timeout_seconds=5)
    fake.delay = 7
    start = time.monotonic()
    out = probe.test("slow", "fake-chat-1")
    assert time.monotonic() - start < 15                  # list is a GET (no delay); chat and tools time out
    assert not out["chat"]["ok"] and "timed out" in out["chat"]["error"]


def test_a_wrong_key_is_said_without_the_key(fake):
    from agenticops.llm import probe
    add_provider("plain", f"{fake.base}/v1", api_key="sk-WRONG-1234")
    fake.require_key = "sk-right"
    out = probe.test("plain", "fake-chat-1")
    assert not out["list"]["ok"] and "authentication failed" in out["list"]["error"]
    assert "sk-WRONG-1234" not in str(out)


def test_probe_needs_a_model(fake):
    from agenticops.llm import probe, registry
    add_provider("empty", f"{fake.base}/v1")
    with pytest.raises(registry.ProviderError) as e:
        probe.test("empty", None)
    assert e.value.code == "no_model"


def test_an_unclassified_error_says_its_kind_not_its_text():
    """An error the classifier does not know is named by its class — its text can quote a key or header value."""
    from types import SimpleNamespace
    from agenticops.llm import catalog
    exc = ValueError("Illegal header value b'Bearer sk-live-SECRET-9999'")
    text = catalog.describe_error(exc, SimpleNamespace(api_key="other"))
    assert "SECRET" not in text and "ValueError" in text


# ── follow-ups (N35, after the review) ───────────────────────────────────────

def test_the_tool_step_has_room_and_says_when_it_was_cut(fake):
    """A think-first model spends tokens before it calls the tool: the step gives it room, and an answer cut at the
    limit is said as such — not «the model answered in text»."""
    from agenticops.llm import catalog, probe
    add_provider("plain", f"{fake.base}/v1")
    catalog.refresh("plain", ADMIN)
    probe.test("plain", "fake-chat-1")
    tool_request = [r["body"] for r in fake.requests if r["body"] and r["body"].get("tools")][-1]
    assert tool_request["max_tokens"] >= 512
    fake.tools_supported, fake.stop = False, "length"
    out = probe.test("plain", "fake-chat-1")
    assert not out["tools"]["ok"] and "output limit" in out["tools"]["error"]


def test_a_listing_with_a_repeated_id_reads_it_once(fake):
    from agenticops.llm import catalog
    fake.models = ["fake-chat-1", "fake-chat-1", "fake-embed-1"]
    add_provider("plain", f"{fake.base}/v1")
    assert catalog.refresh("plain", ADMIN) == {"added": 2, "updated": 0, "unchanged": 0, "error": None}


def test_startup_refreshes_the_enabled_providers_only(fake):
    """At startup the enabled providers' model lists are read again (the spec); a turned-off one is not contacted, and
    one that cannot be read keeps its models and stops nothing."""
    from agenticops.llm import catalog
    add_provider("on", f"{fake.base}/v1")
    add_provider("off", "http://127.0.0.1:9/v1", enabled=False)
    add_provider("down", "http://127.0.0.1:9/v1", timeout_seconds=5)
    out = catalog.refresh_enabled()
    assert set(out) == {"on", "down"} and out["on"]["added"] == 2 and out["down"]["error"]
    assert {r["path"] for r in fake.requests} == {"/v1/models"}


def test_the_app_starts_the_refresh_in_the_background():
    import inspect
    from agenticops.web import app as webapp
    source = inspect.getsource(webapp.lifespan)
    import re
    assert re.search(r"Thread\(target=refresh_enabled[^)]*daemon=True", source)


def test_a_refresh_keeps_a_purpose_the_list_does_not_say(fake):
    """A row marked as an embedding model (before this rule, or by hand) stays one: a refresh writes only what the
    list carries."""
    from agenticops.llm import catalog
    from agenticops.llm.models import ProviderModel
    from agenticops.models import get_db_session
    add_provider("plain", f"{fake.base}/v1")
    catalog.refresh("plain", ADMIN)
    with get_db_session() as s:
        s.query(ProviderModel).filter_by(provider="plain", model_id="fake-embed-1").one().purpose = "embedding"
    catalog.refresh("plain", ADMIN)
    assert _rows("plain")["fake-embed-1"].purpose == "embedding"


def test_a_model_added_by_hand_is_a_chat_model_unless_said(fake):
    from agenticops.llm import catalog
    add_provider("plain", f"{fake.base}/v1")
    assert catalog.add_manual("plain", {"model_id": "nomic-embed-text"}, ADMIN).purpose == "chat"
    assert catalog.add_manual("plain", {"model_id": "bge-m3", "purpose": "embedding"}, ADMIN).purpose == "embedding"


def test_temperature_and_prompt_cache_are_set_by_hand(fake):
    from agenticops.llm import catalog
    add_provider("plain", f"{fake.base}/v1")
    catalog.refresh("plain", ADMIN)
    m = catalog.patch_model("plain", "fake-chat-1", {"accepts_temperature": True, "prompt_cache": False}, ADMIN)
    assert m.accepts_temperature is True and m.prompt_cache is False
    assert set(m.manual_fields) >= {"accepts_temperature", "prompt_cache"}
    back = catalog.patch_model("plain", "fake-chat-1", {"accepts_temperature": None, "prompt_cache": None}, ADMIN)
    assert back.accepts_temperature is None and back.prompt_cache is None             # «not known» / the platform's
    catalog.refresh("plain", ADMIN)
    assert _rows("plain")["fake-chat-1"].accepts_temperature is None
