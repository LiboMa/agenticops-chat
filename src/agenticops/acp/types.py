"""Protocol-agnostic core types for the enhanced-backend abstraction.

NO JSON-RPC / ACP wire details here — those live in client.py/mapping.py.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncIterator, Literal, Optional, Protocol, runtime_checkable


EventKind = Literal["text", "tool_start", "tool_end", "plan", "done", "error"]


@dataclass(frozen=True)
class BackendCapabilities:
    streaming: bool
    plan: bool          # emits plan/step updates
    permissions: bool   # may request permission (HITL)
    tools: bool         # can be given client tools (MCP) — False this round


@dataclass(frozen=True)
class EnhancedEvent:
    """Backend-agnostic streaming event. `kind` values map 1:1 onto the
    frontend SSE cases (text/tool_start/tool_end/done/error)."""
    kind: EventKind
    text: Optional[str] = None          # kind="text"
    tool_name: Optional[str] = None     # kind="tool_start" | "tool_end"
    plan: Optional[list[dict]] = None   # kind="plan" (entries)
    tokens: Optional[dict] = None       # kind="done" ({"input":..,"output":..})
    error: Optional[str] = None         # kind="error"


@runtime_checkable
class EnhancedBackend(Protocol):
    """A pluggable enhancement backend. Protocol-agnostic: the wire protocol
    (ACP/JSON-RPC, or anything else) is the provider's implementation detail."""
    name: str
    def capabilities(self) -> BackendCapabilities: ...
    def run(self, task: str, context: str) -> AsyncIterator[EnhancedEvent]: ...
    async def cancel(self) -> None: ...
