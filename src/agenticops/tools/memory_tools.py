"""Strands Agent tools for per-agent memory.

These tools are added to each agent's tool list, allowing agents to
remember important learnings and recall past experiences.
"""

import asyncio
import logging

from strands import tool

logger = logging.getLogger(__name__)

# Agent name is resolved from context at call time
_current_agent_name: str = "default_agent"


def set_current_agent(name: str) -> None:
    """Set the current agent name for memory tools."""
    global _current_agent_name
    _current_agent_name = name


@tool
def remember_this(
    content: str,
    memory_type: str = "episodic",
    source: str = "",
) -> str:
    """Store a memory for future recall.

    Use this when you learn something important during an investigation:
    - A diagnosis pattern that worked
    - A fix that resolved an issue
    - A configuration detail worth remembering

    Args:
        content: What to remember (natural language)
        memory_type: episodic, procedural, or semantic
        source: What triggered this (e.g., "rca:issue-42")

    Returns:
        Confirmation message
    """
    from agenticops.memory import get_agent_memory
    from agenticops.memory.types import MemoryType

    try:
        mtype = MemoryType(memory_type)
    except ValueError:
        mtype = MemoryType.EPISODIC

    memory = get_agent_memory(_current_agent_name)

    # Run async in sync context (Strands tools are sync)
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                entry = pool.submit(
                    asyncio.run, memory.remember(content, mtype, source=source)
                ).result(timeout=10)
        else:
            entry = loop.run_until_complete(
                memory.remember(content, mtype, source=source)
            )
    except RuntimeError:
        entry = asyncio.run(memory.remember(content, mtype, source=source))

    return f"Remembered ({mtype.value}): {content[:100]}... [id={entry.id}]"


@tool
def recall_memories(
    query: str,
    top_k: int = 5,
) -> str:
    """Search your memories for relevant past experiences.

    Use BEFORE starting any investigation to check if you've seen similar issues.

    Args:
        query: What to search for (e.g., "EKS pod OOM crash")
        top_k: Max results to return

    Returns:
        Formatted list of relevant memories
    """
    from agenticops.memory import get_agent_memory

    memory = get_agent_memory(_current_agent_name)

    # Run async in sync context
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                results = pool.submit(
                    asyncio.run, memory.recall(query, top_k=top_k)
                ).result(timeout=10)
        else:
            results = loop.run_until_complete(memory.recall(query, top_k=top_k))
    except RuntimeError:
        results = asyncio.run(memory.recall(query, top_k=top_k))

    if not results:
        return "No relevant memories found."

    lines = [f"Found {len(results)} relevant memories:\n"]
    for i, entry in enumerate(results, 1):
        lines.append(
            f"{i}. [{entry.memory_type.value}] {entry.content[:200]}"
            f" (confidence: {entry.confidence:.2f}, recalls: {entry.recall_count})"
        )
        if entry.source:
            lines.append(f"   Source: {entry.source}")

    return "\n".join(lines)
