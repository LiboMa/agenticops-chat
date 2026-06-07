"""Tests for the enhanced_task async-generator tool (streaming form)."""
import asyncio
import inspect

import pytest

from agenticops.acp.types import BackendCapabilities, EnhancedEvent


class _FakeBackend:
    """A fake EnhancedBackend that yields a fixed event sequence."""
    name = "fake"

    def __init__(self, events):
        self._events = events

    def capabilities(self):
        return BackendCapabilities(streaming=True, plan=False, permissions=False, tools=False)

    async def run(self, task, context):
        for ev in self._events:
            yield ev

    async def cancel(self):
        ...


def _register_fake(monkeypatch, events):
    from agenticops.acp import registry
    monkeypatch.setitem(registry._BACKENDS, "fake", lambda: _FakeBackend(events))


async def _drain(agen):
    """Collect all yielded items from an async generator."""
    out = []
    async for item in agen:
        out.append(item)
    return out


def test_enhanced_task_is_async_generator():
    from agenticops.agents.enhanced import enhanced_task
    # Strands routes async-generator tools through the streaming path; the
    # underlying function MUST be an async generator function.
    fn = getattr(enhanced_task, "_tool_func", None) or getattr(enhanced_task, "__wrapped__", None) or enhanced_task
    assert inspect.isasyncgenfunction(fn), "enhanced_task must be an async generator function"


def test_disabled_yields_single_message(monkeypatch):
    monkeypatch.setattr("agenticops.config.settings.acp_enhanced_enabled", False, raising=False)
    from agenticops.agents.enhanced import _enhanced_task_impl
    items = asyncio.run(_drain(_enhanced_task_impl("do something")))
    assert len(items) == 1
    assert "disabled" in items[0].lower()


def test_streams_text_then_final_result(monkeypatch):
    monkeypatch.setattr("agenticops.config.settings.acp_enhanced_enabled", True, raising=False)
    monkeypatch.setattr("agenticops.config.settings.acp_enhanced_backend", "fake", raising=False)
    _register_fake(monkeypatch, [
        EnhancedEvent(kind="tool_start", tool_name="Read"),
        EnhancedEvent(kind="text", text="Hello "),
        EnhancedEvent(kind="text", text="world"),
        EnhancedEvent(kind="tool_end", tool_name="Read"),
        EnhancedEvent(kind="done", tokens={"input": 5, "output": 2}),
    ])
    from agenticops.agents.enhanced import _enhanced_task_impl
    items = asyncio.run(_drain(_enhanced_task_impl("greet")))

    # Intermediate items are sub-event dicts; the LAST item is the result string
    # (Strands wraps the final yield as the tool result the agent receives).
    final = items[-1]
    assert isinstance(final, str)
    assert final == "Hello world"

    subs = items[:-1]
    # streaming sub-events carry the enhanced kinds for the SSE mapper
    kinds = [s.get("kind") for s in subs if isinstance(s, dict)]
    assert "tool_start" in kinds
    assert "text" in kinds
    assert "tool_end" in kinds


def test_backend_error_yields_error_text(monkeypatch):
    monkeypatch.setattr("agenticops.config.settings.acp_enhanced_enabled", True, raising=False)
    monkeypatch.setattr("agenticops.config.settings.acp_enhanced_backend", "fake", raising=False)
    _register_fake(monkeypatch, [EnhancedEvent(kind="error", error="boom")])
    from agenticops.agents.enhanced import _enhanced_task_impl
    items = asyncio.run(_drain(_enhanced_task_impl("x")))
    final = items[-1]
    assert isinstance(final, str)
    assert "boom" in final


def test_unknown_backend_yields_message(monkeypatch):
    monkeypatch.setattr("agenticops.config.settings.acp_enhanced_enabled", True, raising=False)
    monkeypatch.setattr("agenticops.config.settings.acp_enhanced_backend", "does-not-exist", raising=False)
    from agenticops.agents.enhanced import _enhanced_task_impl
    items = asyncio.run(_drain(_enhanced_task_impl("x")))
    assert isinstance(items[-1], str)
    assert "unavailable" in items[-1].lower()
