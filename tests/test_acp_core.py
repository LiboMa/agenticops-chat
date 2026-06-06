"""Tests for the protocol-agnostic ACP enhanced-backend core."""

import pytest


def test_config_fields_present():
    from agenticops.config import settings
    assert settings.acp_enhanced_enabled is False          # default off
    assert settings.acp_enhanced_backend == "claude-code"
    assert settings.acp_use_bedrock is True
    assert settings.acp_timeout_seconds == 300


def test_enhanced_event_kinds():
    from agenticops.acp.types import EnhancedEvent
    e = EnhancedEvent(kind="text", text="hi")
    assert e.kind == "text" and e.text == "hi"
    d = EnhancedEvent(kind="done", tokens={"input": 10, "output": 5})
    assert d.tokens["input"] == 10
    err = EnhancedEvent(kind="error", error="boom")
    assert err.error == "boom"


def test_backend_capabilities():
    from agenticops.acp.types import BackendCapabilities
    c = BackendCapabilities(streaming=True, plan=True, permissions=True, tools=False)
    assert c.streaming and not c.tools


def test_enhanced_backend_is_protocol():
    # A minimal duck-typed backend satisfies the Protocol (structural typing).
    from agenticops.acp.types import EnhancedBackend, BackendCapabilities, EnhancedEvent

    class Dummy:
        name = "dummy"
        def capabilities(self): return BackendCapabilities(True, False, False, False)
        async def run(self, task, context):
            yield EnhancedEvent(kind="text", text=task)
        async def cancel(self): ...

    b: EnhancedBackend = Dummy()   # structural check
    assert b.name == "dummy"
