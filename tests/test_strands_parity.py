"""Strands context parity: every agent keeps ITS conversation manager and gets exactly the 1.45-era tool-result
offloader, on any SDK version.

From Strands 1.56 a `context_manager` argument makes the SDK discard a passed conversation manager (only a UserWarning
says so) — every per-agent sliding window would stop working silently. So no build passes one: the offloader is a
plugin (config.get_agent_context_plugins). These tests build REAL `strands.Agent`s the way the agent modules do.
"""
import inspect
import pathlib
import re
import warnings

import boto3
import pytest
from strands import Agent
from strands.models.bedrock import BedrockModel
from strands.vended_plugins.context_offloader import ContextOffloader

from agenticops.agents.preamble import bedrock_model_kwargs
from agenticops.config import (
    AGENT_NAMES, FULL_CONTEXT, get_agent_context_plugins, get_agent_conversation_manager, get_agent_model_config,
    get_agent_window_size, settings,
)

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "agenticops"


def _build(name: str) -> Agent:
    model_id, max_tokens = get_agent_model_config(name)
    session = boto3.Session(region_name="us-east-1", aws_access_key_id="x", aws_secret_access_key="y")  # no network
    model = BedrockModel(model_id=model_id, boto_session=session, max_tokens=max_tokens,
                         **bedrock_model_kwargs(model_id))
    return Agent(model=model, system_prompt="p", callback_handler=None,
                 conversation_manager=get_agent_conversation_manager(name), plugins=get_agent_context_plugins(name))


@pytest.mark.parametrize("offload", [True, False])
@pytest.mark.parametrize("name", AGENT_NAMES)
def test_every_agent_keeps_its_conversation_manager_and_builds_without_warnings(monkeypatch, name, offload):
    monkeypatch.setattr(settings, "strands_context_manager_auto", offload)
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # "ignoring co-provided conversation_manager", deprecations → failures
        agent = _build(name)
    cm, want = agent.conversation_manager, get_agent_window_size(name)
    if want == FULL_CONTEXT:
        assert type(cm).__name__ == "NullConversationManager"
    else:
        assert (type(cm).__name__, cm.window_size) == ("SlidingWindowConversationManager", want)
    assert ("retrieve_offloaded_content" in agent.tool_registry.registry) is offload


def test_the_offloader_has_the_configured_thresholds(monkeypatch):
    monkeypatch.setattr(settings, "strands_context_manager_auto", True)
    (plugin,) = get_agent_context_plugins("rca")
    assert isinstance(plugin, ContextOffloader)
    assert (plugin._max_result_tokens, plugin._preview_tokens) == (settings.context_offload_max_result_tokens,
                                                                  settings.context_offload_preview_tokens)
    assert (settings.context_offload_max_result_tokens, settings.context_offload_preview_tokens) == (1500, 750)
    monkeypatch.setattr(settings, "strands_context_manager_auto", False)
    assert get_agent_context_plugins("rca") == []


def test_the_preview_is_the_head_of_the_result_as_in_1_45(monkeypatch):
    """1.64's own preview is 60 % head + 40 % tail; ours stays the first preview_tokens × 4 characters, so the RCA
    topology evidence keeps showing its candidates and first edges (config._head_preview_offloader_class)."""
    monkeypatch.setattr(settings, "strands_context_manager_auto", True)
    (plugin,) = get_agent_context_plugins("rca")
    budget = settings.context_offload_preview_tokens * 4
    text = "".join(f"{i:07d}\n" for i in range(2 * budget))  # far over the budget, every slice is distinct
    assert plugin._slice_preview(text) == text[:budget]
    assert plugin._slice_preview("short") == "short"


def test_the_sdk_still_builds_its_preview_through_slice_preview():
    """The override is private SDK API: if a Strands release stops calling it, this fails instead of the preview
    silently changing again."""
    assert "self._slice_preview(" in inspect.getsource(ContextOffloader._handle_tool_result)


def test_no_build_passes_a_context_manager():
    """A `context_manager=` argument anywhere would bring the conversation-manager discard back."""
    offenders = [f"{p.relative_to(SRC)}:{i}" for p in SRC.rglob("*.py")
                 for i, line in enumerate(p.read_text().splitlines(), 1)
                 if re.search(r"(?<!`)\bcontext_manager\s*=", line)]
    assert offenders == []
