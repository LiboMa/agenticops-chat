"""Unit tests for _rebuild_tool_messages().

Validates: Requirements 2.1, 2.2, 2.4
"""

import pytest

from agenticops.web.session_manager import _rebuild_tool_messages


class TestRebuildToolMessagesBasic:
    """Core happy-path behaviour."""

    def test_single_tool_call(self):
        tool_calls = [{"name": "get_ec2_status", "input": {"instance_id": "i-123"}}]
        result = _rebuild_tool_messages(tool_calls)

        assert len(result) == 2

        # First message: assistant with toolUse
        assistant_msg = result[0]
        assert assistant_msg["role"] == "assistant"
        assert len(assistant_msg["content"]) == 1
        tool_use = assistant_msg["content"][0]["toolUse"]
        assert tool_use["name"] == "get_ec2_status"
        assert tool_use["input"] == {"instance_id": "i-123"}
        assert tool_use["toolUseId"]  # non-empty

        # Second message: user with toolResult
        user_msg = result[1]
        assert user_msg["role"] == "user"
        assert len(user_msg["content"]) == 1
        tool_result = user_msg["content"][0]["toolResult"]
        assert tool_result["toolUseId"] == tool_use["toolUseId"]
        assert tool_result["content"] == [{"text": "(result from previous session)"}]
        assert tool_result["status"] == "success"

    def test_multiple_tool_calls(self):
        tool_calls = [
            {"name": "list_instances", "input": {}},
            {"name": "describe_alarm", "input": {"alarm_name": "cpu-high"}},
        ]
        result = _rebuild_tool_messages(tool_calls)

        assert len(result) == 4
        # Alternating assistant/user pairs
        assert result[0]["role"] == "assistant"
        assert result[1]["role"] == "user"
        assert result[2]["role"] == "assistant"
        assert result[3]["role"] == "user"

        # Each pair has matching toolUseId
        id1 = result[0]["content"][0]["toolUse"]["toolUseId"]
        assert result[1]["content"][0]["toolResult"]["toolUseId"] == id1

        id2 = result[2]["content"][0]["toolUse"]["toolUseId"]
        assert result[3]["content"][0]["toolResult"]["toolUseId"] == id2

        assert id1 != id2

    def test_tool_name_fallback_to_tool_name_key(self):
        """DB records may use 'tool_name' instead of 'name'."""
        tool_calls = [{"tool_name": "check_health", "input": {"target": "web"}}]
        result = _rebuild_tool_messages(tool_calls)

        assert len(result) == 2
        assert result[0]["content"][0]["toolUse"]["name"] == "check_health"

    def test_preserves_existing_tool_use_id(self):
        """If the DB record already has a toolUseId, reuse it."""
        tool_calls = [{"name": "foo", "input": {}, "toolUseId": "existing-id-42"}]
        result = _rebuild_tool_messages(tool_calls)

        assert result[0]["content"][0]["toolUse"]["toolUseId"] == "existing-id-42"
        assert result[1]["content"][0]["toolResult"]["toolUseId"] == "existing-id-42"

    def test_preserves_tool_use_id_underscore_variant(self):
        tool_calls = [{"name": "bar", "input": {}, "tool_use_id": "underscore-id"}]
        result = _rebuild_tool_messages(tool_calls)

        assert result[0]["content"][0]["toolUse"]["toolUseId"] == "underscore-id"

    def test_missing_input_defaults_to_empty_dict(self):
        tool_calls = [{"name": "simple_tool"}]
        result = _rebuild_tool_messages(tool_calls)

        assert len(result) == 2
        assert result[0]["content"][0]["toolUse"]["input"] == {}

    def test_non_dict_input_defaults_to_empty_dict(self):
        tool_calls = [{"name": "tool_x", "input": "not-a-dict"}]
        result = _rebuild_tool_messages(tool_calls)

        assert len(result) == 2
        assert result[0]["content"][0]["toolUse"]["input"] == {}


class TestRebuildToolMessagesFallback:
    """Error / edge-case paths that should return []."""

    def test_empty_list(self):
        assert _rebuild_tool_messages([]) == []

    def test_none_input(self):
        assert _rebuild_tool_messages(None) == []

    def test_not_a_list(self):
        assert _rebuild_tool_messages("oops") == []

    def test_non_dict_entry(self):
        assert _rebuild_tool_messages(["not-a-dict"]) == []

    def test_missing_name(self):
        assert _rebuild_tool_messages([{"input": {"x": 1}}]) == []

    def test_empty_name(self):
        assert _rebuild_tool_messages([{"name": "", "input": {}}]) == []
