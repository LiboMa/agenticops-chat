"""Tests for the protocol-agnostic ACP enhanced-backend core."""

import pytest


def test_config_fields_present():
    # Assert the fields exist with the right types — NOT specific values, which
    # are user-configurable at runtime (settings.yaml / env / Web Settings).
    from agenticops.config import settings
    assert isinstance(settings.acp_enhanced_enabled, bool)
    assert isinstance(settings.acp_enhanced_backend, str) and settings.acp_enhanced_backend
    assert isinstance(settings.acp_use_bedrock, bool)
    assert isinstance(settings.acp_timeout_seconds, int)


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


class TestRegistry:
    def setup_method(self):
        # Snapshot the real registry, then start clean. teardown restores it so
        # these tests don't wipe the import-time registrations other test files
        # (e.g. test_acp_providers) rely on. Import the package first so the
        # snapshot captures the real backends even if this runs before them.
        import agenticops.acp  # noqa: F401 — triggers register_backend at import
        from agenticops.acp import registry
        self._saved = dict(registry._BACKENDS)
        registry._BACKENDS.clear()

    def teardown_method(self):
        from agenticops.acp import registry
        registry._BACKENDS.clear()
        registry._BACKENDS.update(self._saved)

    def test_register_and_get(self):
        from agenticops.acp import registry
        from agenticops.acp.types import BackendCapabilities, EnhancedEvent

        class Dummy:
            name = "dummy"
            def capabilities(self): return BackendCapabilities(True, False, False, False)
            async def run(self, task, context):
                yield EnhancedEvent(kind="text", text="x")
            async def cancel(self): ...

        registry.register_backend("dummy", Dummy)
        assert "dummy" in registry.available_backends()
        be = registry.get_backend("dummy")
        assert be.name == "dummy"

    def test_get_unknown_raises(self):
        from agenticops.acp import registry
        with pytest.raises(KeyError):
            registry.get_backend("nope")
