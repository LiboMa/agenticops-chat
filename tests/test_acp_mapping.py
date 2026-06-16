"""Tests for the pure ACP session/update -> EnhancedEvent mapping."""
from agenticops.acp.mapping import acp_update_to_event
from agenticops.acp.types import EnhancedEvent


def test_agent_message_chunk_to_text():
    ev = acp_update_to_event({"sessionUpdate": "agent_message_chunk",
                              "content": {"type": "text", "text": "hello"}})
    assert ev == EnhancedEvent(kind="text", text="hello")


def test_tool_call_to_tool_start():
    ev = acp_update_to_event({"sessionUpdate": "tool_call", "toolCallId": "t1",
                              "title": "Read file", "status": "pending"})
    assert ev.kind == "tool_start" and ev.tool_name == "Read file"


def test_tool_call_update_completed_to_tool_end():
    ev = acp_update_to_event({"sessionUpdate": "tool_call_update", "toolCallId": "t1",
                              "status": "completed"})
    assert ev.kind == "tool_end"


def test_tool_call_update_in_progress_is_ignored():
    ev = acp_update_to_event({"sessionUpdate": "tool_call_update", "toolCallId": "t1",
                              "status": "in_progress"})
    assert ev is None


def test_plan_update_to_plan():
    ev = acp_update_to_event({"sessionUpdate": "plan_update",
                              "plan": {"entries": [{"content": "step 1", "status": "pending"}]}})
    assert ev.kind == "plan" and ev.plan == [{"content": "step 1", "status": "pending"}]


def test_unknown_update_is_none():
    assert acp_update_to_event({"sessionUpdate": "available_commands_update"}) is None
    assert acp_update_to_event({}) is None


def test_empty_text_chunk_is_none():
    assert acp_update_to_event({"sessionUpdate": "agent_message_chunk",
                                "content": {"type": "text", "text": ""}}) is None


def test_agent_thought_chunk_is_none():
    # spike: 0.42.0 emits agent_thought_chunk (extended thinking) — not surfaced this round
    assert acp_update_to_event({"sessionUpdate": "agent_thought_chunk",
                                "content": {"type": "text", "text": "thinking..."}}) is None


def test_usage_update_is_none():
    # spike: running token meter — terminal result.usage is what we surface, not this
    assert acp_update_to_event({"sessionUpdate": "usage_update", "used": 33510, "size": 200000}) is None
