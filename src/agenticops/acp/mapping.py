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
