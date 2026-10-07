"""RCA topology evidence injection (MVP-2.6.1 Plan C Task 4): the prompt section and the tool share one gate."""
import importlib
import re
from unittest.mock import MagicMock, patch

import pytest

from agenticops.config import settings

# The module, not the rca_agent tool that agenticops.agents re-exports under the same name.
ra = importlib.import_module("agenticops.agents.rca_agent")

_CJK_RE = re.compile(r"[\u3000-\u303f\u3400-\u4dbf\u4e00-\u9fff\uff00-\uffef]")


def _name(t):
    return getattr(t, "tool_name", None) or getattr(t, "__name__", str(t))


@pytest.fixture
def db(tmp_path, monkeypatch):
    import agenticops.models as models_mod
    monkeypatch.setattr(models_mod, "_engine", None)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/inject.db")
    models_mod.Base.metadata.create_all(models_mod.get_engine())
    yield
    models_mod._engine = None


def _build_rca(flag: bool):
    with patch.object(settings, "rca_topology_context_enabled", flag), \
         patch("agenticops.agents.rca_agent.Agent", side_effect=RuntimeError("stop")) as MockAgent, \
         patch("agenticops.agents.rca_agent.BedrockModel"), \
         patch("agenticops.agents.rca_agent.build_system_prompt", side_effect=lambda p, **kw: p), \
         patch("agenticops.config.get_bedrock_boto_session", return_value=MagicMock()):
        assert ra.rca_agent._tool_func(issue_id=1) == "RCA agent error: stop"
    kw = MockAgent.call_args.kwargs
    return kw["system_prompt"], {_name(t) for t in kw["tools"]}


def test_prompt_follows_flag():
    with patch.object(settings, "rca_topology_context_enabled", True):
        assert ra.topology_evidence_prompt() == ra.TOPOLOGY_EVIDENCE_PROMPT
    with patch.object(settings, "rca_topology_context_enabled", False):
        assert ra.topology_evidence_prompt() == ""


def test_tool_follows_flag():
    with patch.object(settings, "rca_topology_context_enabled", True):
        assert [_name(t) for t in ra.topology_evidence_tools()] == ["get_topology_evidence"]
    with patch.object(settings, "rca_topology_context_enabled", False):
        assert ra.topology_evidence_tools() == []


def test_rca_agent_composition_flag_on(db):
    prompt, names = _build_rca(True)
    assert prompt == ra.RCA_SYSTEM_PROMPT + ra.TOPOLOGY_EVIDENCE_PROMPT
    assert {"get_topology_evidence", "save_rca_result"} <= names


def test_rca_agent_composition_flag_off(db):
    prompt, names = _build_rca(False)
    assert prompt == ra.RCA_SYSTEM_PROMPT and "TOPOLOGY EVIDENCE" not in prompt
    assert "get_topology_evidence" not in names and "save_rca_result" in names


def test_base_prompt_asks_for_a_checked_location_either_way():
    # save_rca_result(location) is always a tool argument, so the base prompt describes it with the flag off too.
    assert "pass location:" in ra.RCA_SYSTEM_PROMPT and "never guess an id" in ra.RCA_SYSTEM_PROMPT
    assert "get_topology_evidence" not in ra.RCA_SYSTEM_PROMPT


def test_topology_prompt_is_english_and_cloud_neutral():
    assert _CJK_RE.search(ra.TOPOLOGY_EVIDENCE_PROMPT) is None
    for word in ("AWS", "EC2", "EKS", "VPC", "CloudWatch", "Bedrock"):
        assert word not in ra.TOPOLOGY_EVIDENCE_PROMPT, word
