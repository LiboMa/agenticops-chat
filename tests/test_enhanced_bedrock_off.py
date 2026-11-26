"""Bedrock turned off means no Bedrock call — the enhanced backend included (MVP-2.9.0 review, Spec ①).

Claude Code with `acp_use_bedrock` runs on Bedrock with this host's AWS credentials. While Bedrock is off
(Settings → Model providers), `enhanced_task` is not offered to Main or the SRE agent, a call that names that backend
anyway is refused before anything starts, and Settings says why. Kiro / Codex, and Claude Code on its own login, are
unaffected."""
import asyncio
from unittest.mock import MagicMock, patch

import pytest

from agenticops.acp.types import BackendCapabilities, EnhancedEvent


class _Recorder:
    """A backend that records whether it was started."""
    started = 0

    def capabilities(self):
        return BackendCapabilities(streaming=True, plan=False, permissions=False, tools=False)

    async def run(self, task, context):
        type(self).started += 1
        yield EnhancedEvent(kind="text", text="ran")

    async def cancel(self):
        ...


@pytest.fixture
def acp(monkeypatch):
    from agenticops.acp import registry as acp_registry
    _Recorder.started = 0
    for name in ("claude-code", "kiro-cli"):
        monkeypatch.setitem(acp_registry._BACKENDS, name, _Recorder)
    monkeypatch.setattr("agenticops.config.settings.acp_enhanced_enabled", True, raising=False)
    monkeypatch.setattr("agenticops.config.settings.acp_enhanced_backend", "claude-code", raising=False)
    monkeypatch.setattr("agenticops.config.settings.acp_use_bedrock", True, raising=False)
    state = {"bedrock": False}
    monkeypatch.setattr("agenticops.llm.registry.bedrock_enabled", lambda: state["bedrock"])
    return state


def _drain(agen):
    async def go():
        return [item async for item in agen]
    return asyncio.run(go())


def test_claude_code_on_bedrock_is_refused_while_bedrock_is_off(acp):
    from agenticops.agents.enhanced import _enhanced_task_impl
    items = _drain(_enhanced_task_impl("research this"))
    assert len(items) == 1 and "Bedrock" in items[0] and "off" in items[0]
    assert _Recorder.started == 0


def test_a_backend_the_model_names_itself_is_checked_too(acp, monkeypatch):
    monkeypatch.setattr("agenticops.config.settings.acp_enhanced_backend", "kiro-cli", raising=False)
    from agenticops.agents.enhanced import _enhanced_task_impl
    items = _drain(_enhanced_task_impl("research this", backend="claude-code"))
    assert "Bedrock" in items[0] and _Recorder.started == 0


@pytest.mark.parametrize("backend, on_bedrock, bedrock_on", [
    ("kiro-cli", True, False),          # another backend: no Bedrock
    ("claude-code", False, False),      # Claude Code on its own login
    ("claude-code", True, True),        # Bedrock is on
])
def test_what_does_not_use_bedrock_still_runs(acp, monkeypatch, backend, on_bedrock, bedrock_on):
    monkeypatch.setattr("agenticops.config.settings.acp_enhanced_backend", backend, raising=False)
    monkeypatch.setattr("agenticops.config.settings.acp_use_bedrock", on_bedrock, raising=False)
    acp["bedrock"] = bedrock_on
    from agenticops.agents.enhanced import _enhanced_task_impl, enhanced_available
    assert enhanced_available() is True
    assert _drain(_enhanced_task_impl("research this"))[-1] == "ran" and _Recorder.started == 1


def test_enhanced_available_follows_the_switch(acp):
    from agenticops.agents.enhanced import bedrock_refusal, enhanced_available
    assert enhanced_available() is False and bedrock_refusal("claude-code")
    acp["bedrock"] = True
    assert enhanced_available() is True and bedrock_refusal("claude-code") is None


def _tool_names(tools) -> set:
    return {getattr(t, "tool_name", None) or getattr(t, "__name__", "") for t in tools}


def _main_tools() -> set:
    from agenticops.agents.main_agent import create_main_agent
    with patch("agenticops.agents.main_agent.Agent") as MockAgent, \
         patch("agenticops.llm.factory.build_model", return_value=MagicMock()), \
         patch("agenticops.agents.main_agent.build_system_prompt", side_effect=lambda p, **kw: p), \
         patch("agenticops.config.get_bedrock_boto_session", return_value=MagicMock()), \
         patch("agenticops.agents.main_agent._safe_mcp_clients", return_value=[]), \
         patch("agenticops.memory.curator.maybe_run_curator"), \
         patch("agenticops.skills.curator.maybe_run_skills_curator"):
        create_main_agent()
    return _tool_names(MockAgent.call_args.kwargs["tools"])


def _sre_tools() -> set:
    from agenticops.agents import sre_agent as mod
    with patch.object(mod, "Agent") as MockAgent, patch("agenticops.llm.factory.build_model", return_value=MagicMock()), \
         patch.object(mod, "build_system_prompt", return_value="p"), \
         patch("agenticops.config.get_agent_model_config", return_value=("scripted", 16384)), \
         patch("agenticops.config.get_bedrock_boto_session", return_value=MagicMock()):
        mod._create_sre_agent()
    return _tool_names(MockAgent.call_args.kwargs["tools"])


def test_neither_agent_is_offered_the_tool_while_bedrock_is_off(acp):
    assert "enhanced_task" not in _main_tools()
    assert "enhanced_task" not in _sre_tools()
    acp["bedrock"] = True
    assert "enhanced_task" in _main_tools()
    assert "enhanced_task" in _sre_tools()


def test_settings_say_why_the_backend_is_not_offered(acp):
    from agenticops.agents.enhanced import blocked_reason
    from agenticops.web.routers.settings import api_get_settings
    assert api_get_settings()["acp_enhanced_blocked"] == "bedrock_off"   # Bedrock off: nothing is listed from it
    acp["bedrock"] = True
    assert blocked_reason() is None
