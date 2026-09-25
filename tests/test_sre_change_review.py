from unittest.mock import MagicMock, patch


def test_prompt_has_mode_c_and_stays_english():
    from agenticops.agents.sre_agent import SRE_SYSTEM_PROMPT
    assert "MODE C" in SRE_SYSTEM_PROMPT and "CHANGE REVIEW PROTOCOL" in SRE_SYSTEM_PROMPT
    for kw in ("ground_change_targets", "attach_change_target", "evaluate_change_policy", "submit_change_review",
               "plan_kind='change'", "needs_clarification", "rollback"):
        assert kw in SRE_SYSTEM_PROMPT
    assert "THREE modes" in SRE_SYSTEM_PROMPT


def test_sre_tool_list_includes_change_tools():
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
         patch.object(mod, "build_system_prompt", return_value="p"):
        mod._create_sre_agent()
    names = {getattr(t, "__name__", None) or getattr(t, "tool_name", None) or str(t) for t in captured["tools"]}
    for n in ("ground_change_targets", "attach_change_target", "evaluate_change_policy", "submit_change_review", "get_change_request"):
        assert any(n in str(x) for x in names), n


def test_sre_agent_review_change_invokes_agent_with_mode_c_prompt():
    from agenticops.agents import sre_agent as mod
    fake_agent = MagicMock()
    with patch.object(mod, "_create_sre_agent", return_value=fake_agent) as create, \
         patch("agenticops.agents.preamble.invoke_with_retry", return_value="verdict delivered") as invoke, \
         patch("agenticops.services.change_service.get_change", return_value={"id": 5, "account_id": None}):
        out = mod.sre_agent_review_change(5)
    assert out == "verdict delivered"
    prompt = invoke.call_args.args[1]
    assert "ChangeRequest #5" in prompt and "MODE C" in prompt
    create.assert_called_once()


def test_review_change_tool_wraps_start_review():
    from agenticops.agents.sre_agent import review_change
    with patch("agenticops.services.change_service.start_review", return_value="reviewed text") as sr:
        assert review_change(7) == "reviewed text"
    sr.assert_called_once_with(7, sync=True)
    from agenticops.services import change_service as cs
    with patch("agenticops.services.change_service.start_review", side_effect=cs.ChangeStateError("is 'planned'")):
        assert "planned" in review_change(7)
