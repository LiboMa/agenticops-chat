"""Tests for the tool_stream -> SSE bridge (pure function, no server)."""
from agenticops.acp.mapping import tool_stream_to_sse


def _evt(data):
    """Shape Strands ToolStreamEvent produces in the stream_async loop."""
    return {"type": "tool_stream", "tool_stream_event": {"tool_use": {"toolUseId": "t1"}, "data": data}}


def test_text_subevent_maps_to_text_sse():
    out = tool_stream_to_sse(_evt({"kind": "text", "text": "hello"}))
    assert out == {"event": "text", "data": {"token": "hello"}}


def test_tool_start_subevent_maps_to_tool_start_sse():
    out = tool_stream_to_sse(_evt({"kind": "tool_start", "tool_name": "Read"}))
    assert out == {"event": "tool_start", "data": {"name": "Read"}}


def test_tool_end_subevent_maps_to_tool_end_sse():
    out = tool_stream_to_sse(_evt({"kind": "tool_end", "tool_name": "Read"}))
    assert out == {"event": "tool_end", "data": {"name": "Read"}}


def test_non_tool_stream_event_is_none():
    # a normal text-token event from the main agent — not ours
    assert tool_stream_to_sse({"data": "regular token"}) is None
    assert tool_stream_to_sse({"current_tool_use": {"name": "scan_agent"}}) is None
    assert tool_stream_to_sse({}) is None


def test_tool_stream_with_string_data_is_none():
    # the FINAL yield (result string) rides as the tool result, not a sub-event;
    # if it ever appears as tool_stream data, it's not a dict we surface
    assert tool_stream_to_sse(_evt("the final result string")) is None


def test_tool_stream_unknown_kind_is_none():
    assert tool_stream_to_sse(_evt({"kind": "plan", "plan": []})) is None
    assert tool_stream_to_sse(_evt({"kind": "done", "tokens": {}})) is None


def test_empty_text_is_none():
    assert tool_stream_to_sse(_evt({"kind": "text", "text": ""})) is None
