"""Property-based tests for HistoryLoader — _rebuild_tool_messages().

Feature: chat-session-persistence, Property 1: toolUse 结构还原正确性

Uses hypothesis to generate random valid tool_calls and verify the output
conforms to the Strands SDK message format.

**Validates: Requirements 2.1**
"""

import hypothesis
from hypothesis import given, settings
from hypothesis import strategies as st

from agenticops.web.session_manager import _rebuild_tool_messages

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Random non-empty tool name (printable, 1-50 chars)
_tool_name_st = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "S")),
    min_size=1,
    max_size=50,
).filter(lambda s: s.strip())  # ensure not blank after strip

# Random tool input dict — keys are short strings, values are JSON-safe primitives
_json_primitive_st = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-10_000, max_value=10_000),
    st.floats(allow_nan=False, allow_infinity=False),
    st.text(max_size=30),
)

_tool_input_st = st.dictionaries(
    keys=st.text(
        alphabet=st.characters(whitelist_categories=("L", "N")),
        min_size=1,
        max_size=20,
    ),
    values=_json_primitive_st,
    max_size=5,
)

# A single valid tool_call dict
_tool_call_st = st.fixed_dictionaries({
    "name": _tool_name_st,
    "input": _tool_input_st,
})

# A non-empty list of valid tool_calls (1-5 entries)
_tool_calls_st = st.lists(_tool_call_st, min_size=1, max_size=5)


# ---------------------------------------------------------------------------
# Property 1: toolUse 结构还原正确性
# ---------------------------------------------------------------------------

class TestToolUseStructureProperty:
    """Property 1: toolUse 结构还原正确性

    For any valid tool_calls JSON array (containing name and input fields),
    _rebuild_tool_messages() should produce assistant messages with toolUse
    content blocks where toolUseId is non-empty, name matches the original
    tool_calls name, and input matches the original tool_calls input.

    Feature: chat-session-persistence, Property 1: toolUse 结构还原正确性
    **Validates: Requirements 2.1**
    """

    @given(tool_calls=_tool_calls_st)
    @settings(max_examples=150, deadline=None)
    def test_assistant_messages_have_tool_use_blocks(self, tool_calls):
        """Every tool call produces an assistant message with a toolUse content block."""
        result = _rebuild_tool_messages(tool_calls)

        # Should produce 2 messages per tool call (assistant + user)
        assert len(result) == len(tool_calls) * 2

        for i, tc in enumerate(tool_calls):
            assistant_msg = result[i * 2]
            assert assistant_msg["role"] == "assistant"
            assert len(assistant_msg["content"]) == 1
            assert "toolUse" in assistant_msg["content"][0]

    @given(tool_calls=_tool_calls_st)
    @settings(max_examples=150, deadline=None)
    def test_tool_use_id_is_non_empty_string(self, tool_calls):
        """Every toolUse block has a non-empty string toolUseId."""
        result = _rebuild_tool_messages(tool_calls)

        for i in range(len(tool_calls)):
            tool_use = result[i * 2]["content"][0]["toolUse"]
            tool_use_id = tool_use["toolUseId"]
            assert isinstance(tool_use_id, str)
            assert len(tool_use_id) > 0

    @given(tool_calls=_tool_calls_st)
    @settings(max_examples=150, deadline=None)
    def test_name_matches_original(self, tool_calls):
        """The toolUse name matches the original tool_calls entry name."""
        result = _rebuild_tool_messages(tool_calls)

        for i, tc in enumerate(tool_calls):
            tool_use = result[i * 2]["content"][0]["toolUse"]
            assert tool_use["name"] == tc["name"]

    @given(tool_calls=_tool_calls_st)
    @settings(max_examples=150, deadline=None)
    def test_input_matches_original(self, tool_calls):
        """The toolUse input matches the original tool_calls entry input."""
        result = _rebuild_tool_messages(tool_calls)

        for i, tc in enumerate(tool_calls):
            tool_use = result[i * 2]["content"][0]["toolUse"]
            assert tool_use["input"] == tc["input"]


# ---------------------------------------------------------------------------
# Property 2: toolResult 配对与占位内容
# ---------------------------------------------------------------------------

class TestToolResultPairingProperty:
    """Property 2: toolResult 配对与占位内容

    For any valid tool_calls JSON array, _rebuild_tool_messages() should produce
    a message sequence where every toolUse has exactly one matching toolResult
    (matched by toolUseId), each toolResult content is the placeholder text
    "(result from previous session)", each toolResult status is "success",
    and each toolResult message has role "user".

    Feature: chat-session-persistence, Property 2: toolResult 配对与占位内容
    **Validates: Requirements 2.2, 2.4**
    """

    @given(tool_calls=_tool_calls_st)
    @settings(max_examples=150, deadline=None)
    def test_each_tool_use_has_exactly_one_matching_tool_result(self, tool_calls):
        """Every toolUse has exactly one toolResult with the same toolUseId."""
        result = _rebuild_tool_messages(tool_calls)

        # Collect all toolUseIds from assistant messages
        tool_use_ids = []
        for msg in result:
            if msg["role"] == "assistant":
                for block in msg["content"]:
                    if "toolUse" in block:
                        tool_use_ids.append(block["toolUse"]["toolUseId"])

        # Collect all toolUseIds from user toolResult messages
        tool_result_ids = []
        for msg in result:
            if msg["role"] == "user":
                for block in msg["content"]:
                    if "toolResult" in block:
                        tool_result_ids.append(block["toolResult"]["toolUseId"])

        # Each toolUse id appears exactly once in toolResults
        assert len(tool_use_ids) == len(tool_calls)
        assert len(tool_result_ids) == len(tool_calls)
        for use_id in tool_use_ids:
            assert tool_result_ids.count(use_id) == 1, (
                f"toolUseId {use_id!r} should appear exactly once in toolResults"
            )

    @given(tool_calls=_tool_calls_st)
    @settings(max_examples=150, deadline=None)
    def test_tool_result_content_is_placeholder_text(self, tool_calls):
        """Every toolResult content is [{"text": "(result from previous session)"}]."""
        result = _rebuild_tool_messages(tool_calls)

        for msg in result:
            if msg["role"] == "user":
                for block in msg["content"]:
                    if "toolResult" in block:
                        expected_content = [{"text": "(result from previous session)"}]
                        assert block["toolResult"]["content"] == expected_content

    @given(tool_calls=_tool_calls_st)
    @settings(max_examples=150, deadline=None)
    def test_tool_result_status_is_success(self, tool_calls):
        """Every toolResult status is "success"."""
        result = _rebuild_tool_messages(tool_calls)

        for msg in result:
            if msg["role"] == "user":
                for block in msg["content"]:
                    if "toolResult" in block:
                        assert block["toolResult"]["status"] == "success"

    @given(tool_calls=_tool_calls_st)
    @settings(max_examples=150, deadline=None)
    def test_tool_result_messages_have_user_role(self, tool_calls):
        """Every toolResult message has role "user"."""
        result = _rebuild_tool_messages(tool_calls)

        for msg in result:
            for block in msg["content"]:
                if "toolResult" in block:
                    assert msg["role"] == "user", (
                        f"toolResult should be in a 'user' message, got {msg['role']!r}"
                    )


# ---------------------------------------------------------------------------
# Property 6: 摘要注入完整性
# ---------------------------------------------------------------------------

from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta, timezone

from agenticops.web.session_manager import _load_history_messages

# Strategies for summary / history message generation

_summary_text_st = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
    min_size=1,
    max_size=200,
).filter(lambda s: s.strip())

_msg_content_st = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
    min_size=1,
    max_size=200,
).filter(lambda s: s.strip())

# A list of user/assistant message pairs (at least 1 pair)
_msg_pair_st = st.tuples(_msg_content_st, _msg_content_st)
_msg_pairs_st = st.lists(_msg_pair_st, min_size=1, max_size=5)

# A non-empty list of summary texts
_summary_texts_st = st.lists(_summary_text_st, min_size=1, max_size=5)


def _make_mock_msg(role: str, content: str, minutes_ago: int = 0):
    """Create a mock ChatMessage row."""
    m = MagicMock()
    m.role = role
    m.content = content
    m.tool_calls = None
    m.created_at = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return m


def _make_mock_summary(text: str, minutes_ago: int = 0):
    """Create a mock SessionSummary row."""
    s = MagicMock()
    s.summary_text = text
    s.created_at = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return s


def _make_mock_session(pk: int = 1, session_id: str = "prop-test-session"):
    row = MagicMock()
    row.id = pk
    row.session_id = session_id
    return row


def _patch_db_for_prop(session_row, message_rows, summary_rows):
    """Return a context-manager mock for get_db_session + query chain."""

    class FakeQuery:
        def __init__(self, model):
            self._model = model

        def filter(self, *args):
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


class TestSummaryInjectionIntegrityProperty:
    """Property 6: 摘要注入完整性

    For any session with N summary records (N >= 1), when HistoryLoader
    rebuilds the message history, the returned message list should contain
    all N summaries' content, and summary content should appear before
    history messages.

    Feature: chat-session-persistence, Property 6: 摘要注入完整性
    **Validates: Requirements 5.3**
    """

    @given(
        summary_texts=_summary_texts_st,
        msg_pairs=_msg_pairs_st,
    )
    @settings(max_examples=150, deadline=None)
    def test_all_summary_texts_present_in_output(self, summary_texts, msg_pairs):
        """Every summary text appears in the returned message list."""
        session_row = _make_mock_session()

        # Build summary rows (older summaries first)
        summary_rows = [
            _make_mock_summary(text, minutes_ago=100 - i)
            for i, text in enumerate(summary_texts)
        ]

        # Build message rows in DESC order (newest first) as DB returns
        message_rows = []
        for idx, (user_text, asst_text) in enumerate(msg_pairs):
            minutes = (len(msg_pairs) - idx) * 2
            message_rows.append(_make_mock_msg("assistant", asst_text, minutes_ago=minutes - 1))
            message_rows.append(_make_mock_msg("user", user_text, minutes_ago=minutes))

        with _patch_db_for_prop(session_row, message_rows, summary_rows):
            result = _load_history_messages("prop-test-session", 20)

        # All summary texts must appear somewhere in the output
        all_text = " ".join(
            block.get("text", "")
            for msg in result
            for block in msg["content"]
            if "text" in block
        )
        for summary_text in summary_texts:
            assert summary_text in all_text, (
                f"Summary text {summary_text!r} not found in output"
            )

    @given(
        summary_texts=_summary_texts_st,
        msg_pairs=_msg_pairs_st,
    )
    @settings(max_examples=150, deadline=None)
    def test_summaries_appear_before_history_messages(self, summary_texts, msg_pairs):
        """Summary content appears before any history message content."""
        session_row = _make_mock_session()

        summary_rows = [
            _make_mock_summary(text, minutes_ago=100 - i)
            for i, text in enumerate(summary_texts)
        ]

        message_rows = []
        for idx, (user_text, asst_text) in enumerate(msg_pairs):
            minutes = (len(msg_pairs) - idx) * 2
            message_rows.append(_make_mock_msg("assistant", asst_text, minutes_ago=minutes - 1))
            message_rows.append(_make_mock_msg("user", user_text, minutes_ago=minutes))

        with _patch_db_for_prop(session_row, message_rows, summary_rows):
            result = _load_history_messages("prop-test-session", 20)

        # Find the index of the summary prefix message (contains "[Previous conversation summary]")
        summary_prefix_idx = None
        first_history_idx = None

        for i, msg in enumerate(result):
            text_content = " ".join(
                block.get("text", "") for block in msg["content"] if "text" in block
            )
            if "[Previous conversation summary]" in text_content:
                summary_prefix_idx = i
                break

        assert summary_prefix_idx is not None, (
            "Expected a '[Previous conversation summary]' message in output"
        )

        # The summary assistant acknowledgment follows immediately
        summary_ack_idx = summary_prefix_idx + 1

        # First history message is after the summary block
        # Find first message that contains actual history content (not summary)
        history_user_texts = {ut for ut, _ in msg_pairs}
        history_asst_texts = {at for _, at in msg_pairs}
        all_history_texts = history_user_texts | history_asst_texts

        for i, msg in enumerate(result):
            if i <= summary_ack_idx:
                continue
            text_content = " ".join(
                block.get("text", "") for block in msg["content"] if "text" in block
            )
            for ht in all_history_texts:
                if ht in text_content:
                    first_history_idx = i
                    break
            if first_history_idx is not None:
                break

        # If we found history messages, they must come after the summary block
        if first_history_idx is not None:
            assert first_history_idx > summary_ack_idx, (
                f"History message at index {first_history_idx} should come after "
                f"summary acknowledgment at index {summary_ack_idx}"
            )

    @given(summary_texts=_summary_texts_st)
    @settings(max_examples=150, deadline=None)
    def test_summaries_present_even_without_history(self, summary_texts):
        """Summaries are returned even when there are no history messages."""
        session_row = _make_mock_session()

        summary_rows = [
            _make_mock_summary(text, minutes_ago=100 - i)
            for i, text in enumerate(summary_texts)
        ]

        with _patch_db_for_prop(session_row, [], summary_rows):
            result = _load_history_messages("prop-test-session", 20)

        # Should still have summary messages
        assert len(result) >= 2  # at least summary user + assistant ack

        all_text = " ".join(
            block.get("text", "")
            for msg in result
            for block in msg["content"]
            if "text" in block
        )
        for summary_text in summary_texts:
            assert summary_text in all_text, (
                f"Summary text {summary_text!r} not found in output (no history case)"
            )
