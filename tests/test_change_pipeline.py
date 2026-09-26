# tests/test_change_pipeline.py
"""Change Management closed loop with mocked agents (SRE / Executor replaced by functions that call the REAL tools)."""
import json
from unittest.mock import patch

import pytest

from agenticops.auth.actor import Actor
from agenticops.models import Base, ChangeRequest, CloudAccount, CloudResource, FixExecution, FixPlan, PipelineEvent, get_session

ALICE = Actor("user", "alice", 1, ("read", "write"))
BOB = Actor("user", "bob", 2, ("read", "write"))


@pytest.fixture
def db(tmp_path, monkeypatch):
    import agenticops.models as models_mod
    import agenticops.audit.models  # noqa: F401
    from agenticops.config import settings
    monkeypatch.setattr(models_mod, "_engine", None)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/pipe.db")
    monkeypatch.setattr(settings, "change_management_enabled", True)
    monkeypatch.setattr(settings, "change_auto_approve_standard", False)
    monkeypatch.setattr(settings, "executor_enabled", False)
    monkeypatch.setattr(settings, "rbac_enforce", False)
    Base.metadata.create_all(models_mod.get_engine())
    s = get_session()
    acct = CloudAccount(name="dev", provider="aws", is_enabled=True, credentials={}, regions=["ap-southeast-1"]); s.add(acct); s.flush()
    s.add(CloudResource(account_id=acct.id, provider="aws", region="ap-southeast-1", resource_type="EC2Instance", resource_id="i-0abc", name="web"))
    s.commit()
    yield s
    s.close()


def fake_sre_review(change_request_id: int) -> str:
    """What a well-behaved SRE Mode C run does, using the real tools."""
    from agenticops.tools.change_tools import evaluate_change_policy, ground_change_targets, submit_change_review
    from agenticops.tools.metadata_tools import save_fix_plan
    g = json.loads(ground_change_targets(change_request_id))
    if g["unresolved"]:
        return submit_change_review(change_request_id, "needs_clarification", reasons="unresolved: " + ", ".join(g["unresolved"]))
    evaluate_change_policy(change_request_id, "L1", "tag")
    save_fix_plan(plan_kind="change", change_request_id=change_request_id, risk_level="L1", title="Tag i-0abc", summary="add Env=prod",
                  steps=json.dumps([{"action": "tag", "command": "aws ec2 create-tags --resources i-0abc --tags Key=Env,Value=prod"}]),
                  rollback_plan=json.dumps({"steps": [{"command": "aws ec2 delete-tags --resources i-0abc --tags Key=Env"}]}),
                  post_checks=json.dumps([{"check": "tag present", "command": "aws ec2 describe-tags --filters Name=resource-id,Values=i-0abc"}]))
    return submit_change_review(change_request_id, "approved_for_planning", "L1", "tag", "single instance tag; reversible")


def make_fake_executor(post_results, status="succeeded"):
    def fake_executor(fix_plan_id: int) -> str:
        from agenticops.tools.metadata_tools import get_approved_fix_plan, save_execution_result
        plan = json.loads(get_approved_fix_plan(fix_plan_id))
        assert plan["plan_kind"] == "change"
        return save_execution_result(fix_plan_id=fix_plan_id, health_issue_id=None, status=status,
                                     step_results=json.dumps([{"step_index": 0, "command": plan["steps"][0]["command"], "status": "ok"}]),
                                     post_check_results=json.dumps(post_results))
    return fake_executor


def _run_executor_for(cr_id):
    from agenticops.services.executor_service import ExecutorService
    s = get_session()
    ex = s.query(FixExecution).join(FixPlan).filter(FixPlan.change_request_id == cr_id).order_by(FixExecution.id.desc()).first()
    ex_id, plan_id = ex.id, ex.fix_plan_id
    ex.status = "running"; s.commit(); s.close()
    ExecutorService()._run_executor(ex_id, plan_id)


@pytest.fixture
def quiet():
    with patch("agenticops.services.change_service.notify_change_requested"), \
         patch("agenticops.services.change_service.notify_change_pending_approval"), \
         patch("agenticops.services.change_service.notify_change_result"):
        yield


def test_main_path_request_review_approve_execute_complete(db, quiet):
    from agenticops.config import settings
    from agenticops.services import change_service as cs
    cr = cs.create_change_request(source="chat", actor=ALICE, title="Tag web", description="add Env=prod to i-0abc",
                                  account_name="dev", targets=["i-0abc"], start_review=False)
    with patch("agenticops.agents.sre_agent.sre_agent_review_change", side_effect=fake_sre_review):
        cs.start_review(cr["id"], sync=True)
    c = cs.get_change(cr["id"])
    assert c["status"] == "planned" and c["risk_level"] == "L1" and c["effective_change_type"] == "standard"
    # no write command may have executed before approval
    from agenticops.models import CommandAudit
    assert db.query(CommandAudit).filter_by(change_request_id=cr["id"], outcome="executed").count() == 0
    cs.approve(cr["id"], actor=BOB, reason="reviewed")
    with patch.object(settings, "executor_enabled", True):
        cs.request_execution(cr["id"], actor=BOB)
    with patch("agenticops.agents.executor_agent.executor_agent", side_effect=make_fake_executor([{"check": "tag present", "status": "pass"}])):
        _run_executor_for(cr["id"])
    # 9b/9c contract: the queued ticket is closed IN PLACE (no second row), and the plan reaches `executed`
    db.expire_all()
    plan = db.query(FixPlan).filter_by(change_request_id=cr["id"], plan_kind="change").one()
    tickets = db.query(FixExecution).filter_by(fix_plan_id=plan.id).all()
    assert len(tickets) == 1 and tickets[0].status == "succeeded"
    assert plan.status == "executed"
    final = cs.get_change(cr["id"])
    assert final["status"] == "completed" and final["closed_at"]
    from agenticops.audit.models import AuditLog
    actions = [a.action for a in db.query(AuditLog).filter_by(entity_type="change_request", entity_id=str(cr["id"]))]
    for expected in ("change.requested", "change.reviewed", "change.approved", "change.execution_started", "change.completed"):
        assert expected in actions
    events = [e.event_type for e in db.query(PipelineEvent).filter_by(change_request_id=cr["id"])]
    assert "policy_decision" in events and "execution_completed" in events


def test_auto_approve_branch(db, quiet):
    from agenticops.config import settings
    from agenticops.services import change_service as cs
    cr = cs.create_change_request(source="web", actor=ALICE, title="Tag", description="d", account_name="dev", targets=["i-0abc"], start_review=False)
    with patch.object(settings, "change_auto_approve_standard", True), patch.object(settings, "executor_enabled", True), \
         patch("agenticops.agents.sre_agent.sre_agent_review_change", side_effect=fake_sre_review):
        cs.start_review(cr["id"], sync=True)
    c = cs.get_change(cr["id"])
    assert c["status"] == "executing" and c["approved_by"] == "agent:auto-pipeline" and "change-standard-low-risk" in c["approval_reason"]
    assert db.query(FixExecution).count() == 1


def test_needs_review_when_post_checks_missing(db, quiet):
    from agenticops.config import settings
    from agenticops.services import change_service as cs
    cr = cs.create_change_request(source="web", actor=ALICE, title="Tag", description="d", account_name="dev", targets=["i-0abc"], start_review=False)
    with patch("agenticops.agents.sre_agent.sre_agent_review_change", side_effect=fake_sre_review):
        cs.start_review(cr["id"], sync=True)
    cs.approve(cr["id"], actor=BOB, reason="ok")
    with patch.object(settings, "executor_enabled", True):
        cs.request_execution(cr["id"], actor=BOB)
    with patch("agenticops.agents.executor_agent.executor_agent", side_effect=make_fake_executor([])):
        _run_executor_for(cr["id"])
    assert cs.get_change(cr["id"])["status"] == "needs_review"
    out = cs.resolve_review(cr["id"], actor=BOB, outcome="completed", reason="verified in console")
    assert out["status"] == "completed"


def test_needs_clarification_then_clarify(db, quiet):
    from agenticops.services import change_service as cs
    cr = cs.create_change_request(source="web", actor=ALICE, title="Tag", description="tag the web box", account_name="dev",
                                  targets=["web-box-typo"], start_review=False)
    with patch("agenticops.agents.sre_agent.sre_agent_review_change", side_effect=fake_sre_review):
        cs.start_review(cr["id"], sync=True)
    assert cs.get_change(cr["id"])["status"] == "needs_clarification"
    with cs._session() as s:
        row = s.get(ChangeRequest, cr["id"]); row.target_hints = ["i-0abc"]
    with patch("agenticops.services.change_service.start_review") as sr:
        cs.clarify(cr["id"], actor=ALICE, message="I meant i-0abc")
    sr.assert_called_once()


def test_policy_block_rejects(db, quiet):
    from agenticops.services import change_service as cs
    from agenticops.services.policy_engine import PolicyDecision
    cr = cs.create_change_request(source="web", actor=ALICE, title="Tag", description="d", account_name="dev", targets=["i-0abc"], start_review=False)
    with patch("agenticops.agents.sre_agent.sre_agent_review_change", side_effect=fake_sre_review), \
         patch.object(cs, "evaluate_policy", return_value=PolicyDecision(action="block", rule_name="freeze-window-block", reasons=["freeze"])):
        cs.start_review(cr["id"], sync=True)
    c = cs.get_change(cr["id"])
    assert c["status"] == "rejected" and c["policy_rule"] == "freeze-window-block"


def test_watchdog_rollback_when_sre_never_answers(db, quiet):
    from agenticops.services import change_service as cs
    cr = cs.create_change_request(source="web", actor=ALICE, title="Tag", description="d", account_name="dev", targets=["i-0abc"], start_review=False)
    with patch("agenticops.agents.sre_agent.sre_agent_review_change", return_value="…"):
        cs.start_review(cr["id"], sync=True)  # returned without a verdict → rolled back to draft
    assert cs.get_change(cr["id"])["status"] == "draft"
    with patch.object(cs.threading, "Thread"), patch.object(cs.threading, "Timer"):
        out = cs.restart_review(cr["id"], actor=ALICE)  # human can retry from the UI (thread not really started here)
    assert out["status"] == "under_review"
