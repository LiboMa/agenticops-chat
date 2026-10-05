# tests/test_change_pipeline.py
"""Change Management closed loop with mocked agents (SRE / Executor replaced by functions that call the REAL tools)."""
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from agenticops.auth.actor import Actor
from agenticops.models import Base, ChangeRequest, CloudAccount, CloudResource, FixExecution, FixPlan, PipelineEvent, get_session

ALICE = Actor("user", "alice", 1, ("read", "write"))
BOB = Actor("user", "bob", 2, ("read", "write"))


def _seen(cr_id):
    """The content hash of the change's implementation plan, as the approver is shown it (spec §3.D.1)."""
    from agenticops.services.plan_content import current_hash
    s = get_session()
    try:
        plan = (s.query(FixPlan).filter_by(change_request_id=cr_id, plan_kind="change")
                .order_by(FixPlan.id.desc()).first())
        return current_hash(s, plan)
    finally:
        s.close()


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
        assert plan["plan_kind"] == "change", plan["plan_kind"]

        def save():
            return save_execution_result(fix_plan_id=fix_plan_id, health_issue_id=None, status=status,
                                         step_results=json.dumps([{"step_index": 0, "command": plan["steps"][0]["command"], "status": "ok"}]),
                                         post_check_results=json.dumps(post_results))
        out = save()
        return save() if out.startswith("INVALID:") else out  # the executor resubmits once, as the INVALID asks
    return fake_executor


def _run_executor_for(cr_id):
    """A stand-in for the poller's claim (_check_for_pending), not the poller: the change's newest ticket must still
    be pending, goes running with started_at stamped, and the real _run_executor runs it."""
    from agenticops.services.executor_service import ExecutorService
    s = get_session()
    ex = s.query(FixExecution).join(FixPlan).filter(FixPlan.change_request_id == cr_id).order_by(FixExecution.id.desc()).first()
    assert ex.status == "pending", ex.status
    ex_id, plan_id = ex.id, ex.fix_plan_id
    ex.status, ex.started_at = "running", datetime.now(timezone.utc); s.commit(); s.close()
    ExecutorService()._run_executor(ex_id, plan_id)


def _plan_and_tickets(db, cr_id):
    db.expire_all()
    plan = db.query(FixPlan).filter_by(change_request_id=cr_id, plan_kind="change").one()
    return plan, db.query(FixExecution).filter_by(fix_plan_id=plan.id).all()


def _audits(db, cr_id):
    from agenticops.audit.models import AuditLog
    return db.query(AuditLog).filter_by(entity_type="change_request", entity_id=str(cr_id)).order_by(AuditLog.id).all()


def _events(db, cr_id, event_type):
    """(status, detail) of each of the change's `event_type` events, oldest first."""
    rows = db.query(PipelineEvent).filter_by(change_request_id=cr_id, event_type=event_type).order_by(PipelineEvent.id)
    return [(e.status, json.loads(e.detail) if e.detail else None) for e in rows]


@pytest.fixture
def quiet():
    with patch("agenticops.services.change_service.notify_change_requested") as requested, \
         patch("agenticops.services.change_service.notify_change_pending_approval") as pending_approval, \
         patch("agenticops.services.change_service.notify_change_result") as result:
        yield SimpleNamespace(requested=requested, pending_approval=pending_approval, result=result)


def test_main_path_request_review_approve_execute_complete(db, quiet):
    from agenticops.config import settings
    from agenticops.services import change_service as cs
    cr = cs.create_change_request(source="chat", actor=ALICE, title="Tag web", description="add Env=prod to i-0abc",
                                  account_name="dev", targets=["i-0abc"], start_review=False)
    with patch("agenticops.agents.sre_agent.sre_agent_review_change", side_effect=fake_sre_review):
        out = cs.start_review(cr["id"], sync=True)
    c = cs.get_change(cr["id"])
    assert c["status"] == "planned" and c["risk_level"] == "L1" and c["effective_change_type"] == "standard", out
    assert c["review_verdict"] == "approved_for_planning", out
    cs.approve(cr["id"], actor=BOB, reason="reviewed", content_hash=_seen(cr["id"]))
    with patch.object(settings, "executor_enabled", True):
        cs.request_execution(cr["id"], actor=BOB)
    with patch("agenticops.agents.executor_agent.executor_agent", side_effect=make_fake_executor([{"check_id": "pc-1", "check": "tag present", "status": "pass"}])):
        _run_executor_for(cr["id"])
    # 9b/9c contract: the queued ticket is closed IN PLACE (no second row), and the plan reaches `executed`
    plan, tickets = _plan_and_tickets(db, cr["id"])
    assert len(tickets) == 1 and tickets[0].status == "succeeded", [t.error_message for t in tickets]
    assert tickets[0].started_at is not None and tickets[0].executed_by == BOB.key  # the claim's, kept by the close
    assert plan.status == "executed"
    final = cs.get_change(cr["id"])
    assert final["status"] == "completed" and final["closed_at"]
    audits = _audits(db, cr["id"])
    actions = [a.action for a in audits]
    for expected in ("change.requested", "change.reviewed", "change.approved", "change.execution_started", "change.completed"):
        assert expected in actions
    reviewed = [a for a in audits if a.action == "change.reviewed"]
    assert [a.details.get("phase") for a in reviewed] == ["started", None]  # the review's start, then its verdict
    assert reviewed[1].details["verdict"] == "approved_for_planning" and reviewed[1].new_values == {"status": "planned"}
    events = [e.event_type for e in db.query(PipelineEvent).filter_by(change_request_id=cr["id"])]
    assert "policy_decision" in events and "execution_completed" in events


def test_auto_approve_branch(db, quiet):
    from agenticops.config import settings
    from agenticops.services import change_service as cs
    cr = cs.create_change_request(source="web", actor=ALICE, title="Tag", description="d", account_name="dev", targets=["i-0abc"], start_review=False)
    with patch.object(settings, "change_auto_approve_standard", True), patch.object(settings, "executor_enabled", True), \
         patch("agenticops.agents.sre_agent.sre_agent_review_change", side_effect=fake_sre_review):
        out = cs.start_review(cr["id"], sync=True)
    c = cs.get_change(cr["id"])
    assert c["status"] == "executing" and c["approved_by"] == "agent:auto-pipeline" and "change-standard-low-risk" in c["approval_reason"], out
    [ticket] = db.query(FixExecution).all()
    assert ticket.status == "pending" and ticket.executed_by == "agent:auto-pipeline"  # queued for the poller
    assert [a.actor for a in _audits(db, cr["id"]) if a.action == "change.approved"] == ["agent:auto-pipeline"]


def test_needs_review_when_post_checks_missing(db, quiet):
    from agenticops.config import settings
    from agenticops.services import change_service as cs
    cr = cs.create_change_request(source="web", actor=ALICE, title="Tag", description="d", account_name="dev", targets=["i-0abc"], start_review=False)
    with patch("agenticops.agents.sre_agent.sre_agent_review_change", side_effect=fake_sre_review):
        out = cs.start_review(cr["id"], sync=True)
    assert cs.get_change(cr["id"])["status"] == "planned", out
    cs.approve(cr["id"], actor=BOB, reason="ok", content_hash=_seen(cr["id"]))
    with patch.object(settings, "executor_enabled", True):
        cs.request_execution(cr["id"], actor=BOB)
    with patch("agenticops.agents.executor_agent.executor_agent", side_effect=make_fake_executor([])):
        _run_executor_for(cr["id"])
    plan, tickets = _plan_and_tickets(db, cr["id"])
    assert [t.status for t in tickets] == ["succeeded"] and plan.status == "executed", [t.error_message for t in tickets]
    assert cs.get_change(cr["id"])["status"] == "needs_review"
    out = cs.resolve_review(cr["id"], actor=BOB, outcome="completed", reason="verified in console")
    assert out["status"] == "completed"
    assert [a.action for a in _audits(db, cr["id"])][-2:] == ["change.needs_review", "change.completed"]


@pytest.mark.parametrize("status", ["failed", "rolled_back"])
def test_failed_and_rolled_back_executions_close_the_change(db, quiet, status):
    from agenticops.config import settings
    from agenticops.services import change_service as cs
    cr = cs.create_change_request(source="web", actor=ALICE, title="Tag", description="d", account_name="dev", targets=["i-0abc"], start_review=False)
    with patch("agenticops.agents.sre_agent.sre_agent_review_change", side_effect=fake_sre_review):
        out = cs.start_review(cr["id"], sync=True)
    assert cs.get_change(cr["id"])["status"] == "planned", out
    cs.approve(cr["id"], actor=BOB, reason="ok", content_hash=_seen(cr["id"]))
    with patch.object(settings, "executor_enabled", True):
        cs.request_execution(cr["id"], actor=BOB)
    with patch("agenticops.agents.executor_agent.executor_agent", side_effect=make_fake_executor([], status=status)):
        _run_executor_for(cr["id"])
    plan, tickets = _plan_and_tickets(db, cr["id"])
    # save_execution_result maps both outcomes to a `failed` plan; the ticket and the change keep the outcome
    assert [t.status for t in tickets] == [status] and plan.status == "failed", [t.error_message for t in tickets]
    c = cs.get_change(cr["id"])
    assert c["status"] == status and c["closed_at"]
    last = _audits(db, cr["id"])[-1]
    assert last.action == f"change.{status}" and last.details["execution_status"] == status
    quiet.result.assert_called_once()
    snap, outcome = quiet.result.call_args.args
    assert outcome == status and snap["status"] == status


def test_needs_clarification_then_clarify(db, quiet):
    from agenticops.services import change_service as cs
    cr = cs.create_change_request(source="web", actor=ALICE, title="Tag", description="tag the web box", account_name="dev",
                                  targets=["web-box-typo"], start_review=False)
    with patch("agenticops.agents.sre_agent.sre_agent_review_change", side_effect=fake_sre_review):
        out = cs.start_review(cr["id"], sync=True)
    c = cs.get_change(cr["id"])
    assert c["status"] == "needs_clarification" and c["review_verdict"] == "needs_clarification", out
    assert c["review_reasons"] == ["unresolved: web-box-typo"], out
    with cs._session() as s:  # the fake SRE grounds from target_hints only: this is its reading of the answer below
        row = s.get(ChangeRequest, cr["id"]); row.target_hints = ["i-0abc"]
    real_start_review, rereview = cs.start_review, []

    def _rereview_inline(cr_id, *, sync):
        rereview.append(real_start_review(cr_id, sync=True))  # the real review, in this thread instead of a daemon

    with patch("agenticops.agents.sre_agent.sre_agent_review_change", side_effect=fake_sre_review), \
         patch.object(cs, "start_review", side_effect=_rereview_inline) as sr:
        out = cs.clarify(cr["id"], actor=ALICE, message="I meant i-0abc")
    sr.assert_called_once_with(cr["id"], sync=False)
    assert out["status"] == "planned" and out["review_verdict"] == "approved_for_planning", rereview
    assert out["review_attempt"] == 2, rereview
    assert out["description"].startswith("tag the web box\n\n--- Clarification (")
    assert out["description"].endswith(f", {ALICE.key}) ---\nI meant i-0abc")
    assert [a.details for a in _audits(db, cr["id"]) if a.action == "change.clarified"] == [{"message": "I meant i-0abc"}]
    assert _events(db, cr["id"], "change_clarified") == [("completed", {"message": "I meant i-0abc"})]


def test_policy_block_rejects(db, quiet):
    from agenticops.services import change_service as cs
    from agenticops.services.policy_engine import PolicyDecision
    cr = cs.create_change_request(source="web", actor=ALICE, title="Tag", description="d", account_name="dev", targets=["i-0abc"], start_review=False)
    block = PolicyDecision(action="block", rule_name="freeze-window-block", reasons=["freeze"])
    with patch("agenticops.agents.sre_agent.sre_agent_review_change", side_effect=fake_sre_review), \
         patch("agenticops.services.policy_engine.get_policy_engine", return_value=SimpleNamespace(evaluate=lambda **_: block)):
        out = cs.start_review(cr["id"], sync=True)
    c = cs.get_change(cr["id"])
    assert c["status"] == "rejected" and c["policy_rule"] == "freeze-window-block" and c["policy_action"] == "block", out
    assert c["rejected_by"] == "policy-engine", out
    plan, _ = _plan_and_tickets(db, cr["id"])
    assert plan.status == "rejected" and plan.rejected_by == "policy-engine"
    last = _audits(db, cr["id"])[-1]
    assert last.action == "change.rejected" and last.details["policy_decision"]["action"] == "block"
    # the real evaluate_policy ran twice: the SRE's evaluate_change_policy, then submit_review's own re-evaluation
    assert [status for status, _ in _events(db, cr["id"], "policy_decision")] == ["block", "block"]


def test_review_without_a_verdict_rolls_back_to_draft_and_a_restart_arms_the_watchdog(db, quiet):
    """sync=True arms no watchdog: this rollback is the worker's own no-verdict path (the timeout path is unit-tested
    in test_change_service.py). The restart is the async start, whose threads are mocks that never run."""
    from agenticops.config import settings
    from agenticops.services import change_service as cs
    cr = cs.create_change_request(source="web", actor=ALICE, title="Tag", description="d", account_name="dev", targets=["i-0abc"], start_review=False)
    with patch("agenticops.agents.sre_agent.sre_agent_review_change", return_value="…"):
        out = cs.start_review(cr["id"], sync=True)  # returned without a verdict → rolled back to draft
    reason = "review ended without a verdict (submit_change_review was not called)"
    c = cs.get_change(cr["id"])
    assert c["status"] == "draft" and c["review_reasons"] == [reason] and c["review_attempt"] == 1, out
    assert [a.details for a in _audits(db, cr["id"]) if a.action == "change.reviewed"] == [
        {"phase": "started", "attempt": 1}, {"phase": "failed", "attempt": 1, "error": reason}]
    assert _events(db, cr["id"], "review_failed") == [("failed", {"error": reason, "attempt": 1})]
    quiet.result.assert_called_once()
    snap, outcome = quiet.result.call_args.args
    assert outcome == "review_failed" and snap["id"] == cr["id"] and snap["status"] == "draft"
    with patch.object(cs, "threading") as th:
        out = cs.restart_review(cr["id"], actor=ALICE)  # the human retry from the UI
    assert out["status"] == "under_review" and out["review_attempt"] == 2
    worker, watchdog = th.Thread.call_args_list
    assert worker.kwargs["target"] is cs._run_review and worker.kwargs["args"] == (cr["id"], c["trace_id"], 2)
    assert watchdog.kwargs["target"] is cs._watchdog_join
    assert watchdog.kwargs["args"] == (cr["id"], 2, th.Thread.return_value, settings.change_review_timeout_seconds)
    th.Thread.return_value.start.assert_called_once_with()  # the watchdog's; it starts its worker itself
