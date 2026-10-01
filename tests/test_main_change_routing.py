# tests/test_main_change_routing.py
from unittest.mock import MagicMock, patch

MODE_C = {"ground_change_targets", "attach_change_target", "evaluate_change_policy", "submit_change_review"}
CHANGE_TOOLS = {"request_change", "review_change", "get_change_request", "list_change_requests", "execute_change"}


def _name(t):
    return getattr(t, "tool_name", None) or getattr(t, "__name__", str(t))


def _build_main(flag: bool):
    from agenticops.config import settings
    from agenticops.agents.main_agent import create_main_agent
    with patch.object(settings, "change_management_enabled", flag), \
         patch("agenticops.agents.main_agent.Agent") as MockAgent, \
         patch("agenticops.agents.main_agent.BedrockModel"), \
         patch("agenticops.agents.main_agent.build_system_prompt", side_effect=lambda p, **kw: p), \
         patch("agenticops.config.get_bedrock_boto_session", return_value=MagicMock()), \
         patch("agenticops.agents.main_agent._safe_mcp_clients", return_value=[]), \
         patch("agenticops.memory.curator.maybe_run_curator"), \
         patch("agenticops.skills.curator.maybe_run_skills_curator"):
        MockAgent.return_value = MagicMock()
        create_main_agent()
    kw = MockAgent.call_args.kwargs
    return kw["system_prompt"], {_name(t) for t in kw["tools"]}


def test_main_prompt_routes_changes():
    from agenticops.agents.main_agent import CHANGE_MANAGEMENT_PROMPT, MAIN_SYSTEM_PROMPT
    for s in ("5.7.", "request_change", "review_change", "execute_change", "C#N", "[CHANGE REQUEST]",
              "change_required", "<referenced_change>", "approve_fix_plan", "HUMAN"):
        assert s in CHANGE_MANAGEMENT_PROMPT, s
    for s in ("request_change", "review_change", "execute_change", "C#", "[CHANGE REQUEST]",
              "change_required", "referenced_change"):
        assert s not in MAIN_SYSTEM_PROMPT, s


def test_change_management_prompt_follows_flag():
    from agenticops.config import settings
    from agenticops.agents.main_agent import CHANGE_MANAGEMENT_PROMPT, change_management_prompt
    with patch.object(settings, "change_management_enabled", True):
        assert change_management_prompt() == CHANGE_MANAGEMENT_PROMPT
    with patch.object(settings, "change_management_enabled", False):
        assert change_management_prompt() == ""


def test_change_tools_gated_by_setting():
    from agenticops.config import settings
    from agenticops.agents.main_agent import change_management_tools
    with patch.object(settings, "change_management_enabled", True):
        names = [_name(t) for t in change_management_tools()]
    assert names == ["request_change", "review_change", "get_change_request", "list_change_requests", "execute_change"]
    with patch.object(settings, "change_management_enabled", False):
        assert change_management_tools() == []


def test_main_agent_composition_flag_on():
    from agenticops.agents.main_agent import CHANGE_MANAGEMENT_PROMPT, MAIN_SYSTEM_PROMPT
    prompt, names = _build_main(True)
    assert prompt.startswith(MAIN_SYSTEM_PROMPT) and CHANGE_MANAGEMENT_PROMPT in prompt
    assert CHANGE_TOOLS <= names
    assert not (MODE_C & names)


def test_main_agent_composition_flag_off():
    from agenticops.agents.main_agent import MAIN_SYSTEM_PROMPT
    prompt, names = _build_main(False)
    assert prompt.startswith(MAIN_SYSTEM_PROMPT)
    assert "request_change" not in prompt and "C#" not in prompt
    assert not ((CHANGE_TOOLS | MODE_C) & names)


def test_change_ref_resolution(tmp_path, monkeypatch):
    import agenticops.models as models_mod
    from agenticops.config import settings
    from agenticops.models import Base, ChangeRequest, get_session
    monkeypatch.setattr(models_mod, "_engine", None)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/ref.db")
    monkeypatch.setattr(settings, "change_management_enabled", True)
    Base.metadata.create_all(models_mod.get_engine())
    s = get_session()
    s.add(ChangeRequest(title="Tag web", description="add Env=prod", requested_by="cli:m", status="planned", risk_level="L1"))
    s.commit(); s.close()
    from agenticops.chat.preprocessor import resolve_references
    text, warnings = resolve_references("please approve C#1 and look at C#99")
    assert '<referenced_change id="1">' in text and "Tag web" in text and "planned" in text
    assert warnings == ["ChangeRequest C#99 not found"]
    text, warnings = resolve_references("C#1 twice: C#1, and C#99 C#99")
    assert text.count('<referenced_change id="1">') == 1
    assert warnings == ["ChangeRequest C#99 not found"]


def test_change_refs_come_from_the_typed_text_only():
    """A C#N inside an attached file (web upload or CLI @file) never pulls that change request into the prompt;
    the same C#N typed by the user does."""
    from agenticops.config import settings
    from agenticops.chat.preprocessor import preprocess_message
    block = '<referenced_change id="7">\nTitle: Tag web\n</referenced_change>'
    pre = "agenticops.chat.preprocessor"
    with patch.object(settings, "change_management_enabled", True), \
         patch(f"{pre}._resolve_change_ref", side_effect=lambda i: block if i == 7 else None) as rc, \
         patch(f"{pre}.is_image_file", return_value=False), patch(f"{pre}.is_document_file", return_value=False), \
         patch(f"{pre}.read_file_as_text", return_value=("rollout notes: see C#7", None)):
        uploaded, w1 = preprocess_message("summarize this", file_contents=[("notes.txt", "rollout notes: see C#7")])
        cli, w2 = preprocess_message("summarize @/tmp/notes.txt", resolve_file_refs=True)
        assert "see C#7" in uploaded and "see C#7" in cli  # the files are attached, their C#7 is not resolved
        assert block not in uploaded and block not in cli and (w1, w2) == ([], [])
        rc.assert_not_called()
        typed, w3 = preprocess_message("approve C#7", file_contents=[("notes.txt", "rollout notes: see C#7")])
    assert typed.count(block) == 1 and w3 == []
    rc.assert_called_once_with(7)


def test_change_refs_ignored_when_disabled():
    from agenticops.config import settings
    from agenticops.chat.preprocessor import resolve_references
    with patch.object(settings, "change_management_enabled", False), \
         patch("agenticops.chat.preprocessor._resolve_change_ref", return_value=None) as rc:
        assert resolve_references("approve C#1") == ("approve C#1", [])
    rc.assert_not_called()


def test_notifications_format_and_severity():
    from agenticops.services import notification_service as ns
    cr = {"id": 3, "title": "Tag web", "requested_by": "user:alice", "risk_level": "L1", "requested_change_type": "normal",
          "effective_change_type": "standard", "account_id": 1, "target_resources": [{"resource_id": "i-0abc"}]}
    with patch.object(ns, "notify_event") as ne:
        ns.notify_change_requested({**cr, "risk_level": None, "target_resources": [], "target_hints": ["web-1"]})
        ns.notify_change_pending_approval(cr, {"id": 9, "label": "C#3 implementation plan v1", "title": "p",
                                               "risk_level": "L1", "summary": "s"})
        ns.notify_change_result(cr, "completed")
        ns.notify_change_result({**cr, "risk_level": "L3"}, "failed")
        ns.notify_change_result(cr, "needs_review")
    calls = ne.call_args_list
    assert calls[0].args[0] == "change_requested" and "Change #3" in calls[0].args[1] and calls[0].args[3] == "medium"
    assert "to be grounded: web-1" in calls[0].args[2]
    assert calls[1].args[0] == "change_pending_approval" and "/app/changes/3" in calls[1].args[2] and calls[1].args[3] == "low"
    assert "C#3 implementation plan v1: p" in calls[1].args[2] and "Plan #" not in calls[1].args[2]
    assert calls[2].args[0] == "change_result" and "COMPLETED" in calls[2].args[1] and calls[2].args[3] == "low"
    assert calls[3].args[3] == "high"
    assert calls[4].args[0] == "change_result" and calls[4].args[3] == "high"


def test_pending_approval_body_carries_the_plan_summary():
    """The approver needs the plan's summary; an empty one adds no line, and it stays one line of 500 chars."""
    from agenticops.services import notification_service as ns
    cr = {"id": 3, "title": "Tag web", "requested_by": "user:alice", "risk_level": "L1",
          "effective_change_type": "standard"}
    plan = {"id": 9, "label": "C#3 implementation plan v1", "title": "p", "risk_level": "L1"}

    def body(summary):
        with patch.object(ns, "notify_event") as ne:
            ns.notify_change_pending_approval(cr, {**plan, "summary": summary})
        return ne.call_args.args[2]

    assert "C#3 implementation plan v1: p\nSummary: Add tag Env=prod to i-0abc; no restart.\nRisk: L1\n" in body(
        "Add tag Env=prod to i-0abc; no restart.")
    for empty in ("", None, "  \n "):
        assert "Summary:" not in body(empty) and "C#3 implementation plan v1: p\nRisk: L1\n" in body(empty)
    # one line, so a summary cannot forge the Risk line under it; then 500 characters
    assert "Summary: tag it Risk: L0\nRisk: L1\n" in body("tag it\n\nRisk: L0")
    assert f"Summary: {'x' * 500}\nRisk: L1\n" in body("x" * 600)
