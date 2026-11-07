"""Web chat agents answer statistics with ```chart blocks and flows with ```mermaid blocks (2026-11-07). The rule is in
the prompt only for a Web chat build (full and read-only): CLI, IM bots and scheduled runs stay plain, since none of
them renders those blocks."""
import pathlib
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def build():
    def _build(read_only=False, rich_output=False):
        from agenticops.agents.main_agent import create_main_agent
        with patch("agenticops.agents.main_agent.Agent") as MockAgent, \
             patch("agenticops.agents.main_agent.BedrockModel"), \
             patch("agenticops.agents.main_agent.build_system_prompt", side_effect=lambda p, **kw: p), \
             patch("agenticops.config.get_bedrock_boto_session", return_value=MagicMock()), \
             patch("agenticops.agents.main_agent._safe_mcp_clients", return_value=[]), \
             patch("agenticops.memory.curator.maybe_run_curator"), \
             patch("agenticops.skills.curator.maybe_run_skills_curator"):
            create_main_agent(read_only=read_only, rich_output=rich_output)
        return MockAgent.call_args.kwargs["system_prompt"]
    return _build


def test_rule_is_only_in_rich_builds(build):
    rich = build(rich_output=True)
    assert "```chart" in rich and "```mermaid" in rich
    plain = build()
    assert "```chart" not in plain and "```mermaid" not in plain


def test_viewer_web_build_gets_the_rule(build):
    assert "```chart" in build(read_only=True, rich_output=True)
    assert "```chart" not in build(read_only=True)


def test_rule_is_english_and_bounded():
    from agenticops.agents.main_agent import RICH_OUTPUT_PROMPT
    assert not any("一" <= c <= "鿿" for c in RICH_OUTPUT_PROMPT) and len(RICH_OUTPUT_PROMPT) < 1500
    assert "ASCII" in RICH_OUTPUT_PROMPT


def test_web_session_manager_builds_rich(tmp_path, monkeypatch):
    import agenticops.models as models_mod
    from agenticops.config import settings
    from agenticops.web import session_manager as sm
    monkeypatch.setattr(models_mod, "_engine", None)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/rich.db")
    models_mod.Base.metadata.create_all(models_mod.get_engine())
    calls = []

    def fake_create(**kw):
        calls.append(kw)
        agent = MagicMock()
        agent.messages = []
        return agent

    monkeypatch.setattr(sm, "create_main_agent", fake_create)
    mgr = sm.ChatSessionManager()
    mgr.get_or_create("s1")
    mgr.get_or_create("s2", True)
    assert calls[0]["rich_output"] is True and not calls[0].get("read_only")
    assert calls[1]["rich_output"] is True and calls[1]["read_only"] is True


def test_other_builders_stay_plain():
    root = pathlib.Path(__file__).resolve().parents[1] / "src" / "agenticops"
    for p in ["scheduler/scheduler.py", "im/session_manager.py", "cli/main.py"]:
        assert "rich_output" not in (root / p).read_text(encoding="utf-8")
