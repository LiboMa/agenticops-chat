"""OpenAI (ChatGPT-family) models on Bedrock — capability gating, cost, windows.

Covers MVP-2.5.x multi-provider support: gpt-oss-* (ON_DEMAND) and
gpt-5.6-* (inference-profile) models must be selectable everywhere a Claude
model is, while Anthropic-only request features (prompt caching cachePoints,
extended thinking) are never sent to them.
"""

import pytest

from agenticops.agents.preamble import bedrock_model_kwargs, is_anthropic_model
from agenticops.config import (
    MODEL_WINDOW_DEFAULTS,
    settings,
    get_agent_window_size,
    validate_agent_model_ids,
)
from agenticops.cost import compute_cost, normalize_model_key


# ---------------------------------------------------------------------------
# is_anthropic_model
# ---------------------------------------------------------------------------

class TestIsAnthropicModel:
    @pytest.mark.parametrize("mid", [
        "anthropic.claude-opus-4-6-v1",
        "global.anthropic.claude-opus-4-8",
        "us.anthropic.claude-sonnet-4-6",
        "global.anthropic.claude-fable-5",
    ])
    def test_anthropic_ids(self, mid):
        assert is_anthropic_model(mid) is True

    @pytest.mark.parametrize("mid", [
        "openai.gpt-oss-120b-1:0",
        "openai.gpt-oss-20b-1:0",
        "openai.gpt-oss-safeguard-120b",
        "global.openai.gpt-5.6-terra",
        "us.openai.gpt-5.6-sol",
    ])
    def test_openai_ids(self, mid):
        assert is_anthropic_model(mid) is False

    def test_empty_and_none(self):
        assert is_anthropic_model("") is False
        assert is_anthropic_model(None) is False


# ---------------------------------------------------------------------------
# bedrock_model_kwargs — the capability gate
# ---------------------------------------------------------------------------

class TestBedrockModelKwargs:
    def test_claude_gets_cache_kwargs(self, monkeypatch):
        monkeypatch.setattr(settings, "bedrock_cache_enabled", True)
        kw = bedrock_model_kwargs("global.anthropic.claude-opus-4-8")
        assert "cache_config" in kw
        assert kw["cache_tools"] == "default"

    def test_claude_thinking_fields_attached(self, monkeypatch):
        monkeypatch.setattr(settings, "bedrock_cache_enabled", True)
        fields = {"thinking": {"type": "enabled", "budget_tokens": 4096}}
        kw = bedrock_model_kwargs("global.anthropic.claude-opus-4-6-v1", fields)
        assert kw["additional_request_fields"] is fields

    def test_claude_cache_disabled_still_gets_thinking(self, monkeypatch):
        monkeypatch.setattr(settings, "bedrock_cache_enabled", False)
        fields = {"thinking": {"type": "enabled", "budget_tokens": 4096}}
        kw = bedrock_model_kwargs("global.anthropic.claude-opus-4-6-v1", fields)
        assert "cache_config" not in kw
        assert kw["additional_request_fields"] is fields

    def test_openai_gets_no_cache(self, monkeypatch):
        monkeypatch.setattr(settings, "bedrock_cache_enabled", True)
        assert bedrock_model_kwargs("openai.gpt-oss-120b-1:0") == {}

    def test_openai_thinking_dropped(self, monkeypatch):
        """Anthropic `thinking` request field must never reach an OpenAI model."""
        monkeypatch.setattr(settings, "bedrock_cache_enabled", True)
        fields = {"thinking": {"type": "enabled", "budget_tokens": 4096}}
        assert bedrock_model_kwargs("global.openai.gpt-5.6-terra", fields) == {}

    def test_none_thinking_fields_omitted_for_claude(self, monkeypatch):
        monkeypatch.setattr(settings, "bedrock_cache_enabled", True)
        kw = bedrock_model_kwargs("global.anthropic.claude-sonnet-4-6", None)
        assert "additional_request_fields" not in kw


# ---------------------------------------------------------------------------
# Cost normalization + rates
# ---------------------------------------------------------------------------

class TestOpenAICost:
    @pytest.mark.parametrize("mid,key", [
        ("openai.gpt-oss-120b-1:0", "gpt-oss-120b"),
        ("openai.gpt-oss-20b-1:0", "gpt-oss-20b"),
        ("openai.gpt-oss-safeguard-120b", "gpt-oss-safeguard-120b"),
        ("global.openai.gpt-5.6-terra", "gpt-5.6-terra"),
        ("us.openai.gpt-5.6-sol", "gpt-5.6-sol"),
    ])
    def test_normalize(self, mid, key):
        assert normalize_model_key(mid) == key

    def test_claude_normalization_unchanged(self):
        assert normalize_model_key("global.anthropic.claude-opus-4-6-v1") == "claude-opus-4-6"
        assert normalize_model_key(
            "global.anthropic.claude-haiku-4-5-20251001-v1:0") == "claude-haiku-4-5"

    def test_gpt_oss_cost_nonzero(self):
        cost = compute_cost("openai.gpt-oss-120b-1:0",
                            {"input": 1_000_000, "output": 1_000_000})
        assert cost == pytest.approx(0.15 + 0.60)

    def test_gpt56_cost_nonzero(self):
        cost = compute_cost("global.openai.gpt-5.6-sol", {"input": 1_000_000})
        assert cost > 0


# ---------------------------------------------------------------------------
# Window families + model-id validation
# ---------------------------------------------------------------------------

class TestOpenAIWindows:
    def test_families_registered(self):
        assert "gpt-5.6" in MODEL_WINDOW_DEFAULTS
        assert "gpt-oss" in MODEL_WINDOW_DEFAULTS

    def test_window_resolves_for_gpt_oss(self, monkeypatch):
        monkeypatch.setattr(settings, "agent_scan_model_id", "openai.gpt-oss-120b-1:0")
        monkeypatch.setattr(settings, "agent_scan_window_size", 0)
        assert get_agent_window_size("scan") == MODEL_WINDOW_DEFAULTS["gpt-oss"]["scan"]

    def test_window_resolves_for_gpt56_profile_id(self, monkeypatch):
        monkeypatch.setattr(settings, "agent_reporter_model_id", "global.openai.gpt-5.6-luna")
        monkeypatch.setattr(settings, "agent_reporter_window_size", 0)
        assert get_agent_window_size("reporter") == MODEL_WINDOW_DEFAULTS["gpt-5.6"]["reporter"]

    def test_validate_agent_model_ids_accepts_openai(self, monkeypatch):
        monkeypatch.setattr(settings, "agent_scan_model_id", "openai.gpt-oss-20b-1:0")
        warnings = validate_agent_model_ids()
        assert not any("agent_scan_model_id" in w for w in warnings)


# ---------------------------------------------------------------------------
# settings.yaml sync guards
# ---------------------------------------------------------------------------

class TestSettingsSync:
    def test_aliases_present(self):
        aliases = settings.model_aliases
        assert aliases.get("gpt-oss-120b") == "openai.gpt-oss-120b-1:0"
        assert aliases.get("gpt-oss-20b") == "openai.gpt-oss-20b-1:0"
        for name in ("gpt-5.6-terra", "gpt-5.6-luna", "gpt-5.6-sol"):
            assert aliases.get(name) == f"global.openai.{name}"

    def test_cost_table_has_openai_families(self):
        table = settings.token_cost_table
        for key in ("gpt-oss-120b", "gpt-oss-20b", "gpt-5.6-terra",
                    "gpt-5.6-luna", "gpt-5.6-sol"):
            assert key in table, f"token_cost_table missing {key}"
            assert table[key]["input"] > 0
            assert table[key]["output"] > 0
