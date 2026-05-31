"""Unit tests for cross-session memory helpers in ChatSessionManager.

Covers the _format_facts_for_prompt helper, the _validate_memory_context
guard, and (cycle② 2026-05-31) the freeze of the dead DB cross-session
memory injection in get_or_create.
"""

from agenticops.models import AgentMemoryFact
from agenticops.web.session_manager import _format_facts_for_prompt


# ---------------------------------------------------------------------------
# _format_facts_for_prompt (backward-compat helper)
# ---------------------------------------------------------------------------


class TestFormatFactsForPrompt:
    """Tests for the _format_facts_for_prompt helper."""

    def test_empty_list_returns_empty_string(self):
        assert _format_facts_for_prompt([]) == ""

    def test_single_fact_formatted(self):
        fact = AgentMemoryFact(
            category="user_preference",
            key="preferred_region",
            value="us-west-2",
            confidence_score=0.95,
            source_session_id="abc-123",
        )
        result = _format_facts_for_prompt([fact])
        assert "[Cross-session memory - Known facts]" in result
        assert "user_preference/preferred_region: us-west-2 (confidence: 0.95)" in result

    def test_multiple_facts_formatted(self):
        facts = [
            AgentMemoryFact(
                category="user_preference",
                key="preferred_region",
                value="us-west-2",
                confidence_score=0.95,
                source_session_id="abc-123",
            ),
            AgentMemoryFact(
                category="infra_context",
                key="naming_convention",
                value="kebab-case",
                confidence_score=0.80,
                source_session_id="def-456",
            ),
        ]
        result = _format_facts_for_prompt(facts)
        assert "[Cross-session memory - Known facts]" in result
        assert "user_preference/preferred_region: us-west-2 (confidence: 0.95)" in result
        assert "infra_context/naming_convention: kebab-case (confidence: 0.80)" in result

    def test_confidence_formatting_two_decimals(self):
        fact = AgentMemoryFact(
            category="team_info",
            key="team_name",
            value="platform",
            confidence_score=0.7,
            source_session_id="x",
        )
        result = _format_facts_for_prompt([fact])
        assert "(confidence: 0.70)" in result


# ---------------------------------------------------------------------------
# cycle② (2026-05-31): DB cross-session memory injection frozen.
#
# The former TestGetOrCreateMemoryInjection class exercised
# MemoryService.build_memory_context being injected into the agent system
# prompt during get_or_create. That DB path is now removed (dead code: the
# builder was always called with an empty query). The replacement guard test
# (test_get_or_create_no_longer_injects_db_memory) asserts the path is gone.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# F6/F7: Validation Guards for Memory Context
# ---------------------------------------------------------------------------


def test_get_or_create_no_longer_injects_db_memory():
    """get_or_create must NOT reference build_memory_context (DB path frozen)."""
    import inspect
    from agenticops.web.session_manager import ChatSessionManager
    src = inspect.getsource(ChatSessionManager.get_or_create)
    assert "build_memory_context" not in src
    assert "MemoryService" not in src


def test_non_string_memory_context_is_not_injected(monkeypatch):
    from agenticops.web import session_manager as sm
    # _validate_memory_context is the new guard
    assert sm._validate_memory_context({"unexpected": "dict"}) is None
    assert sm._validate_memory_context("  ") is None
    assert sm._validate_memory_context("real context") == "real context"


def test_oversized_memory_context_is_truncated():
    from agenticops.web import session_manager as sm
    big = "x" * 100_000
    out = sm._validate_memory_context(big)
    assert out is not None and len(out) <= sm._MAX_MEMORY_CONTEXT_CHARS
