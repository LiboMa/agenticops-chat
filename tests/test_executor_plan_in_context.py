"""A run knows which plan it runs, whoever started it (review of MVP-2.9.0, a finding next to «之后» 22).

`executor_agent` opened its run context without `fix_plan_id`. The queue (`executor_service`) and the approval
thread (`pipeline_service`) set it around the call, so their runs had it; a run Main starts from a chat did not:
`approved_plan_in_context()` was None there, a `systemctl restart` of the approved plan was refused as «needs a
change», and its ledger rows named no plan."""
from unittest.mock import patch

from agenticops.models import get_session
from agenticops.run_context import get_run_context, run_context
from tests.test_viewer_role import _temp_db


def test_a_run_started_without_a_plan_in_its_callers_context_carries_its_own(tmp_path, monkeypatch):
    from agenticops.config import settings
    from agenticops.services.command_audit import approved_plan_in_context
    from tests import test_run_measured_facts as facts
    _temp_db(tmp_path, monkeypatch, "plan-in-context.db")
    monkeypatch.setattr(settings, "executor_enabled", True)
    db = get_session()
    try:
        plan_id = facts._approved_plan(db)
    finally:
        db.close()
    seen = {}

    def invoke(agent, prompt, **kw):
        seen["plan"], seen["approved"] = get_run_context().fix_plan_id, approved_plan_in_context()
        return "done"

    with run_context(actor="user:chat-person"), facts._executor_build(), \
            patch("agenticops.agents.preamble.invoke_with_retry", side_effect=invoke):
        assert get_run_context().fix_plan_id is None                 # a chat turn: no plan in its context
        from agenticops.agents.executor_agent import executor_agent
        assert executor_agent(fix_plan_id=plan_id) == "done"
        assert get_run_context().fix_plan_id is None                 # … and none left behind
    assert seen == {"plan": plan_id, "approved": plan_id}
