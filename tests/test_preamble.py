"""Tests for agents/preamble.py, config optimizations, and skill XML truncation."""

import pytest
from unittest.mock import patch, MagicMock


# ── Preamble: build_system_prompt ────────────────────────────────────

class TestBuildSystemPrompt:
    """Tests for agents.preamble.build_system_prompt()."""

    def test_includes_account_preamble_by_default(self):
        from agenticops.agents.preamble import build_system_prompt, ACCOUNT_PREAMBLE
        result = build_system_prompt("BASE PROMPT", include_skills=False)
        assert ACCOUNT_PREAMBLE in result
        assert "BASE PROMPT" in result

    def test_excludes_account_preamble_when_disabled(self):
        from agenticops.agents.preamble import build_system_prompt, ACCOUNT_PREAMBLE
        result = build_system_prompt("BASE PROMPT", include_account=False, include_skills=False)
        assert ACCOUNT_PREAMBLE not in result
        assert "BASE PROMPT" in result

    def test_includes_output_rules(self):
        from agenticops.agents.preamble import build_system_prompt
        result = build_system_prompt("BASE", include_skills=False)
        assert "OUTPUT FORMAT RULES" in result

    def test_rca_agent_type_adds_rca_addenda(self):
        from agenticops.agents.preamble import build_system_prompt
        result = build_system_prompt("BASE", include_skills=False, agent_type="rca")
        assert "Root Cause" in result

    def test_sre_agent_type_adds_sre_addenda(self):
        from agenticops.agents.preamble import build_system_prompt
        result = build_system_prompt("BASE", include_skills=False, agent_type="sre")
        assert "Mode A" in result

    def test_skills_appended_when_enabled(self):
        from agenticops.agents.preamble import build_system_prompt
        mock_xml = '<available_skills>\n  <skill name="test">Test skill</skill>\n</available_skills>'
        with patch("agenticops.agents.preamble.settings") as mock_settings:
            mock_settings.skills_enabled = True
            with patch("agenticops.skills.loader.get_available_skills_xml", return_value=mock_xml):
                result = build_system_prompt("BASE", include_account=False)
                assert "<available_skills>" in result
                assert "AGENT SKILLS PROTOCOL" in result

    def test_skills_not_appended_when_disabled(self):
        from agenticops.agents.preamble import build_system_prompt
        with patch("agenticops.agents.preamble.settings") as mock_settings:
            mock_settings.skills_enabled = False
            result = build_system_prompt("BASE", include_account=False)
            assert "<available_skills>" not in result
            assert "AGENT SKILLS PROTOCOL" not in result


# ── Preamble: get_output_rules ───────────────────────────────────────

class TestGetOutputRules:
    """Output rules are fixed (single medium template since MVP-2.0.1)."""

    def test_generic_rules(self):
        from agenticops.agents.preamble import get_output_rules
        rules = get_output_rules()
        assert "~1500 tokens" in rules

    def test_rca_addenda_appended(self):
        from agenticops.agents.preamble import get_output_rules
        rules = get_output_rules(agent_type="rca")
        assert "Root Cause" in rules
        assert "Contributing Factors" in rules

    def test_sre_addenda_appended(self):
        from agenticops.agents.preamble import get_output_rules
        rules = get_output_rules(agent_type="sre")
        assert "Mode A" in rules

    def test_generic_no_addenda(self):
        from agenticops.agents.preamble import get_output_rules
        rules = get_output_rules(agent_type="generic")
        assert "Root Cause" not in rules
        assert "Mode A" not in rules

    def test_detail_level_machinery_gone(self):
        import agenticops.config as cfg
        assert not hasattr(cfg, "set_detail_level")
        assert not hasattr(cfg, "get_detail_level")
        assert not hasattr(cfg, "VALID_DETAIL_LEVELS")


# ── Loader: backward compat re-exports ────────────────────────────────

class TestLoaderBackwardCompat:
    """Verify that skills/loader.py re-exports from preamble."""

    def test_get_output_rules_importable(self):
        from agenticops.skills.loader import get_output_rules
        assert callable(get_output_rules)

    def test_build_prompt_with_skills_still_works(self):
        from agenticops.skills.loader import build_prompt_with_skills
        with patch("agenticops.agents.preamble.settings") as mock_settings:
            mock_settings.skills_enabled = False
            result = build_prompt_with_skills("BASE PROMPT")
            assert "BASE PROMPT" in result
            assert "OUTPUT FORMAT RULES" in result

    def test_output_rules_importable(self):
        from agenticops.skills.loader import _OUTPUT_RULES
        assert "OUTPUT FORMAT RULES" in _OUTPUT_RULES


# ── Skill XML Truncation ─────────────────────────────────────────────

class TestSkillXMLTruncation:
    """Tests for truncated skill descriptions in XML."""

    def test_long_description_truncated_to_80_chars(self):
        from agenticops.skills.loader import build_available_skills_xml, SkillMetadata
        from pathlib import Path
        long_desc = "A" * 200 + ". More details here."
        skill = SkillMetadata(
            name="test-skill",
            description=long_desc,
            path=Path("/tmp/fake"),
        )
        xml = build_available_skills_xml([skill])
        # Extract description from XML
        assert len(long_desc.split(".")[0][:80]) <= 80
        assert xml.count("<available_skills>") == 1
        # Full 200-char description should NOT appear
        assert long_desc not in xml

    def test_short_description_preserved(self):
        from agenticops.skills.loader import build_available_skills_xml, SkillMetadata
        from pathlib import Path
        skill = SkillMetadata(
            name="short",
            description="Short description. Extra.",
            path=Path("/tmp/fake"),
        )
        xml = build_available_skills_xml([skill])
        # Short descriptions (under _MAX_DESC_XML) are preserved in full
        assert "Short description. Extra." in xml

    def test_draft_skill_tagged(self):
        from agenticops.skills.loader import build_available_skills_xml, SkillMetadata
        from pathlib import Path
        skill = SkillMetadata(
            name="draft-skill",
            description="A draft skill. Details.",
            path=Path("/tmp/fake"),
            is_draft=True,
        )
        xml = build_available_skills_xml([skill])
        assert "[DRAFT]" in xml

    def test_empty_skills_returns_empty(self):
        from agenticops.skills.loader import build_available_skills_xml
        assert build_available_skills_xml([]) == ""


# ── Config: get_agent_window_size ────────────────────────────────────

class TestGetAgentWindowSize:
    """Tests for config.get_agent_window_size()."""

    def test_returns_override_when_set(self):
        from agenticops.config import get_agent_window_size
        with patch("agenticops.config.settings") as mock:
            mock.agent_rca_window_size = 60
            mock.bedrock_window_size = 40
            assert get_agent_window_size("rca") == 60

    def test_falls_back_to_global(self):
        from agenticops.config import get_agent_window_size
        with patch("agenticops.config.settings") as mock:
            mock.agent_scan_window_size = 0
            mock.bedrock_window_size = 40
            mock.agent_scan_model_id = ""
            mock.bedrock_model_id = "unknown-model"
            mock.agent_scan_max_tokens = 0
            mock.bedrock_max_tokens = 16384
            assert get_agent_window_size("scan") == 40

    def test_unknown_agent_falls_back_to_global(self):
        from agenticops.config import get_agent_window_size, settings
        # "unknown" has no agent_unknown_window_size field, so getattr returns 0
        # and it falls back to bedrock_window_size
        result = get_agent_window_size("unknown")
        assert result == settings.bedrock_window_size


# ── Config: executor smart model fields ──────────────────────────────

class TestExecutorSmartModelConfig:
    """Tests for executor_smart_model config fields."""

    def test_executor_smart_model_default_true(self):
        from agenticops.config import Settings
        s = Settings(
            _env_file=None,
            database_url="sqlite:///test.db",
        )
        assert s.executor_smart_model is True

    def test_executor_simple_model_id_default(self):
        from agenticops.config import Settings
        s = Settings(
            _env_file=None,
            database_url="sqlite:///test.db",
        )
        assert "sonnet" in s.executor_simple_model_id

    def test_token_cost_table_has_three_tiers(self):
        from agenticops.config import Settings
        s = Settings(
            _env_file=None,
            database_url="sqlite:///test.db",
        )
        assert "claude-opus-4-6" in s.token_cost_table
        assert "claude-sonnet-4-6" in s.token_cost_table
        assert "claude-haiku-4-5" in s.token_cost_table

    def test_token_cost_table_has_required_keys(self):
        from agenticops.config import Settings
        s = Settings(
            _env_file=None,
            database_url="sqlite:///test.db",
        )
        for tier, rates in s.token_cost_table.items():
            assert "input" in rates, f"{tier} missing 'input'"
            assert "output" in rates, f"{tier} missing 'output'"
            assert "cache_read" in rates, f"{tier} missing 'cache_read'"


# ── Config: per-agent window size fields ─────────────────────────────

class TestPerAgentWindowSizeConfig:
    """Tests for agent_*_window_size config fields."""

    def test_window_size_fields_exist(self):
        from agenticops.config import settings, AGENT_NAMES
        for name in AGENT_NAMES:
            val = getattr(settings, f"agent_{name}_window_size")
            assert isinstance(val, int), f"agent_{name}_window_size should be int, got {type(val)}"

    def test_rca_window_size_from_yaml(self):
        """RCA window size should be 0 (auto) via settings.yaml."""
        from agenticops.config import settings
        assert settings.agent_rca_window_size == 0

    def test_sre_window_size_from_yaml(self):
        """SRE window size should be -1 (unlimited) via settings.yaml."""
        from agenticops.config import settings
        assert settings.agent_sre_window_size == -1

    def test_executor_window_size_from_yaml(self):
        """Executor window size should be set to 100 via settings.yaml."""
        from agenticops.config import settings
        assert settings.agent_executor_window_size == 100


# ── Display: cost table from config ──────────────────────────────────

class TestDisplayCostTable:
    """Tests for display.py using config-driven cost table."""

    def test_format_detailed_uses_config_cost_table(self):
        from agenticops.cli.display import TokenUsage
        usage = TokenUsage()
        usage.add(input_tok=1000, output_tok=500, cache_read=200, agent_name="main")

        cost_table = {
            "claude-sonnet-4-6": {"input": 3.0, "output": 15.0, "cache_read": 0.30},
        }
        with patch("agenticops.config.get_agent_model_config", return_value=("global.anthropic.claude-sonnet-4-6", 16384)):
            with patch("agenticops.config.settings") as mock_settings:
                mock_settings.token_cost_table = cost_table
                result = usage.format_detailed()
                assert "Estimated Cost:" in result
                assert "$" in result


# ── Preamble: transient error detection ──────────────────────────────

class TestTransientDetection:
    """Tests for _is_transient_error in preamble."""

    def test_detects_throttling_exception_code(self):
        from agenticops.agents.preamble import _is_transient_error
        from botocore.exceptions import ClientError
        err = ClientError({"Error": {"Code": "ThrottlingException", "Message": "slow down"}}, "Converse")
        assert _is_transient_error(err) is True

    def test_detects_widened_substrings(self):
        from agenticops.agents.preamble import _is_transient_error
        for msg in ["Read timeout", "Service Unavailable", "request timeout", "throttled"]:
            assert _is_transient_error(Exception(msg)) is True, msg
        assert _is_transient_error(Exception("HTTP 503")) is True
        assert _is_transient_error(Exception("Rate limited: 429")) is True

    def test_non_transient_returns_false(self):
        from agenticops.agents.preamble import _is_transient_error
        assert _is_transient_error(Exception("ValidationException: bad input")) is False


class TestMemoryLoadErrorHandling:
    """Tests for agent-memory load exception handling in build_system_prompt."""

    def test_missing_file_is_swallowed(self):
        from agenticops.agents.preamble import build_system_prompt
        with patch("agenticops.memory.agent_memory.load_agent_memory", side_effect=FileNotFoundError("nope")):
            out = build_system_prompt("BASE", include_account=False, include_skills=False, agent_name="detect")
            assert "BASE" in out  # continues without memory

    def test_unexpected_error_is_logged_not_raised(self, caplog):
        import logging
        from agenticops.agents.preamble import build_system_prompt
        with patch("agenticops.memory.agent_memory.load_agent_memory", side_effect=ValueError("corrupt")):
            with caplog.at_level(logging.ERROR):
                out = build_system_prompt("BASE", include_account=False, include_skills=False, agent_name="detect")
            assert "BASE" in out
            assert any(r.levelno >= logging.ERROR for r in caplog.records)
