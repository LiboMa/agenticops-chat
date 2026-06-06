"""Optional enhancement tool: delegate a complex task to an external coding
agent (Claude Code) via the ACP enhanced backend. Registered into main/sre only
when settings.acp_enhanced_enabled is true."""
from __future__ import annotations

import asyncio

from strands import tool

from agenticops.config import settings


@tool
def enhanced_task(task: str, context: str = "", backend: str = "") -> str:
    """Delegate a complex task to an enhanced external coding agent (e.g. Claude Code)
    for a higher-quality result. Use for create-skill, deep research, brainstorming,
    or complex multi-step operations that the standard tools cannot fully solve.

    Args:
        task: The task/instruction to delegate.
        context: Optional supporting context.
        backend: Optional backend name override (default from settings).
    Returns:
        The accumulated text result from the enhanced backend, or an error message
        (in which case continue with normal handling).
    """
    if not settings.acp_enhanced_enabled:
        return "Enhanced backend is disabled (acp_enhanced_enabled=false)."

    from agenticops.acp.registry import get_backend

    try:
        be = get_backend(backend or settings.acp_enhanced_backend)
    except KeyError as e:
        return f"Enhanced backend unavailable: {e}"

    async def _drive() -> tuple[list[str], str | None]:
        chunks: list[str] = []
        err: str | None = None
        async for ev in be.run(task, context):
            if ev.kind == "text" and ev.text:
                chunks.append(ev.text)
            elif ev.kind == "error":
                err = ev.error
        return chunks, err

    try:
        chunks, err = asyncio.run(_drive())
    except Exception as e:  # never crash the calling agent's turn
        return f"Enhanced backend failed: {e}"
    if err and not chunks:
        return f"Enhanced backend error: {err}"
    return "".join(chunks) or "(enhanced backend returned no text)"
