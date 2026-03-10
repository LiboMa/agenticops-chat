"""WAL-enforced tool decorator — auto-write memory after tool execution.

Implements the Write-Ahead Log principle: every significant tool execution
is automatically recorded in agent memory before the result is returned.

Usage:
    @tool
    @wal_enforced
    def run_rca(issue_id: str) -> dict:
        ...

Based on Researcher's recommendation (Strands meta-decorator pattern).
"""

import asyncio
import functools
import logging
from contextvars import ContextVar

from agenticops.memory import MemoryType, get_agent_memory

logger = logging.getLogger(__name__)

# Context variable for current agent name
_agent_ctx: ContextVar[str] = ContextVar("wal_agent", default="default_agent")


def set_wal_agent(name: str) -> None:
    """Set the current agent name for WAL enforcement."""
    _agent_ctx.set(name)


def wal_enforced(func=None, *, memory_type: MemoryType = MemoryType.EPISODIC):
    """Meta-decorator: auto-write WAL after tool execution.

    Can be used with or without arguments:
        @wal_enforced
        def my_tool(...): ...

        @wal_enforced(memory_type=MemoryType.PROCEDURAL)
        def my_tool(...): ...
    """
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            result = fn(*args, **kwargs)
            _record_wal(fn.__name__, args, kwargs, result, memory_type)
            return result

        @functools.wraps(fn)
        async def async_wrapper(*args, **kwargs):
            result = await fn(*args, **kwargs)
            await _async_record_wal(fn.__name__, args, kwargs, result, memory_type)
            return result

        if asyncio.iscoroutinefunction(fn):
            return async_wrapper
        return wrapper

    if func is not None:
        # Called without arguments: @wal_enforced
        return decorator(func)
    # Called with arguments: @wal_enforced(memory_type=...)
    return decorator


def _summarize(result, max_len: int = 150) -> str:
    """Create a concise summary of a tool result."""
    text = str(result)
    if len(text) > max_len:
        return text[:max_len] + "..."
    return text


def _record_wal(
    tool_name: str,
    args: tuple,
    kwargs: dict,
    result,
    memory_type: MemoryType,
) -> None:
    """Synchronous WAL recording."""
    try:
        agent_name = _agent_ctx.get()
        memory = get_agent_memory(agent_name)
        content = f"Executed {tool_name}: {_summarize(result)}"

        # Build context from args/kwargs
        context = {"tool": tool_name}
        if args:
            context["args"] = [str(a)[:100] for a in args[:3]]
        if kwargs:
            context["kwargs"] = {
                k: str(v)[:100] for k, v in list(kwargs.items())[:5]
            }

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    pool.submit(
                        asyncio.run,
                        memory.remember(
                            content=content,
                            memory_type=memory_type,
                            context=context,
                            source=f"wal:{tool_name}",
                        ),
                    ).result(timeout=5)
            else:
                loop.run_until_complete(
                    memory.remember(
                        content=content,
                        memory_type=memory_type,
                        context=context,
                        source=f"wal:{tool_name}",
                    )
                )
        except RuntimeError:
            asyncio.run(
                memory.remember(
                    content=content,
                    memory_type=memory_type,
                    context=context,
                    source=f"wal:{tool_name}",
                )
            )

    except Exception as e:
        # WAL failure must never block the tool
        logger.warning("WAL recording failed for %s: %s", tool_name, e)


async def _async_record_wal(
    tool_name: str,
    args: tuple,
    kwargs: dict,
    result,
    memory_type: MemoryType,
) -> None:
    """Async WAL recording."""
    try:
        agent_name = _agent_ctx.get()
        memory = get_agent_memory(agent_name)
        content = f"Executed {tool_name}: {_summarize(result)}"

        context = {"tool": tool_name}
        if args:
            context["args"] = [str(a)[:100] for a in args[:3]]
        if kwargs:
            context["kwargs"] = {
                k: str(v)[:100] for k, v in list(kwargs.items())[:5]
            }

        await memory.remember(
            content=content,
            memory_type=memory_type,
            context=context,
            source=f"wal:{tool_name}",
        )
    except Exception as e:
        logger.warning("WAL recording failed for %s: %s", tool_name, e)
