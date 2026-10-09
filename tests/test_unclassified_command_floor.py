"""2.7.0 E2E observation 3: an approval no person sees never covers a step the code cannot classify.

The execution tools already gate an `unknown` command like a write; the gap was auto-approval, which trusts the
plan's own risk label. A fix plan or a change plan holding a step whose command is `unknown` (or that has no
command, so the executor would decide what to run) goes to a human instead, with one policy_decision event.
"""
from unittest.mock import MagicMock, patch

import pytest

from agenticops.auth.actor import agent_actor, cli_actor
from agenticops.models import Base, ChangeRequest, CloudAccount, CloudResource, FixPlan, PipelineEvent, get_session
# Imported before any test patches agenticops.models.get_db_session: a module first imported inside that patch
# would bind the mock for good (from-imports copy the name), and the change tests below need the real one.
from agenticops.services import change_service, issue_state, pipeline_service, plan_content  # noqa: F401
from agenticops.services.change_steps import plan_steps, rollback_steps, unclassified_commands
from agenticops.services.policy_engine import PolicyDecision

UNKNOWN = "aws custom-service do-thing --id 1"


# ── the pure reading ──────────────────────────────────────────────────


class TestUnclassifiedCommands:
    def test_classified_steps_pass(self):
        steps = [{"action": "add-on", "command": "aws eks create-addon --cluster-name lab --addon-name x"},
                 {"action": "wait", "command": "kubectl rollout status deploy/web"},
                 {"action": "restart", "command": "systemctl restart nginx"}]
        assert unclassified_commands(steps) == []

    def test_an_unknown_command_is_named(self):
        assert unclassified_commands([{"action": "x", "command": UNKNOWN}]) == [UNKNOWN]

    def test_a_step_without_a_command_is_unclassified(self):
        assert unclassified_commands([{"action": "restart the worker"}]) == ["(no command) restart the worker"]

    def test_a_blocked_command_is_left_to_the_blocked_rule(self):
        assert unclassified_commands([{"command": "aws iam create-user --user-name x"}]) == []

    def test_each_list_is_read_and_a_repeat_named_once(self):
        steps = [{"command": UNKNOWN}, {"command": UNKNOWN}]
        assert unclassified_commands(steps, [{"command": "aws other-svc go"}]) == [UNKNOWN, "aws other-svc go"]

    def test_legacy_string_steps_are_decoded(self):
        assert plan_steps('[{"action": "x", "command": "%s"}]' % UNKNOWN) == [{"action": "x", "command": UNKNOWN}]
        assert plan_steps(None) == []


class TestRollbackSteps:
    @pytest.mark.parametrize("rollback,expected", [
        ({"description": "scale both back"}, []),                                   # prose carries no command
        ({}, []),
        (None, []),
        ({"steps": [{"command": "kubectl rollout undo deploy/web"}]}, [{"command": "kubectl rollout undo deploy/web"}]),
        ({"commands": ["aws ec2 delete-tags --resources i-1"]}, ["aws ec2 delete-tags --resources i-1"]),
        (["kubectl rollout undo deploy/web"], ["kubectl rollout undo deploy/web"]),
        ('{"steps": ["systemctl restart worker"]}', ["systemctl restart worker"]),     # legacy JSON string
    ])
    def test_the_steps_a_rollback_carries(self, rollback, expected):
        assert rollback_steps(rollback) == expected

    def test_an_unknown_rollback_command_counts(self):
        assert unclassified_commands([], rollback_steps({"steps": [{"command": UNKNOWN}]})) == [UNKNOWN]


# ── fix plans: trigger_auto_approve ───────────────────────────────────


def _mock_plan(steps, rollback=None, risk="L1"):
    plan = MagicMock()
    plan.id, plan.status, plan.risk_level, plan.health_issue_id = 5, "draft", risk, 10
    plan.steps, plan.rollback_plan = steps, rollback if rollback is not None else {}
    return plan


def _run_auto_approve(plan, *, policy_engine: bool, decision=None):
    issue = MagicMock()
    issue.trace_id = "trace-abc"
    with patch("agenticops.services.pipeline_service.settings") as s, \
         patch("agenticops.services.pipeline_service.trigger_auto_execute") as execute, \
         patch("agenticops.services.pipeline_service._evaluate_policy_for_plan", return_value=decision), \
         patch("agenticops.services.pipeline_events.log_event") as log_event, \
         patch("agenticops.models.get_db_session") as get_db:
        s.auto_fix_enabled = s.executor_auto_approve_l0_l1 = True
        s.policy_engine_enabled = policy_engine
        session = MagicMock()
        session.__enter__ = MagicMock(return_value=session)
        session.__exit__ = MagicMock(return_value=False)
        session.query.return_value.filter_by.return_value.first.side_effect = [plan, issue, issue]
        get_db.return_value = session
        from agenticops.services.pipeline_service import trigger_auto_approve
        trigger_auto_approve(fix_plan_id=plan.id)
    return execute, log_event


def _floor_events(log_event):
    return [c for c in log_event.call_args_list
            if c.args[1:2] == ("policy_decision",) and c.kwargs["detail"]["policy_decision"]["rule"] == "unclassified_command"]


class TestFixPlanAutoApprove:
    def test_an_unknown_command_goes_to_a_human(self):
        plan = _mock_plan([{"action": "x", "command": UNKNOWN}])
        execute, log_event = _run_auto_approve(plan, policy_engine=False)
        assert plan.status == "draft"
        execute.assert_not_called()
        [event] = _floor_events(log_event)
        assert event.kwargs["status"] == "require_human"
        assert any(UNKNOWN in r for r in event.kwargs["detail"]["policy_decision"]["reasons"])

    def test_the_floor_holds_when_policy_says_auto_approve(self):
        plan = _mock_plan([{"command": "systemctl restart nginx"}], rollback={"steps": [{"command": UNKNOWN}]})
        decision = PolicyDecision(action="auto_approve", rule_name="auto-approve-low-risk")
        execute, log_event = _run_auto_approve(plan, policy_engine=True, decision=decision)
        assert plan.status == "draft"
        execute.assert_not_called()
        assert len(_floor_events(log_event)) == 1

    def test_a_plan_the_code_can_read_is_approved_as_before(self):
        plan = _mock_plan([{"command": "kubectl rollout restart deploy/web"}],
                          rollback={"description": "restart again"})
        execute, log_event = _run_auto_approve(plan, policy_engine=False)
        assert plan.status == "approved" and plan.approved_by == "agent:auto-pipeline"
        execute.assert_called_once()
        assert _floor_events(log_event) == []


# ── change plans: submit_review's standard-change auto-approval ────────


@pytest.fixture
def db(tmp_path):
    import agenticops.models as models_mod
    import agenticops.audit.models  # noqa: F401
    from agenticops.config import settings
    saved = settings.database_url
    models_mod._engine = None
    settings.database_url = f"sqlite:///{tmp_path}/floor.db"
    Base.metadata.create_all(models_mod.get_engine())
    s = get_session()
    acct = CloudAccount(name="dev", provider="aws", is_enabled=True, credentials={"account_id": "111111111111"},
                        regions=["ap-southeast-1"])
    s.add(acct); s.flush()
    s.add(CloudResource(account_id=acct.id, provider="aws", region="ap-southeast-1", resource_type="EC2Instance",
                        resource_id="i-0abc", name="web-1", tags={"Name": "web-1"}))
    s.commit()
    yield s
    s.close()
    models_mod._engine = None
    settings.database_url = saved


def _change_under_review(db, steps):
    from agenticops.services import change_service as cs
    with patch.object(cs, "notify_change_requested"):
        cr = cs.create_change_request(source="cli", actor=cli_actor(), title="tag", description="add Env=prod",
                                      account_name="dev", targets=["i-0abc"], requested_change_type="normal",
                                      start_review=False)
    with cs._session() as s:
        cs.transition_change(s.get(ChangeRequest, cr["id"]), "under_review")
    cs.ground_targets(cr["id"])
    db.add(FixPlan(plan_kind="change", change_request_id=cr["id"], risk_level="L1", title="p", summary="s",
                   steps=steps, rollback_plan={"steps": [{"command": "aws ec2 delete-tags --resources i-0abc"}]},
                   post_checks=[{"check": "tag present", "command": "aws ec2 describe-tags --filters x"}],
                   status="draft"))
    db.commit()
    return cr["id"]


class TestChangeAutoApprove:
    def _review(self, cr_id):
        from agenticops.config import settings
        from agenticops.services import change_service as cs
        with patch.object(settings, "change_auto_approve_standard", True), \
             patch.object(cs, "approve") as approve, patch.object(cs, "request_execution") as execute, \
             patch.object(cs, "notify_change_pending_approval") as notify:
            out = cs.submit_review(cr_id, verdict="approved_for_planning", risk_level="L1", action_type="tag",
                                   reasons=["ok"], actor=agent_actor("sre"))
        return out, approve, execute, notify

    def test_an_unknown_command_makes_a_standard_change_wait_for_a_person(self, db):
        cr_id = _change_under_review(db, [{"action": "tag", "command": UNKNOWN}])
        out, approve, execute, notify = self._review(cr_id)
        approve.assert_not_called()
        execute.assert_not_called()
        notify.assert_called_once()
        assert out["status"] == "planned"
        assert out["policy_rule"] == "unclassified_command" and out["policy_action"] == "require_human"
        assert out["effective_change_type"] == "normal"
        [event] = db.query(PipelineEvent).filter_by(change_request_id=cr_id, event_type="policy_decision").all()
        assert event.status == "require_human"

    def test_a_classified_standard_change_still_auto_approves(self, db):
        cr_id = _change_under_review(db, [{"action": "tag", "command": "aws ec2 create-tags --resources i-0abc"}])
        out, approve, execute, notify = self._review(cr_id)
        approve.assert_called_once()
        assert out is not None
