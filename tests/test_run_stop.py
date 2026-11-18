"""A person stops a run in progress, and it is rolled back by the plan's own rollback steps (MVP-2.9.0 N9).

Stopping is a request written on the run's record — the record stays `running`, or the agent could neither roll
back nor record what it did. From then on the run's guard lets through only read-only commands, the tools that
record a result, and commands that are, word for word, steps of this plan's rollback; everything else is refused
with a message that tells the agent to roll back and record. That is code, not the model's goodwill.
"""
import json
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from strands import Agent, tool
from strands.tools.executors import SequentialToolExecutor

from agenticops.agents.run_guard import RunGuard, guard_decision
from agenticops.models import (Base, CloudAccount, FixExecution, FixPlan, HealthIssue, PipelineEvent, RCAResult,
                               get_session)
from agenticops.run_context import RunContext, reset_run_context, set_run_context
from agenticops.services.plan_content import stamp_approval
from agenticops.services.run_tickets import close_ticket, open_ticket, request_stop, ticket_state
from tests.test_run_guard import Scripted

STEP_1 = "aws ec2 revoke-security-group-ingress --group-id sg-1 --protocol tcp --port 22 --cidr 0.0.0.0/0"
STEP_2 = "aws ec2 create-tags --resources sg-1 --tags Key=reviewed,Value=yes"
ROLLBACK = "aws ec2 authorize-security-group-ingress --group-id sg-1 --protocol tcp --port 22 --cidr 0.0.0.0/0"
CHECK = "aws ec2 describe-security-groups --group-ids sg-1"


@pytest.fixture
def db(tmp_path, monkeypatch):
    import agenticops.models as models_mod
    import agenticops.audit.models  # noqa: F401
    from agenticops.config import settings
    monkeypatch.setattr(models_mod, "_engine", None)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/stop.db")
    monkeypatch.setattr(settings, "executor_enabled", True)
    monkeypatch.setattr(settings, "rbac_enforce", False)
    Base.metadata.create_all(models_mod.get_engine())
    s = get_session()
    s.add(CloudAccount(name="dev", provider="aws", is_enabled=True, credentials={}, regions=["ap-southeast-1"]))
    s.commit()
    yield s
    s.close()


@pytest.fixture(autouse=True)
def _no_side_effects():
    with patch("agenticops.services.notification_service.notify_execution_result"), \
         patch("agenticops.services.notification_service.notify_im_origin"), \
         patch("agenticops.services.resolution_service.trigger_post_resolution"):
        yield


def _run(db, rollback=None):
    """An approved fix plan with its run record open → (issue_id, plan_id, execution_id)."""
    issue = HealthIssue(title="t", description="d", severity="low", source="test", status="fix_approved", resource_id="r")
    db.add(issue); db.flush()
    rca = RCAResult(health_issue_id=issue.id, root_cause="x", confidence=0.9)
    db.add(rca); db.flush()
    plan = FixPlan(health_issue_id=issue.id, rca_result_id=rca.id, risk_level="L1", title="p", summary="s",
                   status="approved", approved_by="user:alice",
                   steps=[{"action": "close ssh", "command": STEP_1}, {"action": "tag", "command": STEP_2}],
                   rollback_plan={"steps": [{"action": "reopen ssh", "command": ROLLBACK}]} if rollback is None else rollback)
    db.add(plan); db.flush()
    stamp_approval(db, plan); db.commit()
    issue_id, plan_id = issue.id, plan.id
    ticket, why = open_ticket(plan_id, executed_by="agent:auto-pipeline")
    assert ticket, why
    return issue_id, plan_id, ticket


# ── the request ──────────────────────────────────────────────────────────────

def test_a_stop_is_written_on_the_running_record_once(db):
    issue_id, plan_id, ticket = _run(db)
    assert request_stop(ticket, by="user:alice", note="wrong window") is True
    db.expire_all()
    row = db.get(FixExecution, ticket)
    assert row.status == "running"                                  # not closed: the agent must still roll back and record
    assert row.stop_requested_by == "user:alice" and row.stop_note == "wrong window" and row.stop_requested_at is not None
    assert request_stop(ticket, by="user:bob", note="me too") is False      # the first request stands
    db.expire_all()
    assert db.get(FixExecution, ticket).stop_requested_by == "user:alice"


def test_a_record_that_is_not_running_cannot_be_stopped(db):
    issue_id, plan_id, ticket = _run(db)
    close_ticket(ticket, "failed", "timed out")
    assert request_stop(ticket, by="user:alice", note="") is False
    assert request_stop(9999, by="user:alice", note="") is False


def test_the_state_of_a_stopped_run_names_who_stopped_it_and_what_may_still_run(db):
    issue_id, plan_id, ticket = _run(db)
    assert ticket_state(ticket) == {"status": "running", "fix_plan_id": plan_id, "stopped_by": None, "rollback": frozenset()}
    request_stop(ticket, by="user:alice", note="")
    state = ticket_state(ticket)
    assert state["stopped_by"] == "user:alice" and state["rollback"] == frozenset({ROLLBACK})


# ── what the guard lets through after a stop ─────────────────────────────────

STOPPED = {"status": "running", "fix_plan_id": 1, "stopped_by": "user:alice", "rollback": frozenset({ROLLBACK})}


def test_before_a_stop_everything_runs():
    running = {"status": "running", "fix_plan_id": 1, "stopped_by": None, "rollback": frozenset()}
    assert guard_decision(running, "run_aws_cli", {"command": STEP_2}) is None
    assert guard_decision(running, "activate_skill", {"name": "aws-compute"}) is None


@pytest.mark.parametrize("tool_name,tool_input", [
    ("run_aws_cli", {"command": ROLLBACK}),                                   # the plan's own rollback step, word for word
    ("run_aws_cli_dev", {"command": "  " + ROLLBACK.replace(" --", "   --") + " "}),   # … whatever the spacing, whichever CLI tool
    ("run_aws_cli", {"command": CHECK}),                                      # a read: the agent may look
    ("run_kubectl", {"command": "kubectl get pods -n web"}),
    ("save_execution_result", {"fix_plan_id": 1, "status": "rolled_back"}),   # … and must be able to record
    ("mark_fix_failed", {"execution_id": 3}),
    ("get_approved_fix_plan", {"fix_plan_id": 1}),
    ("describe_security_groups", {"group_ids": "sg-1"}),
])
def test_after_a_stop_rollback_reads_and_recording_still_run(tool_name, tool_input):
    assert guard_decision(STOPPED, tool_name, tool_input) is None


@pytest.mark.parametrize("tool_name,tool_input", [
    ("run_aws_cli", {"command": STEP_2}),                                     # the next step of the plan
    ("run_aws_cli", {"command": ROLLBACK + " --dry-run"}),                    # nearly the rollback is not the rollback
    ("run_aws_cli", {"command": f"{CHECK} && {STEP_2}"}),                     # a read with a write behind it
    ("run_on_host", {"instance_id": "i-1", "command": "systemctl restart nginx"}),
    ("run_kubectl", {"command": "kubectl delete pod web-1"}),
    ("activate_skill", {"name": "aws-compute"}),                              # no command to judge: not on the list
    ("assume_role", {"role_arn": "arn:aws:iam::1:role/x"}),
    ("run_skill_script", {"skill_name": "s", "script": "fix.sh"}),
])
def test_after_a_stop_nothing_else_runs(tool_name, tool_input):
    refusal = guard_decision(STOPPED, tool_name, tool_input)
    assert refusal and "user:alice" in refusal and "roll" in refusal.lower() and "save_execution_result" in refusal


def test_a_closed_record_still_refuses_everything():
    closed = {"status": "aborted", "fix_plan_id": 1, "stopped_by": "user:alice", "rollback": frozenset({ROLLBACK})}
    assert "closed" in guard_decision(closed, "run_aws_cli", {"command": ROLLBACK})
    assert "closed" in guard_decision(closed, "save_execution_result", {})


# ── a real agent, stopped in the middle ──────────────────────────────────────

def test_a_run_stopped_during_its_first_step_does_not_take_the_second_and_can_only_roll_back(db):
    issue_id, plan_id, ticket = _run(db)
    ran, refused = [], []

    @tool
    def run_aws_cli(command: str) -> str:
        """Run a command."""
        ran.append(command)
        if command == STEP_1:
            assert request_stop(ticket, by="user:alice", note="wrong change window")
        return "ok"

    cmd = lambda *cs: [("run_aws_cli", {"command": c}) for c in cs]
    model = Scripted([cmd(STEP_1, STEP_2),            # the model wrote both steps in one turn
                      cmd("aws ec2 delete-security-group --group-id sg-1"),     # … then tries something of its own
                      cmd(CHECK, ROLLBACK),           # … then does what the refusal told it
                      "rolled back"])
    agent = Agent(model=model, tools=[run_aws_cli], hooks=[RunGuard(ticket)], callback_handler=None,
                  tool_executor=SequentialToolExecutor())
    agent("go")
    assert ran == [STEP_1, CHECK, ROLLBACK]           # step 2 and the improvised delete never ran
    assert model.calls == 4                           # the loop went on: the agent must be able to record


# ── the result of a stopped run ──────────────────────────────────────────────

@contextmanager
def _in_run(plan_id, ticket):
    token = set_run_context(RunContext(actor="agent:auto-pipeline", agent_name="executor", fix_plan_id=plan_id,
                                       execution_id=ticket))
    try:
        yield
    finally:
        reset_run_context(token)


def test_a_stopped_run_that_rolled_back_gives_the_issue_back_without_disputing_its_diagnosis(db):
    from agenticops.tools.metadata_tools import save_execution_result
    issue_id, plan_id, ticket = _run(db)
    request_stop(ticket, by="user:alice", note="wrong change window")
    with _in_run(plan_id, ticket):
        out = save_execution_result(fix_plan_id=plan_id, status="rolled_back",
                                    rollback_results=json.dumps([{"command": ROLLBACK, "status": "success"}]))
    assert f"FixExecution #{ticket}" in out
    db.expire_all()
    row = db.get(FixExecution, ticket)
    assert row.status == "rolled_back" and row.verification_status == "failed"
    assert "stopped by user:alice" in row.verification_reason
    assert db.get(FixPlan, plan_id).status == "failed" and db.get(HealthIssue, issue_id).status == "root_cause_identified"
    assert db.query(RCAResult).filter_by(health_issue_id=issue_id).one().human_verdict is None
    assert db.query(PipelineEvent).filter_by(health_issue_id=issue_id, event_type="rca_disputed").count() == 0


def test_a_run_that_failed_by_itself_still_disputes_its_diagnosis(db):
    from agenticops.tools.metadata_tools import save_execution_result
    issue_id, plan_id, ticket = _run(db)
    with _in_run(plan_id, ticket):
        save_execution_result(fix_plan_id=plan_id, status="failed", error_message="step 1 failed")
    db.expire_all()
    assert db.query(PipelineEvent).filter_by(health_issue_id=issue_id, event_type="rca_disputed").count() == 1


def test_a_stopped_run_that_ends_without_recording_says_no_rollback_is_on_record(db):
    from agenticops.agents.executor_agent import executor_agent
    issue = HealthIssue(title="t", description="d", severity="low", source="test", status="fix_approved", resource_id="r")
    db.add(issue); db.flush()
    rca = RCAResult(health_issue_id=issue.id, root_cause="x", confidence=0.9)
    db.add(rca); db.flush()
    plan = FixPlan(health_issue_id=issue.id, rca_result_id=rca.id, risk_level="L1", title="p", summary="s",
                   status="approved", approved_by="user:alice", steps=[{"action": "a", "command": STEP_1}])
    db.add(plan); db.flush(); stamp_approval(db, plan); db.commit()
    issue_id, plan_id = issue.id, plan.id

    def model_gives_up():
        ticket = get_session().query(FixExecution.id).filter_by(fix_plan_id=plan_id).scalar()
        assert request_stop(ticket, by="user:alice", note="")
        return "I was stopped and could not roll back."
    ea = "agenticops.agents.executor_agent"
    token = set_run_context(RunContext(actor="agent:auto-pipeline", agent_name="executor", fix_plan_id=plan_id))
    try:
        with patch(f"{ea}.Agent"), patch(f"{ea}.BedrockModel"), \
             patch(f"{ea}.build_system_prompt", side_effect=lambda p, **kw: p), \
             patch(f"{ea}.get_cli_tool_for_issue", return_value=None), \
             patch("agenticops.config.get_bedrock_boto_session", return_value=MagicMock()), \
             patch("agenticops.agents.preamble.invoke_with_retry", side_effect=lambda agent, prompt, **kw: model_gives_up()), \
             patch("agenticops.services.agent_log_service.track_agent"):
            executor_agent(fix_plan_id=plan_id)
    finally:
        reset_run_context(token)
    db.expire_all()
    row = db.query(FixExecution).one()
    assert row.status == "failed" and "stopped by user:alice" in row.error_message.lower()
    assert "no rollback is on record" in row.error_message
    assert db.get(HealthIssue, issue_id).status == "root_cause_identified"


# ── the route ────────────────────────────────────────────────────────────────

@pytest.fixture
def client(db):
    from fastapi.testclient import TestClient
    from agenticops.web.app import app
    return TestClient(app)


def test_the_route_writes_the_stop_and_says_so_on_the_timeline(db, client):
    from agenticops.audit.models import AuditLog
    issue_id, plan_id, ticket = _run(db)
    r = client.post(f"/api/fix-executions/{ticket}/stop", json={"reason": "wrong change window"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "running" and body["stop_requested_by"] and body["stop_note"] == "wrong change window"
    db.expire_all()
    [event] = db.query(PipelineEvent).filter_by(health_issue_id=issue_id, event_type="execution_stop_requested").all()
    assert json.loads(event.detail)["execution_id"] == ticket
    assert db.query(AuditLog).filter_by(action="plan.execution_stop_requested").count() == 1
    again = client.post(f"/api/fix-executions/{ticket}/stop", json={})
    assert again.status_code == 409 and again.json()["detail"]["code"] == "already_stopping"


def test_the_route_refuses_a_run_that_is_not_in_progress(db, client):
    issue_id, plan_id, ticket = _run(db)
    close_ticket(ticket, "failed", "timed out")
    r = client.post(f"/api/fix-executions/{ticket}/stop", json={})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "not_running"
    assert client.post("/api/fix-executions/9999/stop", json={}).status_code == 404


def test_the_run_as_the_api_shows_it_carries_the_stop(db, client):
    issue_id, plan_id, ticket = _run(db)
    request_stop(ticket, by="user:alice", note="n")
    [row] = client.get(f"/api/fix-executions?fix_plan_id={plan_id}").json()
    assert row["stop_requested_by"] == "user:alice" and row["stop_note"] == "n" and row["stop_requested_at"]


# ── what a stop could roll back, as the plan is written ──────────────────────

@pytest.mark.parametrize("rollback, want", [
    ({"steps": [{"action": "reopen", "command": ROLLBACK}]}, {"steps": 1, "commands": 1, "as_written": 1}),
    ({"description": "restore the rule by hand"}, {"steps": 0, "commands": 0, "as_written": 0}),          # prose: nothing to run
    (None, {"steps": 0, "commands": 0, "as_written": 0}),
    ({"steps": [{"action": "talk to the owner"}, {"command": ROLLBACK}]}, {"steps": 2, "commands": 1, "as_written": 1}),
    # a line that chains commands, or carries a placeholder, cannot be run exactly as it is written
    ({"steps": [{"command": f"{ROLLBACK} && {STEP_2}"}, {"command": "aws ec2 deregister-image --image-id <AMI_ID>"},
                {"command": ROLLBACK}]}, {"steps": 3, "commands": 3, "as_written": 1}),
    ('{"steps": [{"command": "aws ec2 start-instances --instance-ids i-1"}]}', {"steps": 1, "commands": 1, "as_written": 1}),   # a legacy JSON string
    # A sentence is not a command even when a shell would not split it, and neither is a label before a command.
    # Measured on the copy database (N14): 80 of the 116 lines the first rule called «runnable as written» were one
    # of these — the page promised a rollback for ~50 plans whose rollback is sentences.
    ({"steps": ["Start instance and verify status checks",
                "Re-enable key: aws iam update-access-key --user-name app --access-key-id AKIAEXAMPLE --status Active",
                {"command": "Restore the previous security group rules"}, {"command": ROLLBACK}, "systemctl restart nginx"]},
     {"steps": 5, "commands": 5, "as_written": 2}),
    # … and a command the tools refuse outright cannot run, however it is written
    ({"steps": [{"command": "kubectl delete namespace kube-system"}, {"command": ROLLBACK}]}, {"steps": 2, "commands": 2, "as_written": 1}),
    # a placeholder inside a quoted argument is still a placeholder (a shell would not split the line, and the
    # command would run — with «<OWNER_APPROVED_IP>» as its value); a comparison in a --query is not one
    ({"steps": [{"command": "aws ec2 authorize-security-group-ingress --group-id sg-1 --ip-permissions 'IpProtocol=tcp,FromPort=22,ToPort=22,IpRanges=[{CidrIp=<OWNER_APPROVED_IP>/32}]'"},
                {"command": "aws ec2 describe-volumes --query 'Volumes[?Size < `100` && Iops > `3000`].VolumeId' --output text"},
                {"command": 'aws ec2 create-tags --resources sg-1 --tags "Key=owner,Value=<team-name>"'}]},
     {"steps": 3, "commands": 3, "as_written": 1}),
])
def test_how_much_of_a_rollback_can_run_exactly_as_written(rollback, want):
    from agenticops.services.change_steps import rollback_outlook
    assert rollback_outlook(rollback) == want


def test_the_guard_passes_the_plans_own_rollback_text_and_the_outlook_says_how_much_of_it_a_tool_can_run(db):
    """Two different questions: the guard lets the plan's own text through whatever it looks like; the page says, before
    a stop, how many of those lines are one command a tool can run as it stands."""
    from agenticops.services.change_steps import rollback_commands, rollback_outlook
    chained, placeholder = f"{ROLLBACK} && {STEP_2}", "aws ec2 deregister-image --image-id <AMI_ID>"
    rollback = {"steps": [{"command": chained}, {"command": placeholder}, {"command": ROLLBACK}]}
    issue_id, plan_id, ticket = _run(db, rollback=rollback)
    request_stop(ticket, by="user:alice")
    state = ticket_state(ticket)
    passed = [c for c in rollback_commands(rollback) if guard_decision(state, "run_aws_cli", {"command": c}) is None]
    assert len(passed) == 3                                           # each is the plan's own text: the guard lets it through
    assert rollback_outlook(rollback)["as_written"] == 1              # … but only one of them is a command a tool can run as it is


def test_the_plan_as_the_api_shows_it_says_what_a_stop_could_roll_back(db, client):
    issue_id, plan_id, ticket = _run(db)
    body = client.get(f"/api/fix-plans/{plan_id}").json()
    assert body["rollback_outlook"] == {"steps": 1, "commands": 1, "as_written": 1}
    refused = client.put(f"/api/fix-plans/{plan_id}", json={"content_hash": body["content_hash"], "rollback_outlook": {"as_written": 9}})
    assert refused.status_code in (409, 422)                          # computed on the way out: a client cannot write it
