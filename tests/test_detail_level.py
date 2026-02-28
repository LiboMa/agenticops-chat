"""Tests for the configurable detail level feature.

Tests config.py ContextVar-based detail level management,
loader.py output rule generation, and ChatContext.set_detail().
"""

import contextvars
from unittest.mock import patch

import pytest

from agenticops.config import (
    VALID_DETAIL_LEVELS,
    get_detail_level,
    set_detail_level,
    _detail_level_var,
)
from agenticops.cli.context import ChatContext
from agenticops.skills.loader import (
    build_prompt_with_skills,
    get_output_rules,
    _OUTPUT_RULES,
    _RCA_ADDENDA,
    _SRE_ADDENDA,
    _cached_skills,
    _cached_xml,
)


# ── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_detail_level():
    """Reset the detail level ContextVar after each test."""
    token = _detail_level_var.set("medium")
    yield
    _detail_level_var.reset(token)


@pytest.fixture
def clear_skill_cache(monkeypatch):
    """Clear skill caches so build_prompt_with_skills reads fresh state."""
    import agenticops.skills.loader as loader_mod
    monkeypatch.setattr(loader_mod, "_cached_skills", None)
    monkeypatch.setattr(loader_mod, "_cached_xml", None)


# ── config.py tests ──────────────────────────────────────────────────


class TestValidDetailLevels:
    def test_contains_concise(self):
        assert "concise" in VALID_DETAIL_LEVELS

    def test_contains_medium(self):
        assert "medium" in VALID_DETAIL_LEVELS

    def test_contains_detailed(self):
        assert "detailed" in VALID_DETAIL_LEVELS

    def test_exactly_three_levels(self):
        assert len(VALID_DETAIL_LEVELS) == 3


class TestGetDetailLevel:
    def test_default_is_medium(self):
        assert get_detail_level() == "medium"


class TestSetDetailLevel:
    def test_set_to_concise(self):
        set_detail_level("concise")
        assert get_detail_level() == "concise"

    def test_set_to_detailed(self):
        set_detail_level("detailed")
        assert get_detail_level() == "detailed"

    def test_set_to_medium(self):
        set_detail_level("concise")
        set_detail_level("medium")
        assert get_detail_level() == "medium"

    def test_returns_token(self):
        token = set_detail_level("concise")
        assert isinstance(token, contextvars.Token)

    def test_token_can_restore(self):
        token = set_detail_level("detailed")
        assert get_detail_level() == "detailed"
        _detail_level_var.reset(token)
        assert get_detail_level() == "medium"

    def test_invalid_level_raises_value_error(self):
        with pytest.raises(ValueError, match="Invalid detail level"):
            set_detail_level("verbose")

    def test_empty_string_raises_value_error(self):
        with pytest.raises(ValueError):
            set_detail_level("")


# ── loader.py output rules tests ────────────────────────────────────


class TestGetOutputRules:
    def test_returns_string(self):
        result = get_output_rules()
        assert isinstance(result, str)

    def test_contains_output_format_rules(self):
        result = get_output_rules()
        assert "OUTPUT FORMAT RULES" in result

    def test_medium_rules_by_default(self):
        result = get_output_rules()
        assert "medium mode" in result

    def test_concise_rules_when_set(self):
        set_detail_level("concise")
        result = get_output_rules()
        assert "concise mode" in result

    def test_detailed_rules_when_set(self):
        set_detail_level("detailed")
        result = get_output_rules()
        assert "detailed mode" in result

    def test_rca_addenda_included(self):
        result = get_output_rules("rca")
        assert "Root Cause" in result

    def test_sre_addenda_included(self):
        result = get_output_rules("sre")
        assert "fix plans" in result.lower() or "Mode A" in result

    def test_generic_no_addenda(self):
        rca_result = get_output_rules("rca")
        generic_result = get_output_rules("generic")
        assert len(generic_result) < len(rca_result)

    def test_rca_addenda_varies_by_level(self):
        set_detail_level("concise")
        concise_rules = get_output_rules("rca")
        set_detail_level("detailed")
        detailed_rules = get_output_rules("rca")
        assert concise_rules != detailed_rules

    def test_sre_addenda_varies_by_level(self):
        set_detail_level("concise")
        concise_rules = get_output_rules("sre")
        set_detail_level("detailed")
        detailed_rules = get_output_rules("sre")
        assert concise_rules != detailed_rules


class TestBuildPromptWithSkills:
    def test_injects_output_rules(self, clear_skill_cache):
        with patch("agenticops.skills.loader.settings") as mock_settings:
            mock_settings.skills_enabled = False
            result = build_prompt_with_skills("Base prompt")
            assert "Base prompt" in result
            assert "OUTPUT FORMAT RULES" in result

    def test_output_changes_with_level(self, clear_skill_cache):
        with patch("agenticops.skills.loader.settings") as mock_settings:
            mock_settings.skills_enabled = False
            set_detail_level("concise")
            concise_prompt = build_prompt_with_skills("Base prompt")
            set_detail_level("detailed")
            detailed_prompt = build_prompt_with_skills("Base prompt")
            assert "concise mode" in concise_prompt
            assert "detailed mode" in detailed_prompt
            assert concise_prompt != detailed_prompt

    def test_agent_type_affects_output(self, clear_skill_cache):
        with patch("agenticops.skills.loader.settings") as mock_settings:
            mock_settings.skills_enabled = False
            generic = build_prompt_with_skills("Base", "generic")
            rca = build_prompt_with_skills("Base", "rca")
            assert rca != generic
            assert "Root Cause" in rca


# ── ChatContext.set_detail() tests ──────────────────────────────────


class TestChatContextSetDetail:
    def test_accepts_concise(self):
        ctx = ChatContext()
        assert ctx.set_detail("concise") is True
        assert ctx.detail_level == "concise"

    def test_accepts_medium(self):
        ctx = ChatContext()
        ctx.set_detail("concise")
        assert ctx.set_detail("medium") is True
        assert ctx.detail_level == "medium"

    def test_accepts_detailed(self):
        ctx = ChatContext()
        assert ctx.set_detail("detailed") is True
        assert ctx.detail_level == "detailed"

    def test_rejects_invalid(self):
        ctx = ChatContext()
        assert ctx.set_detail("verbose") is False
        assert ctx.detail_level == "medium"  # unchanged

    def test_rejects_empty_string(self):
        ctx = ChatContext()
        assert ctx.set_detail("") is False

    def test_default_is_medium(self):
        ctx = ChatContext()
        assert ctx.detail_level == "medium"

    def test_sequential_changes(self):
        ctx = ChatContext()
        ctx.set_detail("concise")
        assert ctx.detail_level == "concise"
        ctx.set_detail("detailed")
        assert ctx.detail_level == "detailed"
        ctx.set_detail("medium")
        assert ctx.detail_level == "medium"

    def test_invalid_does_not_change_current(self):
        ctx = ChatContext()
        ctx.set_detail("concise")
        ctx.set_detail("invalid_level")
        assert ctx.detail_level == "concise"
