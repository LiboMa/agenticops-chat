"""Pure translation: ACP session/update payload -> backend-agnostic EnhancedEvent.

This is the unit-testable seam between the ACP wire protocol and our core.
Input is the inner `update` object from a session/update notification's params
(the spike confirmed the shape is nested: params.update.sessionUpdate — the
AcpClient unwraps params["update"] before calling here). Returns None for
updates we don't surface (commands list, usage meter, thinking chunks, unknown).
"""
from __future__ import annotations

from typing import Any, Optional

from agenticops.acp.types import EnhancedEvent


def acp_update_to_event(update: dict[str, Any]) -> Optional[EnhancedEvent]:
    kind = update.get("sessionUpdate")

    if kind == "agent_message_chunk":
        text = (update.get("content") or {}).get("text", "")
        return EnhancedEvent(kind="text", text=text) if text else None

    if kind == "tool_call":
        # a new tool call begins
        return EnhancedEvent(kind="tool_start",
                             tool_name=update.get("title") or update.get("toolCallId") or "tool")

    if kind == "tool_call_update":
        # only surface terminal states as tool_end
        if update.get("status") in ("completed", "failed"):
            return EnhancedEvent(kind="tool_end",
                                 tool_name=update.get("title") or update.get("toolCallId") or "tool")
        return None

    if kind == "plan_update":
        entries = (update.get("plan") or {}).get("entries", [])
        return EnhancedEvent(kind="plan", plan=entries)

    # available_commands_update, usage_update, agent_thought_chunk,
    # user_message_chunk, unknown -> not surfaced
    return None


def tool_stream_to_sse(ev: dict) -> Optional[dict]:
    """Bridge a Strands ToolStreamEvent (emitted when the enhanced_task async-gen
    yields a sub-event) onto an existing chat SSE event.

    Input is the raw event dict seen in the web `stream_async` loop. Returns
    ``{"event": <name>, "data": <dict>}`` for enhanced sub-events we surface
    (text / tool_start / tool_end), or None for anything else (so the caller's
    other branches handle normal agent events untouched).
    """
    if ev.get("type") != "tool_stream":
        return None
    data = (ev.get("tool_stream_event") or {}).get("data")
    if not isinstance(data, dict):
        return None  # the final result string rides as the tool result, not here

    kind = data.get("kind")
    if kind == "text":
        text = data.get("text", "")
        return {"event": "text", "data": {"token": text}} if text else None
    if kind == "tool_start":
        return {"event": "tool_start", "data": {"name": data.get("tool_name") or "tool"}}
    if kind == "tool_end":
        return {"event": "tool_end", "data": {"name": data.get("tool_name") or "tool"}}
    return None
