"""Unit tests for memory injection in ChatSessionManager.get_or_create().

Validates that cross-session memory (facts + experiences) from
MemoryService.build_memory_context() is injected into the Agent's system
prompt during session creation, and that failures are handled gracefully
without blocking agent creation.

**Validates: Requirements 6.4, 7.3, 7.4**
"""

import threading
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from agenticops.models import AgentMemoryFact
from agenticops.web.session_manager import ChatSessionManager, _format_facts_for_prompt


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
# ChatSessionManager.get_or_create — memory injection via build_memory_context
# ---------------------------------------------------------------------------


class TestGetOrCreateMemoryInjection:
    """Tests for memory injection during agent creation using build_memory_context."""

    def _make_manager(self):
        """Create a ChatSessionManager without starting cleanup."""
        mgr = ChatSessionManager.__new__(ChatSessionManager)
        mgr._agents = {}
        mgr._last_activity = {}
        mgr._lock = threading.Lock()
        mgr._session_locks = {}
        mgr._ttl = timedelta(minutes=30)
        mgr._cleanup_thread = None
        mgr._shutdown = False
        return mgr

    @patch("agenticops.web.session_manager._load_history_messages", return_value=[])
    @patch("agenticops.web.session_manager.create_main_agent")
    @patch("agenticops.web.memory_service.MemoryService.build_memory_context")
    def test_memory_context_injected_into_system_prompt(
        self, mock_build_ctx, mock_create_agent, mock_load_history
    ):
        mock_agent = MagicMock()
        mock_agent.system_prompt = "You are AgenticOps."
        mock_agent.messages = []
        mock_create_agent.return_value = mock_agent

        mock_build_ctx.return_value = (
            "[Cross-session memory - Known facts]\n"
            "- user_preference/preferred_region: us-west-2 (confidence: 0.95)\n\n"
            "[Cross-session memory - Related experiences]\n"
            "- [problem] EC2 instance unreachable (source: session abc-123, at: 2026-01-15 10:30:00)"
        )

        mgr = self._make_manager()
        agent = mgr.get_or_create("test-session-1")

        # build_memory_context called with session_id and initial_context
        mock_build_ctx.assert_called_once_with(
            session_id="test-session-1", initial_context=""
        )
        # Memory context appended to system prompt
        assert "[Cross-session memory - Known facts]" in agent.system_prompt
        assert "[Cross-session memory - Related experiences]" in agent.system_prompt
        assert "user_preference/preferred_region: us-west-2" in agent.system_prompt
        assert "EC2 instance unreachable" in agent.system_prompt
        # Original prompt is preserved
        assert agent.system_prompt.startswith("You are AgenticOps.")

    @patch("agenticops.web.session_manager._load_history_messages", return_value=[])
    @patch("agenticops.web.session_manager.create_main_agent")
    @patch("agenticops.web.memory_service.MemoryService.build_memory_context")
    def test_no_injection_when_empty_context(
        self, mock_build_ctx, mock_create_agent, mock_load_history
    ):
        mock_agent = MagicMock()
        mock_agent.system_prompt = "You are AgenticOps."
        mock_agent.messages = []
        mock_create_agent.return_value = mock_agent

        mock_build_ctx.return_value = ""

        mgr = self._make_manager()
        agent = mgr.get_or_create("test-session-2")

        # System prompt should remain unchanged
        assert agent.system_prompt == "You are AgenticOps."
        assert "[Cross-session memory" not in agent.system_prompt

    @patch("agenticops.web.session_manager._load_history_messages", return_value=[])
    @patch("agenticops.web.session_manager.create_main_agent")
    @patch("agenticops.web.memory_service.MemoryService.build_memory_context")
    def test_agent_created_even_when_memory_service_fails(
        self, mock_build_ctx, mock_create_agent, mock_load_history
    ):
        mock_agent = MagicMock()
        mock_agent.system_prompt = "You are AgenticOps."
        mock_agent.messages = []
        mock_create_agent.return_value = mock_agent

        mock_build_ctx.side_effect = RuntimeError("DB connection failed")

        mgr = self._make_manager()
        agent = mgr.get_or_create("test-session-3")

        # Agent should still be created and cached
        assert agent is mock_agent
        assert "test-session-3" in mgr._agents
        # System prompt unchanged on failure
        assert agent.system_prompt == "You are AgenticOps."

    @patch("agenticops.web.session_manager._load_history_messages", return_value=[])
    @patch("agenticops.web.session_manager.create_main_agent")
    @patch("agenticops.web.memory_service.MemoryService.build_memory_context")
    def test_cached_agent_skips_memory_injection(
        self, mock_build_ctx, mock_create_agent, mock_load_history
    ):
        mock_agent = MagicMock()
        mock_agent.system_prompt = "You are AgenticOps."
        mock_agent.messages = []
        mock_create_agent.return_value = mock_agent
        mock_build_ctx.return_value = ""

        mgr = self._make_manager()

        # First call creates the agent
        mgr.get_or_create("test-session-4")
        assert mock_create_agent.call_count == 1

        # Second call returns cached agent — no new agent creation
        mgr.get_or_create("test-session-4")
        assert mock_create_agent.call_count == 1
        # build_memory_context should only be called once (during creation)
        assert mock_build_ctx.call_count == 1

    @patch("agenticops.web.session_manager._load_history_messages", return_value=[])
    @patch("agenticops.web.session_manager.create_main_agent")
    @patch("agenticops.web.memory_service.MemoryService.build_memory_context")
    def test_facts_only_context_injected(
        self, mock_build_ctx, mock_create_agent, mock_load_history
    ):
        """When build_memory_context returns only facts (no experiences), it still injects."""
        mock_agent = MagicMock()
        mock_agent.system_prompt = "You are AgenticOps."
        mock_agent.messages = []
        mock_create_agent.return_value = mock_agent

        mock_build_ctx.return_value = (
            "[Cross-session memory - Known facts]\n"
            "- user_preference/preferred_region: us-west-2 (confidence: 0.95)"
        )

        mgr = self._make_manager()
        agent = mgr.get_or_create("test-session-5")

        assert "[Cross-session memory - Known facts]" in agent.system_prompt
        assert "user_preference/preferred_region: us-west-2" in agent.system_prompt

    @patch("agenticops.web.session_manager._load_history_messages", return_value=[])
    @patch("agenticops.web.session_manager.create_main_agent")
    @patch("agenticops.web.memory_service.MemoryService.build_memory_context")
    def test_experience_context_includes_session_id_and_timestamp(
        self, mock_build_ctx, mock_create_agent, mock_load_history
    ):
        """Validates Requirement 7.4: injected format includes source session_id and created_at."""
        mock_agent = MagicMock()
        mock_agent.system_prompt = "You are AgenticOps."
        mock_agent.messages = []
        mock_create_agent.return_value = mock_agent

        mock_build_ctx.return_value = (
            "[Cross-session memory - Related experiences]\n"
            "- [problem] EC2 unreachable (source: session sess-abc-123, at: 2026-03-15 14:30:00)\n"
            "- [solution] Restart instance (source: session sess-def-456, at: 2026-03-16 09:00:00)"
        )

        mgr = self._make_manager()
        agent = mgr.get_or_create("test-session-6")

        assert "source: session sess-abc-123" in agent.system_prompt
        assert "at: 2026-03-15 14:30:00" in agent.system_prompt
        assert "source: session sess-def-456" in agent.system_prompt
        assert "at: 2026-03-16 09:00:00" in agent.system_prompt
