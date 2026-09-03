"""Claude 5 family on Bedrock — Opus 5 / Sonnet 5 / Fable 5.1.

The 5 family ships single-segment version ids ('claude-opus-5') alongside
two-segment ones ('claude-fable-5-1'). Both the cost key regex and the model
picker label regex previously required a major-minor pair, so Opus 5 and
Sonnet 5 fell through to a "Claude" label, a cost of 0, and the global
bedrock_window_size instead of their per-agent window tuning.

Also pins the extended-thinking request shape, which the 5 family changed:
`thinking.budget_tokens` is a 400 there, and adaptive thinking is a 400 on
pre-4.6 models — so the shape must follow the model.
"""

import pytest

from agenticops.agents.preamble import (
    _claude_version,
    bedrock_model_kwargs,
    effort_to_budget,
    is_anthropic_model,
    supports_adaptive_thinking,
    thinking_fields_for_budget,
)
from agenticops.config import (
    MODEL_WINDOW_DEFAULTS,
    settings,
    get_agent_model_config,
    get_agent_window_size,
    validate_agent_model_ids,
)
from agenticops.cost import compute_cost, normalize_model_key
from agenticops.services.model_service import _build_presets_from_bedrock


CLAUDE5_IDS = [
    "global.anthropic.claude-opus-5",
    "global.anthropic.claude-sonnet-5",
    "global.anthropic.claude-fable-5-1",
]


# ---------------------------------------------------------------------------
# Cost key normalization
# ---------------------------------------------------------------------------

class TestClaude5CostKeys:
    @pytest.mark.parametrize("mid,key", [
        ("anthropic.claude-opus-5", "claude-opus-5"),
        ("global.anthropic.claude-opus-5", "claude-opus-5"),
        ("us.anthropic.claude-sonnet-5", "claude-sonnet-5"),
        ("global.anthropic.claude-fable-5-1", "claude-fable-5-1"),
        ("global.anthropic.claude-fable-5", "claude-fable-5"),
        # a later dated/versioned respin must still collapse to the family key
        ("global.anthropic.claude-opus-5-v1:0", "claude-opus-5"),
    ])
    def test_normalize(self, mid, key):
        assert normalize_model_key(mid) == key

    def test_four_x_normalization_unchanged(self):
        """The optional-minor regex must not swallow the 4.x minor version."""
        assert normalize_model_key("global.anthropic.claude-opus-4-8") == "claude-opus-4-8"
        assert normalize_model_key("global.anthropic.claude-opus-4-6-v1") == "claude-opus-4-6"
        assert normalize_model_key(
            "global.anthropic.claude-haiku-4-5-20251001-v1:0") == "claude-haiku-4-5"

    @pytest.mark.parametrize("mid", CLAUDE5_IDS)
    def test_cost_nonzero(self, mid):
        """A missing rate silently bills 0 — the reason this family needs rows."""
        assert compute_cost(mid, {"input": 1_000_000, "output": 1_000_000}) > 0


# ---------------------------------------------------------------------------
# Window families
# ---------------------------------------------------------------------------

class TestClaude5Windows:
    @pytest.mark.parametrize("family", [
        "claude-opus-5", "claude-sonnet-5", "claude-fable-5-1",
    ])
    def test_family_registered(self, family):
        assert family in MODEL_WINDOW_DEFAULTS

    def test_specific_family_precedes_its_prefix(self):
        """get_agent_window_size is first-substring-wins, so a family that is a
        prefix of another must be listed after it (Fable 5.1 before Fable 5)."""
        order = list(MODEL_WINDOW_DEFAULTS)
        for i, family in enumerate(order):
            for other in order[i + 1:]:
                assert not other.startswith(family), (
                    f"{other!r} is shadowed by its prefix {family!r} — move it earlier"
                )

    @pytest.mark.parametrize("mid,family", [
        ("global.anthropic.claude-opus-5", "claude-opus-5"),
        ("global.anthropic.claude-sonnet-5", "claude-sonnet-5"),
        ("global.anthropic.claude-fable-5-1", "claude-fable-5-1"),
    ])
    def test_window_resolves_to_own_family(self, monkeypatch, mid, family):
        monkeypatch.setattr(settings, "agent_main_model_id", mid)
        monkeypatch.setattr(settings, "agent_main_window_size", 0)
        assert get_agent_window_size("main") == MODEL_WINDOW_DEFAULTS[family]["main"]

    def test_no_agent_falls_back_to_global_window(self):
        """Every shipped agent model id must match a known family."""
        assert validate_agent_model_ids() == []


# ---------------------------------------------------------------------------
# Model picker labels
# ---------------------------------------------------------------------------

class TestClaude5Presets:
    @staticmethod
    def _presets(*pairs):
        raw = [{"model_id": mid, "model_name": name, "provider": "anthropic"}
               for mid, name in pairs]
        return {p["label"]: p["value"] for p in _build_presets_from_bedrock(raw)}

    def test_single_segment_versions_get_distinct_labels(self):
        labels = self._presets(
            ("anthropic.claude-opus-5", "Claude Opus 5"),
            ("anthropic.claude-sonnet-5", "Claude Sonnet 5"),
            ("anthropic.claude-fable-5-1", "Claude Fable 5.1"),
        )
        assert labels["Opus 5"] == "global.anthropic.claude-opus-5"
        assert labels["Sonnet 5"] == "global.anthropic.claude-sonnet-5"
        assert labels["Fable 5.1"] == "global.anthropic.claude-fable-5-1"

    def test_four_x_labels_unchanged(self):
        labels = self._presets(
            ("anthropic.claude-opus-4-8", "Claude Opus 4.8"),
            ("anthropic.claude-haiku-4-5-20251001-v1:0", "Claude Haiku 4.5"),
        )
        assert "Opus 4.8" in labels
        assert "Haiku 4.5" in labels

    def test_latest_generation_sorts_first(self):
        raw = [{"model_id": mid, "model_name": mid, "provider": "anthropic"}
               for mid in ("anthropic.claude-opus-4-8", "anthropic.claude-opus-5")]
        assert [p["label"] for p in _build_presets_from_bedrock(raw)] == ["Opus 5", "Opus 4.8"]

    def test_unmatched_shape_uses_full_model_name(self):
        """'claude-3-5-sonnet-…' has no family-version shape; falling back to
        the first word of the name labelled every such model just "Claude"."""
        labels = self._presets(
            ("anthropic.claude-3-5-sonnet-20240620-v1:0", "Claude 3.5 Sonnet"),
            ("anthropic.claude-3-5-sonnet-20241022-v2:0", "Claude 3.5 Sonnet v2"),
        )
        assert "Claude 3.5 Sonnet" in labels
        assert "Claude 3.5 Sonnet v2" in labels
        assert "Claude" not in labels


# ---------------------------------------------------------------------------
# Capability gate — the 5 family is still Anthropic
# ---------------------------------------------------------------------------

class TestClaude5CapabilityGate:
    @pytest.mark.parametrize("mid", CLAUDE5_IDS)
    def test_recognized_as_anthropic(self, mid):
        assert is_anthropic_model(mid) is True

    @pytest.mark.parametrize("mid", CLAUDE5_IDS)
    def test_gets_cache_and_thinking(self, monkeypatch, mid):
        monkeypatch.setattr(settings, "bedrock_cache_enabled", True)
        fields = {"thinking": {"type": "enabled", "budget_tokens": 4096}}
        kw = bedrock_model_kwargs(mid, fields)
        assert "cache_config" in kw
        assert kw["additional_request_fields"] is fields


# ---------------------------------------------------------------------------
# Extended-thinking request shape
#
# Claude 4.6 replaced {"thinking":{"type":"enabled","budget_tokens":N}} with
# adaptive thinking + output_config.effort. Sending the old field to Opus
# 4.7/4.8/5, Sonnet 5 or Fable 5/5.1 is a 400; sending the new one to Haiku 4.5
# is also a 400. Boundary verified live against Bedrock us-east-1.
# ---------------------------------------------------------------------------

class TestThinkingRequestShape:
    @pytest.mark.parametrize("mid,expected", [
        ("global.anthropic.claude-opus-5", (5, 0)),
        ("global.anthropic.claude-sonnet-5", (5, 0)),
        ("global.anthropic.claude-fable-5-1", (5, 1)),
        ("global.anthropic.claude-opus-4-8", (4, 8)),
        ("global.anthropic.claude-opus-4-6-v1", (4, 6)),
        ("global.anthropic.claude-haiku-4-5-20251001-v1:0", (4, 5)),
        # no claude-<family>-<major> shape → unknown
        ("anthropic.claude-3-5-sonnet-20240620-v1:0", None),
        ("openai.gpt-oss-120b-1:0", None),
    ])
    def test_version_parse(self, mid, expected):
        assert _claude_version(mid) == expected

    @pytest.mark.parametrize("mid", [
        "global.anthropic.claude-opus-5",
        "global.anthropic.claude-sonnet-5",
        "global.anthropic.claude-fable-5-1",
        "global.anthropic.claude-fable-5",
        "global.anthropic.claude-opus-4-8",
        "global.anthropic.claude-opus-4-6-v1",   # accepts either; takes the modern one
        "global.anthropic.claude-sonnet-4-6",
    ])
    def test_adaptive_families(self, mid):
        assert supports_adaptive_thinking(mid) is True

    @pytest.mark.parametrize("mid", [
        "global.anthropic.claude-haiku-4-5-20251001-v1:0",  # rejects adaptive
        "anthropic.claude-3-5-sonnet-20240620-v1:0",
        "global.openai.gpt-5.6-terra",                       # not Anthropic at all
        "",
    ])
    def test_legacy_families(self, mid):
        assert supports_adaptive_thinking(mid) is False

    @pytest.mark.parametrize("mid", CLAUDE5_IDS)
    def test_claude5_gets_adaptive_not_budget_tokens(self, mid):
        fields = thinking_fields_for_budget(4096, 16384, mid)
        assert fields == {"thinking": {"type": "adaptive"},
                          "output_config": {"effort": "medium"}}
        assert "budget_tokens" not in fields["thinking"]

    def test_haiku_keeps_budget_tokens(self):
        fields = thinking_fields_for_budget(4096, 16384,
                                            "global.anthropic.claude-haiku-4-5-20251001-v1:0")
        assert fields == {"thinking": {"type": "enabled", "budget_tokens": 4096}}

    @pytest.mark.parametrize("preset,tier", [
        ("low", "low"), ("standard", "medium"), ("high", "high"),
        ("xhigh", "xhigh"), ("deep", "xhigh"), ("max", "max"),
    ])
    def test_preset_maps_to_own_effort_tier(self, preset, tier):
        """Each effort preset must land on its own Bedrock tier — including
        'max', whose 24576 is clamped under max_tokens before mapping."""
        max_tokens = 16384
        budget = effort_to_budget(preset, max_tokens)
        fields = thinking_fields_for_budget(budget, max_tokens, CLAUDE5_IDS[0])
        assert fields["output_config"]["effort"] == tier

    def test_every_emitted_tier_is_accepted_by_bedrock(self):
        valid = {"low", "medium", "high", "xhigh", "max"}
        for preset in settings.thinking_effort_presets:
            budget = effort_to_budget(preset, 16384) or 0
            fields = thinking_fields_for_budget(budget, 16384, CLAUDE5_IDS[0])
            if fields:
                assert fields["output_config"]["effort"] in valid

    def test_openai_still_translates_to_reasoning_effort(self):
        """OpenAI ids fall to the budget_tokens shape on purpose — that is what
        bedrock_model_kwargs reads to build their native reasoning_effort."""
        mid = "global.openai.gpt-5.6-terra"
        fields = thinking_fields_for_budget(4096, 16384, mid)
        assert fields == {"thinking": {"type": "enabled", "budget_tokens": 4096}}
        assert bedrock_model_kwargs(mid, fields) == {
            "additional_request_fields": {"reasoning_effort": "medium"}
        }

    def test_shipped_agent_models_never_get_a_rejected_shape(self, monkeypatch):
        """Drift guard: every agent's configured model must receive the shape
        its family accepts, whatever settings.yaml is set to."""
        monkeypatch.setattr(settings, "bedrock_cache_enabled", False)
        for agent in ("main", "scan", "detect", "rca", "sre", "executor", "reporter"):
            mid, max_tokens = get_agent_model_config(agent)
            fields = thinking_fields_for_budget(4096, max_tokens, mid)
            thinking_type = fields["thinking"]["type"]
            assert thinking_type == ("adaptive" if supports_adaptive_thinking(mid)
                                     else "enabled"), f"{agent} -> {mid}"


# ---------------------------------------------------------------------------
# settings.yaml sync guards
# ---------------------------------------------------------------------------

class TestClaude5SettingsSync:
    def test_aliases_present(self):
        aliases = settings.model_aliases
        assert aliases["opus"] == "global.anthropic.claude-opus-5"
        assert aliases["sonnet"] == "global.anthropic.claude-sonnet-5"
        assert aliases["fable"] == "global.anthropic.claude-fable-5-1"
        # versioned aliases keep the previous generation pinnable
        assert aliases["opus-4-8"] == "global.anthropic.claude-opus-4-8"
        assert aliases["opus-4-6"] == "global.anthropic.claude-opus-4-6-v1"

    def test_cost_table_has_claude5_families(self):
        table = settings.token_cost_table
        for key in ("claude-opus-5", "claude-sonnet-5", "claude-fable-5-1"):
            assert key in table, f"token_cost_table missing {key}"
            assert table[key]["input"] > 0
            assert table[key]["output"] > 0

    def test_defaults_upgraded(self):
        assert get_agent_model_config("main")[0] == "global.anthropic.claude-opus-5"
        assert get_agent_model_config("sre")[0] == "global.anthropic.claude-fable-5-1"

    def test_every_alias_has_cost_rates(self):
        """A pickable model with no rates bills 0 — catch drift between the
        alias list and the cost table."""
        table = settings.token_cost_table
        for alias, model_id in settings.model_aliases.items():
            assert normalize_model_key(model_id) in table, (
                f"alias {alias!r} -> {model_id!r} has no token_cost_table row"
            )
