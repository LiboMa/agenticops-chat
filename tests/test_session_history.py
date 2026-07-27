"""Tests for session history restoration in ChatSessionManager."""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from agenticops.web.session_manager import _load_history_messages, _MAX_MSG_CHARS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_msg(role: str, content: str, tool_calls=None, minutes_ago: int = 0, token_usage=None):
    """Create a mock ChatMessage row."""
    m = MagicMock()
    m.role = role
    m.content = content
    m.tool_calls = tool_calls
    m.token_usage = token_usage
    m.created_at = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return m


def _make_session_row(pk: int = 1, session_id: str = "test-session"):
    row = MagicMock()
    row.id = pk
    row.session_id = session_id
    return row


def _make_summary(summary_text: str, minutes_ago: int = 0):
    """Create a mock SessionSummary row."""
    s = MagicMock()
    s.summary_text = summary_text
    s.created_at = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return s


def _patch_db(session_row, message_rows, summary_rows=None):
    """Return a context-manager mock for get_db_session + query chain."""
    if summary_rows is None:
        summary_rows = []

    class FakeQuery:
        def __init__(self, model):
            self._model = model

        def filter(self, *args):
            # ChatSession query returns session_row; ChatMessage returns message_rows
            name = self._model.__name__
            if name == "ChatSession":
                self._result = session_row
            elif name == "SessionSummary":
                self._result = summary_rows
            else:
                self._result = message_rows
            return self

        def first(self):
            return self._result

        def order_by(self, *args):
            return self

        def limit(self, n):
            self._result = self._result[:n] if self._result else []
            return self

        def all(self):
            return self._result if self._result else []

    class FakeDb:
        def query(self, model):
            return FakeQuery(model)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    return patch("agenticops.models.get_db_session", return_value=FakeDb())


# ---------------------------------------------------------------------------
# Tests for _load_history_messages
# ---------------------------------------------------------------------------

class TestLoadHistoryMessages:

    def test_empty_session_returns_empty(self):
        """No ChatSession row → empty list."""
        with _patch_db(None, []):
            result = _load_history_messages("nonexistent", 20)
        assert result == []

    def test_no_messages_returns_empty(self):
        """Session exists but no messages → empty list."""
        with _patch_db(_make_session_row(), []):
            result = _load_history_messages("test-session", 20)
        assert result == []

    def test_basic_user_assistant_pair(self):
        """Simple user/assistant pair converts correctly."""
        msgs = [
            _make_msg("user", "hello", minutes_ago=2),
            _make_msg("assistant", "hi there", minutes_ago=1),
        ]
        # DB returns DESC order, function reverses
        with _patch_db(_make_session_row(), list(reversed(msgs))):
            result = _load_history_messages("test-session", 20)
        assert len(result) == 2
        assert result[0]["role"] == "user"
        assert result[0]["content"] == [{"text": "hello"}]
        assert result[1]["role"] == "assistant"
        assert result[1]["content"] == [{"text": "hi there"}]

    def test_skips_empty_messages(self):
        """Empty content messages are skipped."""
        msgs = [
            _make_msg("user", "hello", minutes_ago=3),
            _make_msg("assistant", "", minutes_ago=2),
            _make_msg("assistant", "real reply", minutes_ago=1),
        ]
        with _patch_db(_make_session_row(), list(reversed(msgs))):
            result = _load_history_messages("test-session", 20)
        assert len(result) == 2
        assert result[0]["role"] == "user"
        assert result[1]["role"] == "assistant"
        assert result[1]["content"][0]["text"] == "real reply"

    def test_keeps_failed_turn_with_error_metadata(self):
        """Empty assistant turn carrying error metadata is preserved (I3)."""
        msgs = [
            _make_msg("user", "hi", minutes_ago=2),
            _make_msg(
                "assistant",
                "",
                minutes_ago=1,
                token_usage={"input": 0, "output": 0, "error": "boom"},
            ),
        ]
        with _patch_db(_make_session_row(), list(reversed(msgs))):
            result = _load_history_messages("test-session", 10)
        # The failed turn must NOT be dropped — an assistant message survives.
        assert any(m["role"] == "assistant" for m in result)

    def test_truncates_long_messages(self):
        """Messages exceeding _MAX_MSG_CHARS are truncated."""
        long_text = "x" * (_MAX_MSG_CHARS + 500)
        msgs = [
            _make_msg("user", long_text, minutes_ago=1),
        ]
        with _patch_db(_make_session_row(), list(reversed(msgs))):
            result = _load_history_messages("test-session", 20)
        assert len(result) == 1
        text = result[0]["content"][0]["text"]
        assert len(text) < len(long_text)
        assert text.endswith("... (truncated)")

    def test_tool_calls_faithful_reconstruction(self):
        """Assistant messages with valid tool_calls produce toolUse/toolResult pairs."""
        tool_calls = [{"name": "scan_resources", "input": {"region": "us-east-1"}}]
        msgs = [
            _make_msg("user", "scan my aws", minutes_ago=2),
            _make_msg("assistant", "Found 5 resources", tool_calls=tool_calls, minutes_ago=1),
        ]
        with _patch_db(_make_session_row(), list(reversed(msgs))):
            result = _load_history_messages("test-session", 20)

        # user + assistant(text) + assistant(toolUse) + user(toolResult)
        # After merging consecutive same-role, the structure may vary,
        # but we should find toolUse and toolResult content blocks
        all_content = []
        for m in result:
            for block in m["content"]:
                all_content.append(block)

        tool_uses = [b for b in all_content if "toolUse" in b]
        tool_results = [b for b in all_content if "toolResult" in b]
        assert len(tool_uses) == 1
        assert tool_uses[0]["toolUse"]["name"] == "scan_resources"
        assert len(tool_results) == 1
        assert tool_results[0]["toolResult"]["content"] == [{"text": "(result from previous session)"}]

    def test_tool_calls_fallback_to_prefix_on_invalid_data(self):
        """When tool_calls data is invalid, falls back to [Used tools: ...] prefix."""
        # tool_calls with entries missing 'name' — _rebuild_tool_messages returns []
        tool_calls = [{"input": {"x": 1}}]
        msgs = [
            _make_msg("user", "scan my aws", minutes_ago=2),
            _make_msg("assistant", "Found 5 resources", tool_calls=tool_calls, minutes_ago=1),
        ]
        with _patch_db(_make_session_row(), list(reversed(msgs))):
            result = _load_history_messages("test-session", 20)

        # Should fall back to text prefix with "unknown" since name is missing
        assistant_texts = [
            m["content"][0]["text"] for m in result if m["role"] == "assistant"
        ]
        # The fallback tries tc.get("name") or tc.get("tool_name", "unknown") → "unknown"
        assert any("[Used tools: unknown]" in t for t in assistant_texts)

    def test_tool_calls_fallback_on_non_list(self):
        """When tool_calls is truthy but not a list, falls back to text prefix."""
        # _rebuild_tool_messages returns [] for non-list input
        tool_calls = "not-a-list"
        msgs = [
            _make_msg("user", "hello", minutes_ago=2),
            _make_msg("assistant", "reply", tool_calls=tool_calls, minutes_ago=1),
        ]
        with _patch_db(_make_session_row(), list(reversed(msgs))):
            result = _load_history_messages("test-session", 20)

        # Should not crash; assistant message should be present
        assert any(m["role"] == "assistant" for m in result)

    def test_tool_calls_multiple_tools_reconstruction(self):
        """Multiple tool_calls produce multiple toolUse/toolResult pairs."""
        tool_calls = [
            {"name": "scan_resources", "input": {}},
            {"name": "check_health", "input": {"target": "web"}},
        ]
        msgs = [
            _make_msg("user", "scan my aws", minutes_ago=2),
            _make_msg("assistant", "Found resources", tool_calls=tool_calls, minutes_ago=1),
        ]
        with _patch_db(_make_session_row(), list(reversed(msgs))):
            result = _load_history_messages("test-session", 20)

        all_content = []
        for m in result:
            for block in m["content"]:
                all_content.append(block)

        tool_uses = [b for b in all_content if "toolUse" in b]
        tool_results = [b for b in all_content if "toolResult" in b]
        assert len(tool_uses) == 2
        assert len(tool_results) == 2
        assert tool_uses[0]["toolUse"]["name"] == "scan_resources"
        assert tool_uses[1]["toolUse"]["name"] == "check_health"

    def test_merges_consecutive_same_role(self):
        """Consecutive same-role messages are merged."""
        msgs = [
            _make_msg("user", "hello", minutes_ago=4),
            _make_msg("assistant", "part 1", minutes_ago=3),
            _make_msg("assistant", "part 2", minutes_ago=2),
            _make_msg("user", "thanks", minutes_ago=1),
        ]
        with _patch_db(_make_session_row(), list(reversed(msgs))):
            result = _load_history_messages("test-session", 20)
        assert len(result) == 3
        assert result[0]["role"] == "user"
        assert result[1]["role"] == "assistant"
        assert "part 1" in result[1]["content"][0]["text"]
        assert "part 2" in result[1]["content"][0]["text"]
        assert result[2]["role"] == "user"

    def test_first_assistant_gets_synthetic_user(self):
        """If first message is assistant, a synthetic user message is prepended."""
        msgs = [
            _make_msg("assistant", "Welcome!", minutes_ago=2),
            _make_msg("user", "hi", minutes_ago=1),
        ]
        with _patch_db(_make_session_row(), list(reversed(msgs))):
            result = _load_history_messages("test-session", 20)
        assert len(result) == 3
        assert result[0]["role"] == "user"
        assert "continuing previous conversation" in result[0]["content"][0]["text"]
        assert result[1]["role"] == "assistant"
        assert result[2]["role"] == "user"

    def test_respects_max_turns_limit(self):
        """Only loads max_turns * 2 messages from DB."""
        msgs = [_make_msg("user" if i % 2 == 0 else "assistant", f"msg {i}", minutes_ago=20 - i) for i in range(20)]
        with _patch_db(_make_session_row(), list(reversed(msgs))):
            result = _load_history_messages("test-session", max_turns=3)
        # max_turns=3 → limit(6), so at most 6 raw messages → 6 after merge
        assert len(result) <= 6

    def test_summaries_prepended_before_history(self):
        """Session summaries appear as context prefix before history messages."""
        summaries = [
            _make_summary("Summary of early discussion about AWS setup", minutes_ago=10),
            _make_summary("Summary of debugging session for Lambda errors", minutes_ago=5),
        ]
        msgs = [
            _make_msg("user", "hello", minutes_ago=2),
            _make_msg("assistant", "hi there", minutes_ago=1),
        ]
        with _patch_db(_make_session_row(), list(reversed(msgs)), summary_rows=summaries):
            result = _load_history_messages("test-session", 20)

        # Summary user message + summary assistant ack + user + assistant = 4
        assert len(result) == 4
        # First message should be the summary context prefix
        assert result[0]["role"] == "user"
        assert "[Previous conversation summary]" in result[0]["content"][0]["text"]
        assert "AWS setup" in result[0]["content"][0]["text"]
        assert "Lambda errors" in result[0]["content"][0]["text"]
        # Second message is the assistant acknowledgment
        assert result[1]["role"] == "assistant"
        assert "context" in result[1]["content"][0]["text"].lower()
        # History messages follow
        assert result[2]["role"] == "user"
        assert result[2]["content"][0]["text"] == "hello"
        assert result[3]["role"] == "assistant"
        assert result[3]["content"][0]["text"] == "hi there"

    def test_summaries_only_no_history(self):
        """When there are summaries but no history messages, only summaries are returned."""
        summaries = [
            _make_summary("Summary of previous conversation", minutes_ago=5),
        ]
        with _patch_db(_make_session_row(), [], summary_rows=summaries):
            result = _load_history_messages("test-session", 20)

        assert len(result) == 2
        assert result[0]["role"] == "user"
        assert "[Previous conversation summary]" in result[0]["content"][0]["text"]
        assert "Summary of previous conversation" in result[0]["content"][0]["text"]
        assert result[1]["role"] == "assistant"

    def test_no_summaries_no_change(self):
        """When there are no summaries, behavior is unchanged from before."""
        msgs = [
            _make_msg("user", "hello", minutes_ago=2),
            _make_msg("assistant", "hi", minutes_ago=1),
        ]
        with _patch_db(_make_session_row(), list(reversed(msgs)), summary_rows=[]):
            result = _load_history_messages("test-session", 20)

        assert len(result) == 2
        assert result[0]["role"] == "user"
        assert result[0]["content"][0]["text"] == "hello"

    def test_empty_summary_text_skipped(self):
        """Summaries with empty text are not included."""
        summaries = [
            _make_summary("", minutes_ago=10),
            _make_summary("Valid summary", minutes_ago=5),
        ]
        msgs = [
            _make_msg("user", "hello", minutes_ago=2),
            _make_msg("assistant", "hi", minutes_ago=1),
        ]
        with _patch_db(_make_session_row(), list(reversed(msgs)), summary_rows=summaries):
            result = _load_history_messages("test-session", 20)

        # Summary prefix should only contain the valid summary
        summary_text = result[0]["content"][0]["text"]
        assert "Valid summary" in summary_text

    def test_summaries_with_first_assistant_message(self):
        """Summaries prevent the synthetic user prefix when first history msg is assistant."""
        summaries = [
            _make_summary("Previous context summary", minutes_ago=10),
        ]
        msgs = [
            _make_msg("assistant", "Welcome!", minutes_ago=2),
            _make_msg("user", "hi", minutes_ago=1),
        ]
        with _patch_db(_make_session_row(), list(reversed(msgs)), summary_rows=summaries):
            result = _load_history_messages("test-session", 20)

        # Summary user msg starts the sequence, so no synthetic user needed
        assert result[0]["role"] == "user"
        assert "[Previous conversation summary]" in result[0]["content"][0]["text"]
        # No "(continuing previous conversation)" synthetic message needed
        assert not any(
            "continuing previous conversation" in m["content"][0].get("text", "")
            for m in result
        )


class TestGetOrCreateWithHistory:

    @patch("agenticops.web.session_manager._load_history_messages")
    @patch("agenticops.web.session_manager.create_main_agent")
    def test_injects_history_on_new_agent(self, mock_create, mock_load):
        """get_or_create injects history messages into a new agent."""
        from agenticops.web.session_manager import ChatSessionManager

        fake_agent = MagicMock()
        fake_agent.messages = []
        mock_create.return_value = fake_agent

        history = [
            {"role": "user", "content": [{"text": "hello"}]},
            {"role": "assistant", "content": [{"text": "hi"}]},
        ]
        mock_load.return_value = history

        mgr = ChatSessionManager()
        agent = mgr.get_or_create("sess-123")

        assert len(agent.messages) == 2
        assert agent.messages[0]["role"] == "user"
        mock_load.assert_called_once()

    @patch("agenticops.web.session_manager._load_history_messages")
    @patch("agenticops.web.session_manager.create_main_agent")
    def test_no_history_still_works(self, mock_create, mock_load):
        """get_or_create works fine when there's no history."""
        from agenticops.web.session_manager import ChatSessionManager

        fake_agent = MagicMock()
        fake_agent.messages = []
        mock_create.return_value = fake_agent
        mock_load.return_value = []

        mgr = ChatSessionManager()
        agent = mgr.get_or_create("sess-empty")

        assert len(agent.messages) == 0

    @patch("agenticops.web.session_manager._load_history_messages")
    @patch("agenticops.web.session_manager.create_main_agent")
    def test_existing_agent_not_reloaded(self, mock_create, mock_load):
        """Existing agent in cache is returned without reloading history."""
        from agenticops.web.session_manager import ChatSessionManager

        fake_agent = MagicMock()
        fake_agent.messages = [{"role": "user", "content": [{"text": "cached"}]}]
        mock_create.return_value = fake_agent
        mock_load.return_value = [{"role": "user", "content": [{"text": "hello"}]}]

        mgr = ChatSessionManager()
        mgr.get_or_create("sess-x")  # first call creates
        mock_create.reset_mock()
        mock_load.reset_mock()

        agent = mgr.get_or_create("sess-x")  # second call uses cache
        mock_create.assert_not_called()
        mock_load.assert_not_called()

    @patch("agenticops.web.session_manager._load_history_messages")
    @patch("agenticops.web.session_manager.create_main_agent")
    def test_concurrent_sessions_not_blocked(self, mock_create, mock_load):
        """Different sessions don't block each other during creation."""
        import threading
        from agenticops.web.session_manager import ChatSessionManager

        creation_order = []
        barrier = threading.Barrier(2, timeout=5)

        def slow_create(model_id_override="", effort_override=""):
            agent = MagicMock()
            agent.messages = []
            return agent

        def slow_load(sid, depth):
            creation_order.append(f"load-start-{sid}")
            barrier.wait()  # both threads must reach here
            creation_order.append(f"load-end-{sid}")
            return []

        mock_create.side_effect = slow_create
        mock_load.side_effect = slow_load

        mgr = ChatSessionManager()
        threads = []
        for sid in ("sess-A", "sess-B"):
            t = threading.Thread(target=mgr.get_or_create, args=(sid,))
            threads.append(t)

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        # Both loads started before either finished — proves no global blocking
        starts = [e for e in creation_order if e.startswith("load-start")]
        assert len(starts) == 2, f"Expected 2 load-starts, got: {creation_order}"

    @patch("agenticops.web.session_manager._load_history_messages")
    @patch("agenticops.web.session_manager.create_main_agent")
    def test_remove_cleans_session_lock(self, mock_create, mock_load):
        """remove() cleans up per-session lock."""
        from agenticops.web.session_manager import ChatSessionManager

        fake_agent = MagicMock()
        fake_agent.messages = []
        mock_create.return_value = fake_agent
        mock_load.return_value = []

        mgr = ChatSessionManager()
        mgr.get_or_create("sess-z")
        assert "sess-z" in mgr._session_locks

        mgr.remove("sess-z")
        assert "sess-z" not in mgr._agents
        assert "sess-z" not in mgr._session_locks
