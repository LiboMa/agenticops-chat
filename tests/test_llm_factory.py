"""The one place a model is built, and single-turn calls for the non-Bedrock protocols (MVP-2.9.0 N35 task 2).

`llm.factory.build_model(ref, max_tokens=, thinking_budget=)`: a Bedrock id builds exactly what the nine agent build
sites built before; `<provider>::<model>` builds Strands' OpenAIModel / AnthropicModel from the stored provider, with
no Bedrock-only request field. Anything that cannot be built is an explicit `ModelProviderUnavailable` — never a
quiet fall back to Bedrock. `llm.direct.complete_text` keeps `converse_text`'s contract for the two protocols, and
`converse_text` hands a reference to it.
"""
import time
from unittest.mock import patch

import boto3
import pytest

from tests.llm_fake_server import FakeLLMServer, add_model, add_provider, llm_db


@pytest.fixture
def db(tmp_path, monkeypatch):
    return llm_db(tmp_path, monkeypatch, "n35-factory.db")


@pytest.fixture
def boto():
    session = boto3.Session(region_name="us-east-1", aws_access_key_id="x", aws_secret_access_key="y")
    with patch("agenticops.config.get_bedrock_boto_session", return_value=session) as fn:
        yield fn


# ── Bedrock: unchanged ───────────────────────────────────────────────────────

@pytest.mark.parametrize("model_id,budget", [("global.anthropic.claude-opus-5-5", 4096),
                                             ("global.anthropic.claude-haiku-4-5-20251001-v1:0", 0),
                                             ("openai.gpt-oss-120b-1:0", 4096)])
def test_bedrock_ref_builds_exactly_what_it_built_before(db, boto, model_id, budget):
    from strands.models.bedrock import BedrockModel
    from agenticops.agents.preamble import bedrock_model_kwargs, thinking_fields_for_budget
    from agenticops.llm.factory import build_model
    before = BedrockModel(model_id=model_id, boto_session=boto.return_value, max_tokens=16000,
                          **bedrock_model_kwargs(model_id, thinking_fields_for_budget(budget, 16000, model_id)))
    after = build_model(model_id, max_tokens=16000, thinking_budget=budget)
    assert isinstance(after, BedrockModel)
    assert after.config == before.config
    assert after.aiops_ref == model_id


# ── the other two protocols ──────────────────────────────────────────────────

def test_openai_compatible_sends_no_bedrock_fields(db):
    from strands.models.openai import OpenAIModel
    from agenticops.llm.factory import build_model
    add_provider("local-llm", "http://h:4000/v1/", api_key="sk-local", extra_headers={"X-Title": "ops"})
    add_model("local-llm", "qwen3:32b", reasoning="none", context_window=32768)
    add_model("local-llm", "o-think", reasoning="openai_effort")
    m = build_model("local-llm::qwen3:32b", max_tokens=2000, thinking_budget=8192)
    assert isinstance(m, OpenAIModel) and m.aiops_ref == "local-llm::qwen3:32b"
    assert m.client_args["base_url"] == "http://h:4000/v1" and m.client_args["api_key"] == "sk-local"
    assert m.client_args["default_headers"] == {"X-Title": "ops"}
    assert m.config["model_id"] == "qwen3:32b" and m.config["params"] == {"max_tokens": 2000}
    assert "cache_config" not in m.config and m.config.get("context_window_limit") == 32768
    assert build_model("local-llm::o-think", max_tokens=2000, thinking_budget=8192).config["params"] == \
        {"max_tokens": 2000, "reasoning_effort": "high"}
    assert build_model("local-llm::o-think", max_tokens=2000, thinking_budget=0).config["params"] == {"max_tokens": 2000}
    for budget, effort in ((2048, "low"), (4096, "medium"), (24576, "high")):        # capped: no xhigh / max there
        assert build_model("local-llm::o-think", max_tokens=30000, thinking_budget=budget).config["params"][
            "reasoning_effort"] == effort


def test_a_provider_without_a_key_still_builds(db):
    from agenticops.llm.factory import build_model
    add_provider("ollama", "http://localhost:11434/v1")
    add_model("ollama", "llama3.1:8b")
    assert build_model("ollama::llama3.1:8b", max_tokens=100).client_args["api_key"]     # the SDK requires one


def test_anthropic_compatible_thinking_follows_the_claude_version(db):
    from strands.models.anthropic import AnthropicModel
    from agenticops.llm.factory import build_model
    add_provider("relay", "https://relay.example.com/", kind="anthropic_compatible", api_key="sk-relay")
    add_model("relay", "claude-sonnet-4-6", reasoning="anthropic_thinking")
    add_model("relay", "claude-3-5-haiku-20241022", reasoning="anthropic_thinking")
    add_model("relay", "plain-claude-alias", reasoning="none")
    m = build_model("relay::claude-sonnet-4-6", max_tokens=16000, thinking_budget=8192)
    assert isinstance(m, AnthropicModel) and m.config["max_tokens"] == 16000
    assert m.config["params"]["thinking"] == {"type": "adaptive"}
    assert m.config["params"]["output_config"] == {"effort": "high"}
    old = build_model("relay::claude-3-5-haiku-20241022", max_tokens=16000, thinking_budget=8192)
    assert old.config["params"]["thinking"] == {"type": "enabled", "budget_tokens": 8192}
    assert not build_model("relay::plain-claude-alias", max_tokens=16000, thinking_budget=8192).config.get("params")


@pytest.mark.parametrize("setup,ref,reason", [
    (lambda: None, "nowhere::m", "unknown_provider"),
    (lambda: (add_provider("off", "http://h/v1", enabled=False), add_model("off", "m")), "off::m", "provider_disabled"),
    (lambda: (add_provider("p1", "http://h/v1"), add_model("p1", "m", enabled=False)), "p1::m", "model_disabled"),
    (lambda: add_provider("p2", "http://h/v1"), "p2::not-listed", "unknown_model"),
])
def test_unavailable_is_explicit(db, setup, ref, reason):
    from agenticops.llm.factory import ModelProviderUnavailable, build_model
    setup()
    with patch("agenticops.config.get_bedrock_boto_session", side_effect=AssertionError("Bedrock was asked")):
        with pytest.raises(ModelProviderUnavailable) as e:
            build_model(ref, max_tokens=100)
    assert e.value.reason == reason and e.value.ref == ref and ref in str(e.value)


def test_bedrock_turned_off_is_explicit(db):
    from agenticops.llm import registry
    from agenticops.llm.factory import ModelProviderUnavailable, build_model
    from tests.llm_fake_server import ADMIN
    registry.set_bedrock_enabled(False, ADMIN)
    with patch("agenticops.config.get_bedrock_boto_session", side_effect=AssertionError("Bedrock was asked")):
        with pytest.raises(ModelProviderUnavailable) as e:
            build_model("global.anthropic.claude-opus-5-5", max_tokens=100)
    assert e.value.reason == "bedrock_off"


def test_ref_of_reads_what_the_factory_set(db, boto):
    from agenticops.llm.factory import build_model, ref_of
    add_provider("p3", "http://h/v1")
    add_model("p3", "m")
    assert ref_of(build_model("p3::m", max_tokens=10)) == "p3::m"
    assert ref_of(build_model("global.anthropic.claude-opus-5-5", max_tokens=10)) == "global.anthropic.claude-opus-5-5"


# ── single-turn calls ────────────────────────────────────────────────────────

@pytest.fixture
def fake():
    with FakeLLMServer() as server:
        yield server


@pytest.fixture
def both(db, fake):
    add_provider("oa", f"{fake.base}/v1", api_key="k1")
    add_model("oa", "fake-chat-1")
    add_provider("an", fake.base, kind="anthropic_compatible", api_key="k2")
    add_model("an", "claude-sonnet-4-6")
    return fake


@pytest.mark.parametrize("ref", ["oa::fake-chat-1", "an::claude-sonnet-4-6"])
def test_complete_text_against_the_fake_server(both, ref):
    from agenticops.agents.preamble import ModelReplyEmpty, ModelReplyTruncated
    from agenticops.llm.direct import complete_text
    text, usage, stop = complete_text(ref, "你好，世界", max_tokens=50)
    assert text == "echo: 你好，世界" and usage == {"input": 10, "output": 5} and stop in ("stop", "end_turn")
    both.stop = "length"
    with pytest.raises(ModelReplyTruncated):
        complete_text(ref, "x", max_tokens=5)
    both.stop, both.reply = "stop", ""
    with pytest.raises(ModelReplyEmpty):
        complete_text(ref, "x", max_tokens=5)


@pytest.mark.parametrize("ref", ["oa::fake-chat-1", "an::claude-sonnet-4-6"])
def test_a_slow_server_times_out_on_time(both, ref):
    from agenticops.llm.direct import complete_text
    both.delay = 3
    start = time.monotonic()
    with pytest.raises(Exception) as e:
        complete_text(ref, "x", max_tokens=5, read_timeout=1, total_attempts=1)
    assert time.monotonic() - start < 2.5
    assert "timeout" in type(e.value).__name__.lower() or "timed out" in str(e.value).lower()


def test_temperature_only_where_the_model_takes_it(both):
    from agenticops.llm.direct import complete_text
    complete_text("oa::fake-chat-1", "x", max_tokens=5, temperature=0)
    complete_text("an::claude-sonnet-4-6", "x", max_tokens=5, temperature=0)
    sent = [r["body"] for r in both.requests if r["method"] == "POST"]
    assert sent[0].get("temperature") == 0                # an OpenAI-compatible server takes it
    assert sent[1].get("temperature") == 0                # Claude 4.6 still takes it
    add_model("an", "claude-opus-5-5")
    complete_text("an::claude-opus-5-5", "x", max_tokens=5, temperature=0)
    assert "temperature" not in both.requests[-1]["body"]  # 4.7+ rejects it


def test_converse_text_dispatches_by_ref(both):
    from agenticops.agents.preamble import converse_text
    assert converse_text("oa::fake-chat-1", "hi", max_tokens=20)[0] == "echo: hi"
    with patch("agenticops.config.get_bedrock_boto_session") as session:
        session.return_value.client.return_value.converse.return_value = {
            "output": {"message": {"content": [{"text": "from bedrock"}]}}, "stopReason": "end_turn",
            "usage": {"inputTokens": 1, "outputTokens": 2}}
        assert converse_text("global.anthropic.claude-opus-5-5", "hi", max_tokens=20)[0] == "from bedrock"
        assert session.return_value.client.call_args[0][0] == "bedrock-runtime"


def test_media_capabilities_and_temperature_for_refs(db):
    from agenticops.agents.preamble import accepts_temperature, media_capabilities
    add_provider("openrouter", "https://openrouter.ai/api/v1", api_key="k")
    add_model("openrouter", "anthropic/claude-sonnet-4.5", supports_images=True, supports_documents=False)
    add_model("openrouter", "meta/llama", supports_images=False, supports_documents=False)
    caps = media_capabilities("openrouter::anthropic/claude-sonnet-4.5")
    assert caps.images is True and caps.documents is False          # not «claude in the name → documents»
    assert media_capabilities("openrouter::meta/llama") == (False, False)
    assert media_capabilities("openrouter::not-listed") == (False, False)
    assert media_capabilities("global.anthropic.claude-opus-5-5") == (True, True)   # Bedrock unchanged
    assert accepts_temperature("openrouter::meta/llama") is True
    assert accepts_temperature("global.anthropic.claude-opus-5-5") is False


# ── follow-ups (N35, after the review) ───────────────────────────────────────

def test_an_agents_model_retries_a_stuck_provider_once(db):
    """A provider that does not answer: the chat gives up after two tries (it was three, at 3× the timeout)."""
    from agenticops.llm.factory import build_model
    add_provider("p4", "http://h/v1")
    add_model("p4", "m")
    assert build_model("p4::m", max_tokens=10).client_args["max_retries"] == 1


def test_no_temperature_for_a_new_claude_behind_an_openai_proxy(db):
    """OpenRouter's «anthropic/claude-opus-4.8» refuses temperature as Bedrock's Claude 4.7+ does; a proxy alias with
    no version (LiteLLM's «claude-sonnet») and another family keep it."""
    from agenticops.agents.preamble import accepts_temperature
    add_provider("openrouter", "https://openrouter.ai/api/v1", api_key="k")
    for mid in ("anthropic/claude-opus-4.8", "anthropic/claude-sonnet-4.5", "claude-sonnet", "meta/llama-3"):
        add_model("openrouter", mid)
    assert accepts_temperature("openrouter::anthropic/claude-opus-4.8") is False
    assert accepts_temperature("openrouter::anthropic/claude-sonnet-4.5") is True
    assert accepts_temperature("openrouter::claude-sonnet") is True
    assert accepts_temperature("openrouter::meta/llama-3") is True
