"""Every run of the executor has one record while it works (MVP-2.9.0 N8).

Three things start the executor: a queued ticket (POST /execute, the CLI, every change), the thread an approval
starts, and Main calling it in a chat turn. Until N8 only the first had a fix_executions row while it worked — so
only that one could be seen, cancelled, timed out or reconciled. Now executor_agent opens the record itself when
its run has none: the plan and the issue move to «executing» as they do for a queued run, the result closes that
same row in place, and a run that ends without a result is closed as failed and gives the issue back.
"""
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from agenticops.models import (Base, CloudAccount, FixExecution, FixPlan, HealthIssue, PipelineEvent, RCAResult,
                               get_session)
from agenticops.run_context import RunContext, reset_run_context, set_run_context
from agenticops.services.plan_content import stamp_approval


@pytest.fixture
def db(tmp_path, monkeypatch):
    import agenticops.models as models_mod
    import agenticops.audit.models  # noqa: F401
    from agenticops.config import settings
    monkeypatch.setattr(models_mod, "_engine", None)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/tickets.db")
    monkeypatch.setattr(settings, "executor_enabled", True)
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


def _plan(db, *, plan_status="approved", issue_status="fix_approved"):
    """An issue, its diagnosis and a fix plan → (issue_id, plan_id)."""
    issue = HealthIssue(title="t", description="d", severity="low", source="test", status=issue_status, resource_id="r")
    db.add(issue); db.flush()
    rca = RCAResult(health_issue_id=issue.id, root_cause="x", confidence=0.9)
    db.add(rca); db.flush()
    plan = FixPlan(health_issue_id=issue.id, rca_result_id=rca.id, risk_level="L1", title="p", summary="s",
                   status=plan_status, approved_by="user:alice",
                   steps=[{"action": "look", "command": "aws sts get-caller-identity"}])
    db.add(plan); db.flush()
    if plan_status in ("approved", "executing"):
        stamp_approval(db, plan)
    db.commit()
    return issue.id, plan.id


def _state(db, issue_id, plan_id):
    db.expire_all()
    return (db.get(FixPlan, plan_id).status, db.get(HealthIssue, issue_id).status,
            [(r.status, r.executed_by) for r in db.query(FixExecution).order_by(FixExecution.id)])


def _events(db, issue_id, kind):
    db.expire_all()
    return [(e.status, e.detail) for e in db.query(PipelineEvent).filter_by(health_issue_id=issue_id, event_type=kind)]


@contextmanager
def _as(actor, **fields):
    token = set_run_context(RunContext(actor=actor, agent_name="executor", **fields))
    try:
        yield
    finally:
        reset_run_context(token)


@contextmanager
def _executor(model_does):
    """executor_agent's real body without Bedrock: `model_does()` stands for what the model would do in the run."""
    ea = "agenticops.agents.executor_agent"
    with patch(f"{ea}.Agent") as agent_cls, patch(f"{ea}.BedrockModel"), \
         patch(f"{ea}.build_system_prompt", side_effect=lambda p, **kw: p), \
         patch(f"{ea}.get_cli_tool_for_issue", return_value=None), \
         patch("agenticops.config.get_bedrock_boto_session", return_value=MagicMock()), \
         patch("agenticops.agents.preamble.invoke_with_retry", side_effect=lambda agent, prompt, **kw: model_does()), \
         patch("agenticops.services.agent_log_service.track_agent"):
        yield agent_cls


def _records(plan_id, status="succeeded"):
    """What a run that follows its protocol does: read the approved plan, then record its result."""
    from agenticops.tools.metadata_tools import get_approved_fix_plan, save_execution_result
    seen = {}

    def model_does():
        seen["gate"] = get_approved_fix_plan(plan_id)
        seen["saved"] = save_execution_result(fix_plan_id=plan_id, status=status)
        return "recorded"
    return model_does, seen


# ── opening the record ───────────────────────────────────────────────────────

def test_a_run_without_a_record_gets_one_and_the_plan_and_issue_read_executing(db):
    from agenticops.services.run_tickets import open_ticket
    issue_id, plan_id = _plan(db)
    ticket, why = open_ticket(plan_id, executed_by="agent:auto-pipeline")
    assert ticket and why == ""
    assert _state(db, issue_id, plan_id) == ("executing", "fix_executing", [("running", "agent:auto-pipeline")])
    row = db.get(FixExecution, ticket)
    assert row.started_at is not None and row.health_issue_id == issue_id and row.completed_at is None


@pytest.mark.parametrize("plan_status", ["draft", "pending_approval", "rejected", "executed", "failed"])
def test_a_plan_that_is_not_approved_gets_no_record(db, plan_status):
    from agenticops.services.run_tickets import open_ticket
    issue_id, plan_id = _plan(db, plan_status=plan_status, issue_status="fix_planned")
    ticket, why = open_ticket(plan_id, executed_by="user:alice")
    assert ticket is None and plan_status in why
    assert _state(db, issue_id, plan_id) == (plan_status, "fix_planned", [])


def test_a_plan_that_is_already_running_gets_no_second_record(db):
    from agenticops.services.run_tickets import open_ticket
    issue_id, plan_id = _plan(db)
    first, _ = open_ticket(plan_id, executed_by="agent:auto-pipeline")
    second, why = open_ticket(plan_id, executed_by="user:bob")
    assert second is None and f"Execution #{first}" in why
    assert len(_state(db, issue_id, plan_id)[2]) == 1


def test_an_unknown_plan_gets_no_record(db):
    from agenticops.services.run_tickets import open_ticket
    assert open_ticket(999, executed_by="user:alice") == (None, "FixPlan #999 not found")


# ── closing it ───────────────────────────────────────────────────────────────

def test_closing_a_fix_runs_record_gives_the_issue_back_and_says_so_on_the_timeline(db):
    """Until N8 a cancelled or timed-out fix run left its issue at fix_executing, on nobody's list, with no event."""
    from agenticops.services.run_tickets import close_ticket, open_ticket
    issue_id, plan_id = _plan(db)
    ticket, _ = open_ticket(plan_id, executed_by="agent:auto-pipeline")
    assert close_ticket(ticket, "aborted", "Cancelled by operator") is True
    assert _state(db, issue_id, plan_id) == ("failed", "root_cause_identified", [("aborted", "agent:auto-pipeline")])
    [(status, detail)] = _events(db, issue_id, "execution_completed")
    assert status == "failed" and f'"execution_id": {ticket}' in detail and "Cancelled by operator" in detail
    assert close_ticket(ticket, "failed", "again") is False            # the first closer wins; nothing more is written
    assert len(_events(db, issue_id, "execution_completed")) == 1


def test_closing_a_record_leaves_an_issue_that_moved_on_where_it_is(db):
    from agenticops.services.run_tickets import close_ticket, open_ticket
    issue_id, plan_id = _plan(db)
    ticket, _ = open_ticket(plan_id, executed_by="agent:auto-pipeline")
    db.query(HealthIssue).filter_by(id=issue_id).update({"status": "dismissed"}); db.commit()
    assert close_ticket(ticket, "failed", "timed out") is True
    assert _state(db, issue_id, plan_id)[:2] == ("failed", "dismissed")


# ── the executor opens and closes its own ────────────────────────────────────

def test_a_run_the_approval_started_has_a_record_and_its_result_closes_that_same_row(db):
    from agenticops.agents.executor_agent import executor_agent
    issue_id, plan_id = _plan(db)
    during = {}
    model_does, seen = _records(plan_id)

    def watched():
        during["state"] = _state(get_session(), issue_id, plan_id)
        return model_does()
    with _executor(watched), _as("agent:auto-pipeline", fix_plan_id=plan_id):
        executor_agent(fix_plan_id=plan_id)
    assert during["state"] == ("executing", "fix_executing", [("running", "agent:auto-pipeline")])
    plan_status, issue_status, rows = _state(db, issue_id, plan_id)
    assert plan_status == "executed" and rows == [("succeeded", "agent:auto-pipeline")]      # one row, closed in place
    assert issue_status == "fix_executed"                       # no declared check: a person accepts it
    assert "FixExecution #" in seen["saved"]


def test_a_run_dispatched_from_chat_has_a_record_too(db):
    from agenticops.agents.executor_agent import executor_agent
    issue_id, plan_id = _plan(db)
    model_does, _ = _records(plan_id)
    with _executor(model_does), _as("user:alice"):                # a chat turn: no plan in its Run Context
        executor_agent(fix_plan_id=plan_id)
    assert _state(db, issue_id, plan_id)[2] == [("succeeded", "user:alice")]


def test_a_run_that_ends_without_a_result_is_closed_and_the_issue_comes_back(db):
    """It used to read «executing» for executor_total_timeout (30 min) with nothing to end it."""
    from agenticops.agents.executor_agent import executor_agent
    issue_id, plan_id = _plan(db)
    with _executor(lambda: "I could not run this plan."), _as("agent:auto-pipeline", fix_plan_id=plan_id):
        executor_agent(fix_plan_id=plan_id)
    plan_status, issue_status, rows = _state(db, issue_id, plan_id)
    assert (plan_status, issue_status, rows) == ("failed", "root_cause_identified", [("failed", "agent:auto-pipeline")])
    assert "without recording a result" in db.query(FixExecution).one().error_message
    assert [s for s, _ in _events(db, issue_id, "execution_completed")] == ["failed"]


def test_a_queued_run_keeps_its_own_record_and_opens_no_second_one(db):
    from agenticops.agents.executor_agent import executor_agent
    from agenticops.services.run_tickets import open_ticket
    issue_id, plan_id = _plan(db)
    ticket, _ = open_ticket(plan_id, executed_by="user:alice")     # what POST /execute + the claim leave
    model_does, _ = _records(plan_id)
    with _executor(model_does), _as("agent:executor", fix_plan_id=plan_id, execution_id=ticket):
        executor_agent(fix_plan_id=plan_id)
    assert _state(db, issue_id, plan_id)[2] == [("succeeded", "user:alice")]


def test_a_plan_that_is_not_approved_is_refused_before_any_model_is_built(db):
    """A withdraw that raced the thread start used to be caught only if the model asked for the plan first."""
    from agenticops.agents.executor_agent import executor_agent
    issue_id, plan_id = _plan(db, plan_status="rejected", issue_status="root_cause_identified")
    with _executor(lambda: "never") as agent_cls, _as("agent:auto-pipeline", fix_plan_id=plan_id):
        answer = executor_agent(fix_plan_id=plan_id)
    assert answer.startswith("REJECTED") and "rejected" in answer
    agent_cls.assert_not_called()
    assert _state(db, issue_id, plan_id)[2] == []


def test_a_second_executor_on_a_running_plan_is_refused(db):
    from agenticops.agents.executor_agent import executor_agent
    from agenticops.services.run_tickets import open_ticket
    issue_id, plan_id = _plan(db)
    ticket, _ = open_ticket(plan_id, executed_by="agent:auto-pipeline")
    with _executor(lambda: "never") as agent_cls, _as("user:bob"):
        answer = executor_agent(fix_plan_id=plan_id)
    assert answer.startswith("REJECTED") and f"Execution #{ticket}" in answer
    agent_cls.assert_not_called()
    assert _state(db, issue_id, plan_id)[2] == [("running", "agent:auto-pipeline")]


def test_the_executor_is_built_to_run_one_command_at_a_time_under_its_runs_guard(db):
    from strands.tools.executors import SequentialToolExecutor
    from agenticops.agents.executor_agent import executor_agent
    from agenticops.agents.run_guard import RunGuard
    issue_id, plan_id = _plan(db)
    model_does, _ = _records(plan_id)
    with _executor(model_does) as agent_cls, _as("agent:auto-pipeline", fix_plan_id=plan_id):
        executor_agent(fix_plan_id=plan_id)
    kwargs = agent_cls.call_args.kwargs
    assert isinstance(kwargs["tool_executor"], SequentialToolExecutor)
    [guard] = [h for h in kwargs["hooks"] if isinstance(h, RunGuard)]
    assert guard.execution_id == db.query(FixExecution).one().id


def test_a_run_the_approval_started_is_timed_out_like_a_queued_one(db, monkeypatch):
    from agenticops.agents.executor_agent import executor_agent
    from agenticops.config import settings
    from agenticops.tools.metadata_tools import save_execution_result
    monkeypatch.setattr(settings, "executor_total_timeout", 0.05)
    issue_id, plan_id = _plan(db)
    late = {}

    def slow():
        time.sleep(0.4)
        late["saved"] = save_execution_result(fix_plan_id=plan_id, status="succeeded")
        return "recorded, too late"
    with _executor(slow), _as("agent:auto-pipeline", fix_plan_id=plan_id):
        executor_agent(fix_plan_id=plan_id)
    plan_status, issue_status, rows = _state(db, issue_id, plan_id)
    assert rows == [("failed", "agent:auto-pipeline")] and "timed out" in db.query(FixExecution).one().error_message
    assert (plan_status, issue_status) == ("failed", "root_cause_identified")
    assert "not executable" in late["saved"]                     # the first closer won: the late result is refused


# ── the routes around a run ──────────────────────────────────────────────────

@pytest.fixture
def client(db):
    from fastapi.testclient import TestClient
    from agenticops.web.app import app
    return TestClient(app)


def test_a_plan_cannot_be_deleted_while_it_runs(db, client):
    """DELETE had no state check: the plan of a run in progress could be removed under the executor."""
    from agenticops.services.run_tickets import open_ticket
    issue_id, plan_id = _plan(db)
    open_ticket(plan_id, executed_by="agent:auto-pipeline")
    r = client.delete(f"/api/fix-plans/{plan_id}")
    assert r.status_code == 409 and "in progress" in r.json()["detail"]
    db.expire_all()
    assert db.get(FixPlan, plan_id) is not None


def test_a_plan_that_has_run_is_kept_with_its_runs(db, client):
    """It answered 500: the run rows point at the plan."""
    from agenticops.services.run_tickets import close_ticket, open_ticket
    issue_id, plan_id = _plan(db)
    ticket, _ = open_ticket(plan_id, executed_by="agent:auto-pipeline")
    close_ticket(ticket, "failed", "timed out")
    r = client.delete(f"/api/fix-plans/{plan_id}")
    assert r.status_code == 409 and "has run" in r.json()["detail"]
    db.expire_all()
    assert db.get(FixPlan, plan_id) is not None and db.query(FixExecution).count() == 1


def test_a_plan_that_is_not_running_can_still_be_deleted(db, client):
    issue_id, plan_id = _plan(db, plan_status="draft", issue_status="fix_planned")
    assert client.delete(f"/api/fix-plans/{plan_id}").status_code == 204
    db.expire_all()
    assert db.get(FixPlan, plan_id) is None


def test_switching_the_executor_on_starts_its_queue(db, client, monkeypatch):
    """PATCH /api/settings only set the flag: tickets queued afterwards waited until the next restart."""
    from agenticops.config import settings
    from agenticops.web import app as app_mod
    monkeypatch.setattr(settings, "executor_enabled", False)
    with patch.object(app_mod._executor_service, "start") as start:
        assert client.patch("/api/settings", json={"executor_enabled": True}).status_code == 200
        start.assert_called_once()
        assert client.patch("/api/settings", json={"executor_enabled": False}).status_code == 200
        start.assert_called_once()                                 # switching it off starts nothing
    monkeypatch.setattr(settings, "executor_enabled", True)


# ── round-2 review ───────────────────────────────────────────────────────────────────────────────────

def test_a_cancelled_run_names_who_cancelled_it_on_the_timeline(db, client):
    """A-M7: the status move and the run's end were written as agent:executor «Cancelled by operator»; who it was
    stood only in the audit log."""
    from agenticops.services.run_tickets import open_ticket
    issue_id, plan_id = _plan(db)
    ticket, _ = open_ticket(plan_id, executed_by="agent:auto-pipeline")
    r = client.post(f"/api/fix-executions/{ticket}/cancel")
    assert r.status_code == 200, r.text
    who = "web:anonymous"                                        # auth is off in this fixture: the session's actor
    db.expire_all()
    ended = db.query(PipelineEvent).filter_by(health_issue_id=issue_id, event_type="execution_completed").one()
    moved = db.query(PipelineEvent).filter_by(health_issue_id=issue_id, event_type="status_changed").order_by(PipelineEvent.id.desc()).first()
    assert ended.actor == who and moved.actor == who
    assert f"Cancelled by {who}" in db.get(FixExecution, ticket).error_message


def test_the_cancel_route_does_not_run_on_the_event_loop():
    """It closes the record, fails the plan, moves the issue and writes the timeline: blocking writes (A-M7)."""
    import inspect
    from agenticops.web import app as app_mod
    assert not inspect.iscoroutinefunction(app_mod.api_cancel_execution)


# A-I3. The timer that times a run out, and the reconcile that closes one that recorded nothing, live in the process
# that runs it. After a restart nothing ever closed the record: the issue stayed «executing», in nobody's queue,
# no new run and no new plan could start. Since N8 every fix run has such a record, so every restart during a run
# left one.

def _running_since(db, minutes):
    from datetime import datetime, timedelta, timezone
    from agenticops.services.run_tickets import open_ticket
    issue_id, plan_id = _plan(db)
    ticket, _ = open_ticket(plan_id, executed_by="agent:auto-pipeline")
    db.query(FixExecution).filter_by(id=ticket).update({"started_at": datetime.now(timezone.utc) - timedelta(minutes=minutes)})
    db.commit()
    return issue_id, plan_id, ticket


def test_a_run_whose_process_is_gone_is_closed_at_startup(db, monkeypatch):
    from agenticops.config import settings
    from agenticops.services.run_tickets import close_orphans
    monkeypatch.setattr(settings, "executor_total_timeout", 1800)
    old_issue, old_plan, old = _running_since(db, 120)
    young_issue, young_plan, young = _running_since(db, 1)
    closed, timers = close_orphans()
    try:
        assert closed == [old]
        db.expire_all()
        row = db.get(FixExecution, old)
        assert row.status == "failed" and "process that ran it ended" in row.error_message
        assert _state(db, old_issue, old_plan)[:2] == ("failed", "root_cause_identified")     # back on somebody's list
        assert [s for s, _d in _events(db, old_issue, "execution_completed")] == ["failed"]
        # the young one may still be running in another process (the CLI): it gets the time it has left
        assert db.get(FixExecution, young).status == "running"
        [timer] = timers
        assert 1800 - 60 < timer.interval <= 1800 + 120
    finally:
        for t in timers:
            t.cancel()
    timer.function(*timer.args, **timer.kwargs)                                             # … and is closed when that is up
    db.expire_all()
    assert db.get(FixExecution, young).status == "failed"
    assert _state(db, young_issue, young_plan)[:2] == ("failed", "root_cause_identified")


def test_a_run_that_ended_meanwhile_is_left_as_it_ended(db, monkeypatch):
    from agenticops.config import settings
    from agenticops.services.run_tickets import close_orphans, close_ticket
    monkeypatch.setattr(settings, "executor_total_timeout", 1800)
    issue_id, plan_id, ticket = _running_since(db, 1)
    closed, timers = close_orphans()
    for t in timers:
        t.cancel()
    close_ticket(ticket, "aborted", "Cancelled by user:alice")                              # it ends by itself first
    timers[0].function(*timers[0].args, **timers[0].kwargs)
    db.expire_all()
    assert db.get(FixExecution, ticket).status == "aborted"


def test_without_a_time_limit_nothing_is_closed_at_startup(db, monkeypatch):
    """executor_total_timeout = 0 means a run may take as long as it takes: an old record proves nothing."""
    from agenticops.config import settings
    from agenticops.services.run_tickets import close_orphans
    monkeypatch.setattr(settings, "executor_total_timeout", 0)
    _i, _p, ticket = _running_since(db, 600)
    assert close_orphans() == ([], [])
    db.expire_all()
    assert db.get(FixExecution, ticket).status == "running"


def test_the_service_closes_orphaned_runs_when_it_starts():
    import inspect
    from agenticops.web import app as app_mod
    assert "close_orphans" in inspect.getsource(app_mod.lifespan)
