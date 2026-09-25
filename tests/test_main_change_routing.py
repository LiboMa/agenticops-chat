# tests/test_main_change_routing.py
from unittest.mock import patch


def test_main_prompt_routes_changes():
    from agenticops.agents.main_agent import MAIN_SYSTEM_PROMPT as p
    assert "5.7." in p and "request_change" in p and "review_change" in p
    assert "C#N" in p and "[CHANGE REQUEST]" in p
    assert "change_required" in p  # rule 10 addendum


def test_change_tools_gated_by_setting():
    from agenticops.config import settings
    from agenticops.agents.main_agent import change_management_tools
    with patch.object(settings, "change_management_enabled", True):
        names = [getattr(t, "tool_name", None) or getattr(t, "__name__", str(t)) for t in change_management_tools()]
    assert any("request_change" in n for n in names) and any("review_change" in n for n in names)
    with patch.object(settings, "change_management_enabled", False):
        assert change_management_tools() == []


def test_change_ref_resolution(tmp_path):
    import agenticops.models as models_mod
    from agenticops.config import settings
    from agenticops.models import Base, ChangeRequest, get_session
    models_mod._engine = None
    settings.database_url = f"sqlite:///{tmp_path}/ref.db"
    Base.metadata.create_all(models_mod.get_engine())
    s = get_session()
    s.add(ChangeRequest(title="Tag web", description="add Env=prod", requested_by="cli:m", status="planned", risk_level="L1"))
    s.commit(); s.close()
    from agenticops.chat.preprocessor import resolve_references
    text, warnings = resolve_references("please approve C#1 and look at C#99")
    assert '<referenced_change id="1">' in text and "Tag web" in text and "planned" in text
    assert warnings == ["ChangeRequest C#99 not found"]
    models_mod._engine = None


def test_notifications_format_and_severity():
    from agenticops.services import notification_service as ns
    cr = {"id": 3, "title": "Tag web", "requested_by": "user:alice", "risk_level": "L1", "requested_change_type": "normal",
          "effective_change_type": "standard", "account_id": 1, "target_resources": [{"resource_id": "i-0abc"}]}
    with patch.object(ns, "notify_event") as ne:
        ns.notify_change_requested(cr)
        ns.notify_change_pending_approval(cr, {"id": 9, "title": "p", "risk_level": "L1", "summary": "s"})
        ns.notify_change_result(cr, "completed")
        ns.notify_change_result({**cr, "risk_level": "L3"}, "failed")
    calls = ne.call_args_list
    assert calls[0].args[0] == "change_requested" and "Change #3" in calls[0].args[1] and calls[0].args[3] == "low"
    assert calls[1].args[0] == "change_pending_approval" and "/app/changes/3" in calls[1].args[2] and calls[1].args[3] == "low"
    assert calls[2].args[0] == "change_result" and "COMPLETED" in calls[2].args[1] and calls[2].args[3] == "low"
    assert calls[3].args[3] == "high"
