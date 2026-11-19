"""MVP-2.9.0 N26 — the execution path, tightened in four places, and one widening (the owner's rulings, 2026-11-18).

① An aborted run that tried nothing does not dispute the diagnosis it was planned from (the plan still ends).
② A «read» that writes a file on the host AgenticOps runs on is not read-only.
③ An approved plan cannot run once its issue is resolved or dismissed — at the opening of a run's record and at
   queueing, as it already could not be approved.
④ A diagnosis or a plan run a PERSON asked for takes a word only from that person or an administrator.
And CloudFormation's `describe-` / `list-` are reads (`get-` is not: `get-template` returns the whole template).
"""
import gc
import json
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from agenticops.agents.run_guard import RunGuard, applied_of, guard_decision
from agenticops.auth.actor import Actor
from agenticops.models import (AgentStep, Base, CloudAccount, FixExecution, FixPlan, HealthIssue, PipelineEvent,
                               RCAResult, get_session)
from agenticops.run_context import RunContext, reset_run_context, set_run_context
from agenticops.services import agent_runs
from agenticops.services import change_steps
from agenticops.services.plan_content import stamp_approval
from agenticops.services.run_tickets import open_ticket
from agenticops.skills.security import classify_kubectl_command
from agenticops.tools.aws_cli_tool import _classify_command

ALICE = Actor("user", "alice", 1, ("read", "write"))
BOB = Actor("user", "bob", 2, ("read", "write"))
ADMIN = Actor("user", "root", 3, ("read", "write", "admin"))
STEP = "aws ec2 create-tags --resources sg-1 --tags Key=reviewed,Value=yes"


@pytest.fixture
def db(tmp_path, monkeypatch):
    import agenticops.models as models_mod
    import agenticops.audit.models  # noqa: F401
    import agenticops.galaxy.models  # noqa: F401
    import agenticops.scheduler.scheduler  # noqa: F401
    from agenticops.config import settings
    monkeypatch.setattr(models_mod, "_engine", None)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/n26.db")
    monkeypatch.setattr(settings, "executor_enabled", True)
    monkeypatch.setattr(settings, "rbac_enforce", False)
    monkeypatch.setattr(settings, "api_auth_enabled", False)
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


def _plan(db, issue_status="fix_approved"):
    """An approved fix plan of an issue → (issue_id, plan_id, rca_id)."""
    issue = HealthIssue(title="t", description="d", severity="low", source="test", status=issue_status, resource_id="r")
    db.add(issue); db.flush()
    rca = RCAResult(health_issue_id=issue.id, root_cause="x", confidence=0.9)
    db.add(rca); db.flush()
    plan = FixPlan(health_issue_id=issue.id, rca_result_id=rca.id, risk_level="L1", title="p", summary="s",
                   status="approved", approved_by="user:alice", steps=[{"action": "tag", "command": STEP}])
    db.add(plan); db.flush()
    stamp_approval(db, plan); db.commit()
    return issue.id, plan.id, rca.id


def _run(db):
    """… with its run record open → (issue_id, plan_id, rca_id, execution_id)."""
    issue_id, plan_id, rca_id = _plan(db)
    ticket, why = open_ticket(plan_id, executed_by="agent:auto-pipeline")
    assert ticket, why
    return issue_id, plan_id, rca_id, ticket


@contextmanager
def _in_run(plan_id, ticket):
    token = set_run_context(RunContext(actor="agent:auto-pipeline", agent_name="executor", fix_plan_id=plan_id,
                                       execution_id=ticket))
    try:
        yield
    finally:
        reset_run_context(token)


def _disputes(db, issue_id) -> int:
    db.expire_all()
    return db.query(PipelineEvent).filter_by(health_issue_id=issue_id, event_type="rca_disputed").count()


# ── ① an aborted run that tried nothing says nothing about the diagnosis ────────────────────────────────────

def _save(plan_id, ticket, status, steps=(), error="pre-check failed: the instance is not running"):
    from agenticops.tools.metadata_tools import save_execution_result
    with _in_run(plan_id, ticket):
        return save_execution_result(fix_plan_id=plan_id, status=status, step_results=json.dumps(list(steps)),
                                     error_message=error)


def test_the_guard_of_a_run_says_how_many_commands_that_could_change_something_it_let_through():
    assert applied_of(None) is None and applied_of(4711) is None          # no guard watched such a run here
    guard = RunGuard(4711)
    assert applied_of(4711) == 0
    guard.applied = 2
    assert applied_of(4711) == 2
    del guard
    gc.collect()
    assert applied_of(4711) is None                                        # the run is over: nothing is kept of it


def test_an_aborted_run_that_let_nothing_through_does_not_dispute_the_diagnosis(db):
    """A pre-check failed before any step: the plan was never tried, so its failure says nothing about the cause.
    Since 2.2.0 every failed run disputed its RCA — this one too."""
    issue_id, plan_id, rca_id, ticket = _run(db)
    guard = RunGuard(ticket)                                               # the run's own guard: it let nothing through
    _save(plan_id, ticket, "aborted")
    db.expire_all()
    row = db.get(FixExecution, ticket)
    assert (row.status, row.verification_status) == ("aborted", "failed")
    assert db.get(FixPlan, plan_id).status == "failed"                     # the plan still ends …
    assert db.get(HealthIssue, issue_id).status == "root_cause_identified" # … and the issue waits for a new one
    assert _disputes(db, issue_id) == 0 and db.get(RCAResult, rca_id).critic_verdict is None
    assert guard.applied == 0


def test_an_aborted_run_that_had_changed_something_still_disputes_it(db):
    issue_id, plan_id, rca_id, ticket = _run(db)
    guard = RunGuard(ticket)
    guard.applied = guard.tried = 1                                        # a command that could change something ran
    _save(plan_id, ticket, "aborted", error="step 2 could not start")
    assert _disputes(db, issue_id) == 1
    assert db.get(RCAResult, rca_id).critic_verdict == "disputed_by_execution"


def test_what_the_guard_counted_decides_not_what_the_agent_reports(db):
    """The agent says «aborted, no steps» — but the guard let a write through: something was tried."""
    issue_id, plan_id, _rca, ticket = _run(db)
    guard = RunGuard(ticket)
    guard.applied = guard.tried = 1
    _save(plan_id, ticket, "aborted", steps=())
    assert _disputes(db, issue_id) == 1
    # … and the other way round: step results are reported, the guard let nothing through that could change anything
    issue_2, plan_2, _rca2, ticket_2 = _run(db)
    guard_2 = RunGuard(ticket_2)
    _save(plan_2, ticket_2, "aborted", steps=({"step_index": 1, "status": "skipped"},))
    assert _disputes(db, issue_2) == 0 and guard_2.applied == 0


def test_without_a_guard_the_runs_own_step_results_decide(db):
    """A run no guard watched in this process: an aborted run that reports no step tried nothing."""
    issue_id, plan_id, _rca, ticket = _run(db)
    _save(plan_id, ticket, "aborted", steps=())
    assert _disputes(db, issue_id) == 0
    issue_2, plan_2, _rca2, ticket_2 = _run(db)
    _save(plan_2, ticket_2, "aborted", steps=({"step_index": 1, "status": "failed"},))
    assert _disputes(db, issue_2) == 1


@pytest.mark.parametrize("status", ["failed", "rolled_back"])
def test_a_run_that_failed_disputes_the_diagnosis_whatever_was_counted(db, status):
    """Only «aborted» is excused: a run that reports a failure tried the plan."""
    issue_id, plan_id, _rca, ticket = _run(db)
    guard = RunGuard(ticket)
    _save(plan_id, ticket, status, error="step 1 failed")
    assert _disputes(db, issue_id) == 1 and guard.applied == 0


# ── ② a «read» that writes a file on the AgenticOps host is not read-only ───────────────────────────────────

@pytest.mark.parametrize("command", [
    "aws s3api get-object --bucket b --key k /tmp/out.bin",
    "aws s3api get-object --bucket b --key k --range bytes=0-9 out",
    "aws s3api get-object-torrent --bucket b --key k out.torrent",
    "aws apigateway get-export --rest-api-id a1 --stage-name prod --export-type swagger /tmp/api.json",
    "aws apigateway get-sdk --rest-api-id a1 --stage-name prod --sdk-type javascript sdk.zip",
    "AWS S3API GET-OBJECT --bucket b --key k out",
])
def test_an_aws_read_that_saves_a_file_is_a_write(command):
    assert _classify_command(command) == "write"
    assert change_steps.command_tier(command.lower() if command.isupper() else command) != "readonly"


@pytest.mark.parametrize("command", [
    "aws --region us-east-1 s3api get-object --bucket b --key k out",       # a global option before the service
    "aws s3api --endpoint-url https://x get-object --bucket b --key k out",
])
def test_however_it_is_written_it_is_never_read_only(command):
    assert _classify_command(command) != "readonly"


@pytest.mark.parametrize("command", [
    "aws s3api get-object-acl --bucket b --key k",                           # these only answer: they stay reads
    "aws s3api get-object-tagging --bucket b --key k",
    "aws s3api get-object-attributes --bucket b --key k --object-attributes ETag",
    "aws s3api get-bucket-policy --bucket b",
    "aws s3api head-object --bucket b --key k",
    "aws s3api list-objects-v2 --bucket b",
    "aws apigateway get-rest-apis",
    "aws apigateway get-stages --rest-api-id a1",
    "aws apigateway get-export-something --rest-api-id a1",                  # another operation that merely begins alike
])
def test_the_reads_beside_them_stay_reads(command):
    assert _classify_command(command) == "readonly"


@pytest.mark.parametrize("command, tier", [
    ("cluster-info dump --output-directory=/tmp/dump", "write"),
    ("cluster-info dump --output-directory /tmp/dump", "write"),
    ("kubectl cluster-info dump --namespaces kube-system --output-directory=/tmp/dump", "write"),
    ("cluster-info dump --all-namespaces --OUTPUT-DIRECTORY=/tmp/dump", "write"),
    ("cluster-info dump", "readonly"),                                       # to the answer, not to a file
    ("cluster-info dump --namespaces kube-system", "readonly"),
    ("cluster-info", "readonly"),
    ("get pods --output-directory=/tmp/x", "readonly"),                      # not this command's option: kubectl refuses it
])
def test_a_cluster_dump_into_a_directory_is_a_write(command, tier):
    assert classify_kubectl_command(command) == tier


def test_a_plan_step_that_saves_a_file_waits_for_a_person_and_is_refused_after_a_stop():
    for command in ("aws s3api get-object --bucket b --key k /tmp/out.bin",
                    "kubectl cluster-info dump --output-directory=/tmp/dump"):
        assert change_steps.command_tier(command) == "write"
    stopped = {"status": "running", "fix_plan_id": 1, "stopped_by": "user:alice", "rollback": frozenset()}
    assert guard_decision(stopped, "run_aws_cli", {"command": "aws s3api get-object --bucket b --key k /tmp/out.bin"}, applied=1)
    assert guard_decision(stopped, "run_kubectl", {"command": "cluster-info dump --output-directory=/tmp/dump"}, applied=1)
    assert guard_decision(stopped, "run_aws_cli", {"command": "aws s3api get-object-acl --bucket b --key k"}, applied=1) is None


def test_the_read_only_tool_refuses_it_without_running_anything():
    from agenticops.tools import aws_cli_tool
    with patch.object(aws_cli_tool, "_execute_aws_cli") as ran:
        out = aws_cli_tool.run_aws_cli_readonly(command="aws s3api get-object --bucket b --key k /tmp/out.bin")
    ran.assert_not_called()
    assert out.lower().startswith("error")


# ── CloudFormation's describe- / list- are reads; get- is not ───────────────────────────────────────────────

@pytest.mark.parametrize("command, tier", [
    ("aws cloudformation describe-stacks --stack-name web", "readonly"),
    ("aws cloudformation describe-stack-events --stack-name web", "readonly"),
    ("aws cloudformation describe-stack-resources --stack-name web", "readonly"),
    ("aws cloudformation list-stacks", "readonly"),
    ("aws cloudformation list-stack-resources --stack-name web", "readonly"),
    ("aws cloudformation get-template --stack-name web", "unknown"),         # the whole template: a person looks
    ("aws cloudformation get-template-summary --stack-name web", "unknown"),
    ("aws cloudformation detect-stack-drift --stack-name web", "unknown"),   # starts an operation
    ("aws cloudformation create-stack --stack-name web --template-body file://t.yaml", "write"),
    ("aws cloudformation update-stack --stack-name web", "write"),
    ("aws cloudformation delete-stack --stack-name web", "write"),
])
def test_cloudformation_reads(command, tier):
    assert _classify_command(command) == tier


# ── ③ a closed issue's approved plan cannot run ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("status", ["resolved", "dismissed"])
def test_a_runs_record_is_not_opened_for_a_closed_issue(db, status):
    issue_id, plan_id, _rca = _plan(db, issue_status=status)
    ticket, why = open_ticket(plan_id, executed_by="agent:auto-pipeline")
    assert ticket is None
    # N27 (review): the sentence no longer offers reopening as the way to run the plan — a reopened issue starts
    # again from its diagnosis (tests/test_review_fixes_n27.py)
    assert why.startswith(f"HealthIssue #{issue_id} is '{status}': its approved plan is not run")
    db.expire_all()
    assert db.get(FixPlan, plan_id).status == "approved"                   # nothing moved, nothing was written
    assert db.get(HealthIssue, issue_id).status == status
    assert db.query(FixExecution).count() == 0


def test_an_open_issues_plan_runs_as_before(db):
    issue_id, plan_id, _rca = _plan(db)
    ticket, why = open_ticket(plan_id, executed_by="agent:auto-pipeline")
    assert ticket and why == ""
    db.expire_all()
    assert db.get(FixPlan, plan_id).status == "executing" and db.get(HealthIssue, issue_id).status == "fix_executing"


@pytest.mark.parametrize("status", ["resolved", "dismissed"])
def test_the_run_route_refuses_a_closed_issues_plan(db, status):
    from fastapi.testclient import TestClient
    from agenticops.web import deps
    from agenticops.web.app import app
    issue_id, plan_id, _rca = _plan(db, issue_status=status)
    app.dependency_overrides[deps.current_actor] = lambda: ADMIN
    try:
        r = TestClient(app).post(f"/api/fix-plans/{plan_id}/execute", json={})
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 409, r.text
    assert r.json()["detail"].startswith(f"HealthIssue #{issue_id} is '{status}': its approved plan is not run")
    db.expire_all()
    assert db.get(FixPlan, plan_id).status == "approved" and db.query(FixExecution).count() == 0


def test_the_page_is_told_the_run_is_not_on_offer(db):
    from agenticops.services import ui_actions
    _issue, plan_id, _rca = _plan(db, issue_status="resolved")
    plan = db.get(FixPlan, plan_id)
    closed = {a["action"]: a for a in ui_actions.plan_actions(plan, ADMIN, issue_status="resolved", run_in_flight=False)}
    assert (closed["execute"]["allowed"], closed["execute"]["reason_code"]) == (False, "issue_closed")
    live = {a["action"]: a for a in ui_actions.plan_actions(plan, ADMIN, issue_status="fix_approved", run_in_flight=False)}
    assert live["execute"]["allowed"] is True


def test_the_closed_issue_is_said_before_a_run_in_flight(db):
    from agenticops.services import ui_actions
    _issue, plan_id, _rca = _plan(db, issue_status="dismissed")
    acts = {a["action"]: a for a in ui_actions.plan_actions(db.get(FixPlan, plan_id), ADMIN, issue_status="dismissed", run_in_flight=True)}
    assert acts["execute"]["reason_code"] == "issue_closed"


def test_approving_still_says_approving(db):
    from agenticops.services.issue_state import closed_issue_refusal
    issue_id, _plan_id, _rca = _plan(db, issue_status="resolved")
    assert closed_issue_refusal(db, issue_id) == f"HealthIssue #{issue_id} is 'resolved'; reopen it before approving its plan"
    assert closed_issue_refusal(db, None) is None


# ── ④ a run a person asked for takes a word only from that person or an administrator ───────────────────────

@pytest.fixture
def claims():
    from agenticops.agents.step_recorder import clear_live
    agent_runs.clear()
    clear_live()
    yield agent_runs
    agent_runs.clear()
    clear_live()


def test_who_may_say_a_word_to_a_run(claims):
    asked = claims.begin("rca", 7, "user:alice")
    assert claims.may_note(asked, ALICE) is True                           # the person who asked
    assert claims.may_note(asked, BOB) is False                            # another person with the write flag
    assert claims.may_note(asked, ADMIN) is True                           # an administrator
    claims.end(asked)
    by_pipeline = claims.take("sre", 7, claims.PIPELINE)
    assert claims.may_note(by_pipeline, BOB) is True                       # nobody's own run: as before
    assert claims.may_note(None, BOB) is True                              # no claim on record: as before
    claims.end(by_pipeline)
    from_im = claims.begin("rca", 8, "im:feishu:ou_1")                     # asked through the IM bot: a person's run too
    assert claims.may_note(from_im, BOB) is False and claims.may_note(from_im, ADMIN) is True


def _client(actor):
    from fastapi.testclient import TestClient
    from agenticops.web import deps
    from agenticops.web.app import app
    from agenticops.web.routers import ui as ui_router
    app.dependency_overrides[deps.current_actor] = lambda: actor
    app.dependency_overrides[ui_router.signed_in_user] = lambda: SimpleNamespace(id=actor.user_id)
    return TestClient(app)


def _notes(db):
    db.expire_all()
    return db.query(AgentStep).filter_by(kind="you").order_by(AgentStep.id).all()


def test_the_route_takes_a_word_only_from_the_person_who_asked_or_an_administrator(db, claims):
    from agenticops.agents.step_recorder import StepRecorder
    from agenticops.web.app import app
    run = claims.begin("rca", 7, "user:alice")                             # asked for from a page, or a (private) chat
    recorder = StepRecorder("rca", "I7")
    try:
        r = _client(BOB).post("/api/ui/activity/note", json={"lane": "I7:diagnosis", "text": "try the other region"})
        assert r.status_code == 403 and r.json()["detail"]["code"] == "not_your_run", r.text
        assert _notes(db) == []                                            # nothing was recorded, nothing reaches the agent
        assert _client(ALICE).post("/api/ui/activity/note", json={"lane": "I7:diagnosis", "text": "mine"}).status_code == 201
        assert _client(ADMIN).post("/api/ui/activity/note", json={"lane": "I7:diagnosis", "text": "an admin's"}).status_code == 201
        assert [n.summary for n in _notes(db)] == ["mine", "an admin's"]
    finally:
        app.dependency_overrides.clear()
        recorder.close()
        claims.end(run)


def test_a_run_the_pipeline_started_takes_a_word_from_anyone_who_may_write_notes(db, claims):
    from agenticops.agents.step_recorder import StepRecorder
    from agenticops.web.app import app
    run = claims.take("sre", 7, claims.PIPELINE)
    recorder = StepRecorder("sre", "I7")
    try:
        assert _client(BOB).post("/api/ui/activity/note", json={"lane": "I7:plan", "text": "keep it small"}).status_code == 201
    finally:
        app.dependency_overrides.clear()
        recorder.close()
        claims.end(run)


def test_the_live_list_says_whether_this_person_may(db, claims):
    from agenticops.services.activity import activity
    issue = HealthIssue(title="t", description="d", severity="low", source="test", status="investigating", resource_id="r")
    db.add(issue); db.commit()
    run = claims.begin("rca", issue.id, "user:alice")
    lane = lambda actor: next(l for l in activity(actor)["running"] if l["id"] == f"I{issue.id}:diagnosis")   # noqa: E731
    assert lane(ALICE)["notes_from_you"] is True
    assert lane(BOB)["notes_from_you"] is False
    assert lane(ADMIN)["notes_from_you"] is True
    claims.end(run)
    auto = claims.take("rca", issue.id, claims.PIPELINE)
    assert lane(BOB)["notes_from_you"] is True
    claims.end(auto)


# ── the plan agent is told to write every step as one exact command ─────────────────────────────────────────

def test_the_plan_agent_is_told_to_write_every_step_as_one_exact_command():
    """N26 (the owner's ruling): of 166 plans on a copy of the database, 5 had a rollback that could run entirely as
    written — «stop and roll back» can only run rollback lines that are commands. The fix-plan protocol says so, in
    both builds that carry it; the rule names no cloud and no cloud's tool."""
    from agenticops.agents.sre_agent import SRE_BASE_PROMPT, SRE_SYSTEM_PROMPT
    for prompt in (SRE_SYSTEM_PROMPT, SRE_BASE_PROMPT):
        text = " ".join(prompt.split())                       # the prompt wraps lines; the rule is what is pinned
        assert text.count("EXACT COMMANDS:") == 1
        rule = text[text.index("EXACT COMMANDS:"):text.index("7. SAVE:")]
        assert "every step" in rule and "every rollback step" in rule
        assert "ONE command line, written exactly as it will be run" in rule
        assert "no placeholder" in rule and "no two commands joined" in rule and "no comment" in rule
        assert "pre-check" in rule and "post-check" in rule
        assert "is not a step" in rule                         # what cannot be one command is said, not planned
        for word in ("aws", "kubectl", "azure", "gcloud", "aliyun", "ec2", " s3", "eks"):
            assert word not in rule.lower(), word
