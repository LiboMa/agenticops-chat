import re
from unittest.mock import MagicMock, patch

import pytest

MODE_C_TOOLS = ("get_change_request", "ground_change_targets", "attach_change_target", "evaluate_change_policy",
                "submit_change_review")


def test_prompt_has_mode_c_and_stays_english():
    from agenticops.agents.sre_agent import SRE_SYSTEM_PROMPT
    assert "MODE C" in SRE_SYSTEM_PROMPT and "CHANGE REVIEW PROTOCOL" in SRE_SYSTEM_PROMPT
    for kw in ("ground_change_targets", "attach_change_target", "evaluate_change_policy", "submit_change_review",
               "plan_kind='change'", "needs_clarification", "rollback"):
        assert kw in SRE_SYSTEM_PROMPT
    assert "THREE modes" in SRE_SYSTEM_PROMPT
    # the attach names the hint it resolves, ASSESS uses the Mode A rubric's words, POLICY uses the tool's
    # parameter names and a block skips PLAN, and the guardrail covers Mode C
    for kw in ("hint='<the unresolved hint, verbatim>'", "resize are L2; restart service,",
               "evaluate_change_policy(N, risk_level, action_type)", "skip PLAN",
               "Only generate plans (Mode A/C) or query information (Mode B)."):
        assert kw in SRE_SYSTEM_PROMPT, kw
    assert not re.search(r"[一-鿿]", SRE_SYSTEM_PROMPT)


def test_the_base_prompt_is_the_full_prompt_without_mode_c():
    """The Mode A/B builds do not carry the Mode C tools, so their prompt must not describe them."""
    from agenticops.agents.sre_agent import SRE_BASE_PROMPT, SRE_SYSTEM_PROMPT
    for kw in ("MODE C", "C#N", "CHANGE REVIEW", "plan_kind='change'", "(Mode A/C)", *MODE_C_TOOLS):
        assert kw not in SRE_BASE_PROMPT, kw
    for kw in ("READ-ONLY", "NEVER execute fixes", "save_fix_plan", "L0", "L1", "L2", "L3", "TWO modes",
               "Only generate plans (Mode A) or query information (Mode B)."):
        assert kw in SRE_BASE_PROMPT, kw
    # one blank line between Mode B and the rules, as between every other pair of sections
    assert "and key attributes.\n\nRULES & GUARDRAILS (CRITICAL):" in SRE_BASE_PROMPT
    assert not re.search(r"[一-鿿]", SRE_BASE_PROMPT)
    assert SRE_SYSTEM_PROMPT.count("MODE C — CHANGE REVIEW PROTOCOL") == 1


def test_a_broken_anchor_fails_at_import_rather_than_leaking_mode_c():
    from agenticops.agents import sre_agent as mod
    for broken in (mod.SRE_SYSTEM_PROMPT.replace("(Mode A/C)", "(Modes A and C)"),        # anchor gone
                   mod.SRE_SYSTEM_PROMPT + "You have THREE modes of operation:\n",        # anchor twice
                   mod.SRE_SYSTEM_PROMPT.replace("RULES & GUARDRAILS (CRITICAL):", "RULES:")):
        with pytest.raises(RuntimeError, match="exactly once"):
            mod._without_mode_c(broken)


def _build(**kwargs) -> dict:
    """Run _create_sre_agent with nothing real behind it: capture the Agent's tools and the prompt it is given."""
    from agenticops.agents import sre_agent as mod
    captured = {}

    class FakeAgent:
        def __init__(self, **kw):
            captured["tools"] = kw["tools"]

    with patch.object(mod, "Agent", FakeAgent), patch.object(mod, "BedrockModel", MagicMock()), \
         patch("agenticops.config.get_agent_model_config", return_value=("m", 100)), \
         patch("agenticops.config.get_agent_conversation_manager", return_value=None), \
         patch("agenticops.config.get_agent_context_manager", return_value=None), \
         patch("agenticops.config.get_bedrock_boto_session", return_value=None), \
         patch("agenticops.agents.preamble.bedrock_model_kwargs", return_value={}), \
         patch.object(mod, "build_system_prompt", return_value="p") as build_prompt:
        mod._create_sre_agent(**kwargs)
    build_prompt.assert_called_once()
    captured["prompt"], = build_prompt.call_args.args
    captured["prompt_kwargs"] = build_prompt.call_args.kwargs
    return captured


def _built_tool_names(**kwargs) -> set:
    return {getattr(t, "tool_name", None) or getattr(t, "__name__", None) or str(t) for t in _build(**kwargs)["tools"]}


def test_only_the_change_review_build_is_given_the_mode_c_prompt():
    from agenticops.agents import sre_agent as mod
    same_kwargs = {"include_account": False, "agent_type": "sre", "agent_name": "sre"}
    for kwargs in ({}, {"cli_tools": [MagicMock()]}):  # the Mode A (sre_agent) and Mode B (sre_query) builds
        built = _build(**kwargs)
        assert "MODE C" not in built["prompt"], kwargs
        assert built["prompt"] == mod.SRE_BASE_PROMPT, kwargs
        assert built["prompt_kwargs"] == same_kwargs, kwargs
    built = _build(change_review=True)
    assert built["prompt"] == mod.SRE_SYSTEM_PROMPT
    assert built["prompt_kwargs"] == same_kwargs


def test_mode_c_tools_only_in_the_change_review_build():
    review = _built_tool_names(change_review=True)
    assert set(MODE_C_TOOLS) <= review and "save_fix_plan" in review
    default = _built_tool_names()  # the Mode A (sre_agent) and Mode B (sre_query) builds
    assert not set(MODE_C_TOOLS) & default
    assert "save_fix_plan" in default


def test_sre_agent_review_change_invokes_agent_with_mode_c_prompt():
    from agenticops.agents import sre_agent as mod
    fake_agent = MagicMock()
    with patch.object(mod, "_create_sre_agent", return_value=fake_agent) as create, \
         patch("agenticops.agents.preamble.invoke_with_retry", return_value="verdict delivered") as invoke, \
         patch("agenticops.services.change_service.get_change", return_value={"id": 5, "account_id": None}), \
         patch("agenticops.services.agent_log_service.log_agent_call") as log:
        out = mod.sre_agent_review_change(5)
    assert out == "verdict delivered"
    prompt = invoke.call_args.args[1]
    assert "ChangeRequest #5" in prompt and "MODE C" in prompt
    create.assert_called_once_with(cli_tool=None, change_review=True)
    log.assert_called_once()  # the tracker's AgentLog write is intercepted — no row in the real database


def test_sre_agent_review_change_is_addressed_to_the_requests_account():
    from agenticops.agents import sre_agent as mod
    account_tool = object()
    with patch.object(mod, "_create_sre_agent", return_value=MagicMock()) as create, \
         patch.object(mod, "get_cli_tool_for_issue", return_value=account_tool) as resolve, \
         patch.object(mod, "_account_name", return_value="dev"), \
         patch("agenticops.agents.preamble.invoke_with_retry", return_value="ok") as invoke, \
         patch("agenticops.services.change_service.get_change", return_value={"id": 5, "account_id": 3}), \
         patch("agenticops.services.agent_log_service.log_agent_call"):
        mod.sre_agent_review_change(5)
    resolve.assert_called_once_with(3)
    create.assert_called_once_with(cli_tool=account_tool, change_review=True)
    assert "account='dev'" in invoke.call_args.args[1]


def test_sre_agent_review_change_fails_closed_when_account_credentials_fail():
    """Credential rule: never fall back to the default, auto-resolving CLI tool (it may be another account)."""
    from agenticops.agents import sre_agent as mod
    with patch.object(mod, "_create_sre_agent") as create, \
         patch.object(mod, "get_cli_tool_for_issue", return_value=None), \
         patch.object(mod, "_account_name", return_value="dev"), \
         patch("agenticops.agents.preamble.invoke_with_retry") as invoke, \
         patch("agenticops.services.change_service.get_change", return_value={"id": 5, "account_id": 3}), \
         patch("agenticops.services.agent_log_service.log_agent_call"):
        with pytest.raises(RuntimeError, match="could not be resolved"):
            mod.sre_agent_review_change(5)
    create.assert_not_called()
    invoke.assert_not_called()


def test_review_change_tool_wraps_start_review():
    from agenticops.agents.sre_agent import review_change
    with patch("agenticops.services.change_service.start_review", return_value="reviewed text") as sr, \
         patch("agenticops.services.change_service.get_change", return_value={"status": "planned", "review_reasons": []}):
        out = review_change(7)
    sr.assert_called_once_with(7, sync=True)
    assert "reviewed text" in out and "Platform status of C#7: planned" in out
    from agenticops.services import change_service as cs
    with patch("agenticops.services.change_service.start_review", side_effect=cs.ChangeStateError("is 'planned'")):
        assert "planned" in review_change(7)


def test_review_change_reports_a_rolled_back_review():
    """A crashed review returns None and the platform rolled the CR back to draft — never 'Review finished.'"""
    from agenticops.agents.sre_agent import review_change
    with patch("agenticops.services.change_service.start_review", return_value=None), \
         patch("agenticops.services.change_service.get_change",
               return_value={"status": "draft", "review_reasons": ["review crashed: boom"]}):
        out = review_change(7)
    assert "draft" in out and "review crashed: boom" in out
    assert "Review finished" not in out
    # no verdict: the SRE's own text is kept, but the platform's rollback is stated next to it
    with patch("agenticops.services.change_service.start_review", return_value="all looks fine"), \
         patch("agenticops.services.change_service.get_change",
               return_value={"status": "draft", "review_reasons": ["review ended without a verdict"]}):
        out = review_change(7)
    assert "all looks fine" in out and "did not complete (review ended without a verdict)" in out
    assert "Nothing was approved." in out


def test_review_change_when_the_request_cannot_be_reread():
    from agenticops.agents.sre_agent import review_change
    from agenticops.services import change_service as cs
    with patch("agenticops.services.change_service.start_review", return_value=None), \
         patch("agenticops.services.change_service.get_change", side_effect=cs.ChangeNotFound("gone")):
        assert review_change(7) == "Review ended; the change request could not be re-read."
