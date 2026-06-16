"""Optional enhancement tool: delegate a complex task to an external coding
agent (Claude Code) via the ACP enhanced backend. Registered into main/sre only
when settings.acp_enhanced_enabled is true.

Implemented as an async generator so Strands streams the backend's progress in
real time: intermediate `yield`s are small sub-event dicts (surfaced to the web
SSE via ToolStreamEvent), and the FINAL `yield` is the accumulated result string
(which Strands wraps as the tool result the calling agent receives).
"""
from __future__ import annotations

from typing import AsyncIterator

from strands import tool

from agenticops.config import settings


async def _enhanced_task_impl(task: str, context: str = "", backend: str = "") -> AsyncIterator:
    """Async-generator core. Yields sub-event dicts for streaming, then a final
    result string. See module docstring for the streaming contract."""
    if not settings.acp_enhanced_enabled:
        yield "Enhanced backend is disabled (acp_enhanced_enabled=false)."
        return

    from agenticops.acp.registry import get_backend

    try:
        be = get_backend(backend or settings.acp_enhanced_backend)
    except KeyError as e:
        yield f"Enhanced backend unavailable: {e}"
        return

    chunks: list[str] = []
    err: str | None = None
    try:
        async for ev in be.run(task, context):
            if ev.kind == "text" and ev.text:
                chunks.append(ev.text)
                # stream the chunk out for live display
                yield {"kind": "text", "text": ev.text}
            elif ev.kind == "tool_start":
                yield {"kind": "tool_start", "tool_name": ev.tool_name or "tool"}
            elif ev.kind == "tool_end":
                yield {"kind": "tool_end", "tool_name": ev.tool_name or "tool"}
            elif ev.kind == "error":
                err = ev.error
            # plan/done are not surfaced as sub-events this round
    except Exception as e:  # never crash the calling agent's turn
        yield f"Enhanced backend failed: {e}"
        return

    # Final yield = the tool result the agent receives.
    if err and not chunks:
        yield f"Enhanced backend error: {err}"
    else:
        yield "".join(chunks) or "(enhanced backend returned no text)"


@tool
async def enhanced_task(task: str, context: str = "", backend: str = ""):
    """Delegate a complex task to an enhanced external coding agent (e.g. Claude Code)
    for a higher-quality result. Use for create-skill, deep research, brainstorming,
    or complex multi-step operations that the standard tools cannot fully solve.

    Streams the backend's progress live; returns the accumulated text result (or a
    clear error message — in which case continue with normal handling).

    Args:
        task: The task/instruction to delegate.
        context: Optional supporting context.
        backend: Optional backend name override (default from settings).
    """
    async for item in _enhanced_task_impl(task, context, backend):
        yield item
