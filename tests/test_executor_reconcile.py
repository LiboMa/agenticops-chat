"""Executor robustness (MVP-2.6.0 Task 9c): one terminal per queued run; a change never runs on a fallback account.

A queued run closes its own FixExecution ticket in place, so there is one row per queued execution. A run that
returns without recording its result, a cancel and a timeout fail the ticket, its plan and, for a change plan,
the change request. save_execution_result refuses another plan's result and a change plan outside its queued
run. A change plan whose account is bound but cannot be resolved is refused before any model is built.
mark_fix_executed marks an issue only for a succeeded run of that issue's executed plan.
"""
import json
import logging
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from agenticops.models import (Base, ChangeRequest, CloudAccount, FixExecution, FixPlan, HealthIssue, RCAResult,
                               get_session)
from agenticops.run_context import RunContext, reset_run_context, set_run_context
from agenticops.services.executor_service import ExecutorService
from agenticops.services.plan_content import stamp_approval
from agenticops.tools.aws_cli_tool import run_aws_cli, run_aws_cli_readonly  # the executor's fallback tools

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
PASSED = json.dumps([{"check": "c", "status": "pass"}])


@pytest.fixture
def db(tmp_path, monkeypatch):
    import agenticops.models as models_mod
    import agenticops.audit.models  # noqa: F401
    from agenticops.config import settings
    monkeypatch.setattr(models_mod, "_engine", None)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/reconcile.db")
    monkeypatch.setattr(settings, "change_management_enabled", True)
    monkeypatch.setattr(settings, "executor_enabled", True)
    Base.metadata.create_all(models_mod.get_engine())
    s = get_session()
    s.add(CloudAccount(name="dev", provider="aws", is_enabled=True, credentials={}, regions=["ap-southeast-1"]))
    s.commit()
    yield s
    s.close()


@pytest.fixture(autouse=True)
def _no_side_effects():
    """No notification leaves the process, and an auto-resolved issue starts no post-resolution pipeline."""
    with patch("agenticops.services.change_service.notify_change_result"), \
         patch("agenticops.services.notification_service.notify_execution_result"), \
         patch("agenticops.services.notification_service.notify_im_origin"), \
         patch("agenticops.services.resolution_service.trigger_post_resolution"):
        yield


# ── rows (inserted directly: there is no ORM status validator) ───────────────

def _dev_id(db):
    return db.query(CloudAccount).filter_by(name="dev").one().id


def _change_run(db, *, account=True, plan_status="executing", cr_status="executing", ticket_status="running"):
    """A change request, its change plan and the ticket ExecutorService claimed → (cr_id, plan_id, ex_id).
    ticket_status=None inserts no ticket (ex_id None)."""
    cr = ChangeRequest(title="tag web", description="d", requested_by="user:alice", status=cr_status,
                       account_id=_dev_id(db) if account else None)
    db.add(cr); db.flush()
    plan = FixPlan(plan_kind="change", change_request_id=cr.id, risk_level="L1", title="p", summary="s",
                   status=plan_status, approved_by="user:bob", rollback_plan={"steps": ["undo"]},
                   post_checks=[{"check": "c"}])
    db.add(plan); db.flush()
    _as_approved(db, plan)
    ex_id = None
    if ticket_status:
        ex = FixExecution(fix_plan_id=plan.id, status=ticket_status, executed_by="user:bob", started_at=T0)
        db.add(ex); db.flush()
        ex_id = ex.id
    db.commit()
    return cr.id, plan.id, ex_id


def _fix_run(db, plan_status="executing", ticket_status="running", *, account_id=None, post_checks=None):
    """A fix plan and its ticket, the tests/test_run_context_entrypoints.py::_approved_plan shapes →
    (issue_id, plan_id, ex_id). ticket_status=None inserts no ticket (ex_id None)."""
    issue = HealthIssue(title="t", description="d", severity="low", source="test", status="fix_approved",
                        resource_id="r", trace_id="TRC-issue1", account_id=account_id)
    db.add(issue); db.flush()
    rca = RCAResult(health_issue_id=issue.id, root_cause="x", confidence=0.9)
    db.add(rca); db.flush()
    plan = FixPlan(health_issue_id=issue.id, rca_result_id=rca.id, risk_level="L1", title="p", summary="s",
                   status=plan_status, approved_by="user:alice", post_checks=post_checks or [])
    db.add(plan); db.flush()
    _as_approved(db, plan)
    ex_id = None
    if ticket_status:
        ex = FixExecution(fix_plan_id=plan.id, health_issue_id=issue.id, status=ticket_status,
                          executed_by="user:alice", started_at=T0)
        db.add(ex); db.flush()
        ex_id = ex.id
    db.commit()
    return issue.id, plan.id, ex_id


def _as_approved(db, plan):
    """An approved/executing plan carries the hash its approval was for (spec §3.D.1)."""
    if plan.status in ("approved", "executing"):
        stamp_approval(db, plan)


def _audits(db, action):
    from agenticops.audit.models import AuditLog
    db.expire_all()
    return db.query(AuditLog).filter_by(action=action).all()


def _snapshot(db, pid, cr_id=None, ex_id=None):
    """What a refused call must not change: ticket, plan and change-request status, execution and audit rows."""
    from agenticops.audit.models import AuditLog
    db.expire_all()
    return (db.get(FixExecution, ex_id).status if ex_id else None, db.get(FixPlan, pid).status,
            db.get(ChangeRequest, cr_id).status if cr_id else None, db.query(FixExecution).count(),
            db.query(AuditLog).count())


# ── running a queued execution ───────────────────────────────────────────────

@contextmanager
def _in_run(pid, cr_id=None, ex_id=None):
    """The Run Context ExecutorService._run_executor sets for its queued run, set directly."""
    token = set_run_context(RunContext(actor="agent:executor", agent_name="executor", fix_plan_id=pid,
                                       change_request_id=cr_id, execution_id=ex_id))
    try:
        yield
    finally:
        reset_run_context(token)


def _recorder(status, **fields):
    """A fake executor_agent that passes the REAL gate and records its result through the REAL tool.
    It passes the plan's health_issue_id unless fields names another. Returns (fake, seen):
    seen["gate"] / seen["saved"] are the two tools' return values."""
    from agenticops.tools.metadata_tools import get_approved_fix_plan, save_execution_result
    seen = {}

    def fake(fix_plan_id):
        seen["gate"] = get_approved_fix_plan(fix_plan_id)
        plan = json.loads(seen["gate"])
        seen["saved"] = save_execution_result(**{"fix_plan_id": fix_plan_id, "status": status,
                                                 "health_issue_id": plan["health_issue_id"], **fields})
        return "recorded"
    return fake, seen


def _run(ex_id, pid, fake):
    """Drive a queued run through ExecutorService._run_executor (which sets the real Run Context)."""
    svc = ExecutorService()
    svc._active_executions[ex_id] = MagicMock()
    with patch("agenticops.agents.executor_agent.executor_agent", side_effect=fake):
        svc._run_executor(ex_id, pid)
    assert ex_id not in svc._active_executions
    return svc


@contextmanager
def _executor_build():
    """Task 9b's executor-build patches (tests/test_change_plan_fix_path_guard.py): executor_agent builds and
    runs without Bedrock. Yields the Agent, BedrockModel and get_cli_tool_for_issue mocks."""
    ea = "agenticops.agents.executor_agent"
    with patch(f"{ea}.Agent") as agent_cls, patch(f"{ea}.BedrockModel") as model_cls, \
         patch(f"{ea}.build_system_prompt", side_effect=lambda p, **kw: p), \
         patch(f"{ea}.get_cli_tool_for_issue", return_value=None) as cli_tool, \
         patch("agenticops.config.get_bedrock_boto_session", return_value=MagicMock()), \
         patch("agenticops.agents.preamble.invoke_with_retry", return_value="done"), \
         patch("agenticops.services.agent_log_service.track_agent"):
        yield agent_cls, model_cls, cli_tool


# ── (b) one row per queued run ───────────────────────────────────────────────

def test_a_change_run_closes_its_own_ticket_in_place(db):
    cr_id, pid, ex_id = _change_run(db)
    fake, seen = _recorder("succeeded", post_check_results=PASSED, executed_by="executor_agent")
    _run(ex_id, pid, fake)
    db.expire_all()
    rows = db.query(FixExecution).all()
    assert [r.id for r in rows] == [ex_id]
    ex = rows[0]
    assert ex.status == "succeeded" and ex.executed_by == "user:bob"  # the requester, kept
    assert ex.started_at.replace(tzinfo=None) == T0.replace(tzinfo=None)  # the claim, kept
    assert ex.completed_at is not None and ex.post_check_results == [{"check": "c", "status": "pass"}]
    assert db.get(FixPlan, pid).status == "executed" and db.get(ChangeRequest, cr_id).status == "completed"
    assert _audits(db, "change.failed") == []  # the post-run reconcile was a no-op
    assert f"FixExecution #{ex_id}" in seen["saved"]


def test_a_fix_run_closes_its_own_ticket_in_place(db):
    issue_id, pid, ex_id = _fix_run(db)
    fake, seen = _recorder("succeeded")
    _run(ex_id, pid, fake)
    db.expire_all()
    rows = db.query(FixExecution).all()
    assert [r.id for r in rows] == [ex_id]
    assert rows[0].status == "succeeded" and rows[0].health_issue_id == issue_id and rows[0].executed_by == "user:alice"
    assert db.get(FixPlan, pid).status == "executed"


def test_the_plan_not_the_agent_names_the_issue_a_result_resolves(db, caplog):
    from agenticops.models import PipelineEvent
    issue_id, pid, ex_id = _fix_run(db, post_checks=[{"check": "c"}])  # a passing post-check resolves it
    other_id, _, _ = _fix_run(db, plan_status="approved", ticket_status=None)  # another fix_approved issue
    fake, seen = _recorder("succeeded", health_issue_id=other_id, post_check_results=PASSED)  # the wrong issue
    with caplog.at_level(logging.WARNING, logger="agenticops.tools.metadata_tools"), \
         patch("agenticops.services.resolution_service.trigger_post_resolution") as post, \
         patch("agenticops.services.notification_service.notify_execution_result") as notify, \
         patch("agenticops.services.notification_service.notify_im_origin") as im_origin:
        _run(ex_id, pid, fake)
    db.expire_all()
    ex = db.get(FixExecution, ex_id)
    assert ex.status == "succeeded" and ex.health_issue_id == issue_id  # the issue the ticket was claimed with
    assert db.get(HealthIssue, issue_id).status == "resolved"
    assert db.get(HealthIssue, other_id).status == "fix_approved"  # untouched
    post.assert_called_once_with(issue_id)
    assert notify.call_args.args[1] == issue_id and im_origin.call_args.args[0] == issue_id
    events = db.query(PipelineEvent).filter_by(event_type="execution_completed").all()
    assert [e.health_issue_id for e in events] == [issue_id]
    assert f"HealthIssue #{issue_id} auto-resolved" in seen["saved"]
    assert any(r.levelno == logging.WARNING and f"health_issue_id={other_id}" in r.getMessage()
               for r in caplog.records)


def test_without_a_run_context_a_new_row_is_inserted(db):
    """Chat / auto-pipeline runs have no ticket: unchanged behaviour."""
    from agenticops.tools.metadata_tools import save_execution_result
    issue_id, pid, _ = _fix_run(db, plan_status="approved", ticket_status=None)
    assert db.query(FixExecution).count() == 0
    out = save_execution_result(fix_plan_id=pid, health_issue_id=issue_id, status="succeeded")
    db.expire_all()
    rows = db.query(FixExecution).all()
    assert len(rows) == 1 and rows[0].executed_by == "executor_agent" and f"FixExecution #{rows[0].id}" in out
    assert db.get(FixPlan, pid).status == "executed"


def test_the_run_contexts_ticket_is_updated_in_place(db):
    from agenticops.tools.metadata_tools import save_execution_result
    cr_id, pid, ex_id = _change_run(db)
    with _in_run(pid, cr_id, ex_id):
        out = save_execution_result(fix_plan_id=pid, status="succeeded", post_check_results=PASSED)
    db.expire_all()
    assert [r.id for r in db.query(FixExecution).all()] == [ex_id]
    assert db.get(FixExecution, ex_id).status == "succeeded" and f"FixExecution #{ex_id}" in out
    assert db.get(ChangeRequest, cr_id).status == "completed"


# ── (b2), (b3) refusals ──────────────────────────────────────────────────────

def test_a_run_cannot_record_another_plans_result(db):
    from agenticops.tools.metadata_tools import save_execution_result
    cr_a, a, ex_a = _change_run(db)
    issue_b, b, ex_b = _fix_run(db)  # an executing fix plan: nothing else would stop this write
    before = (_snapshot(db, a, cr_a, ex_a), _snapshot(db, b, None, ex_b))
    with _in_run(a, cr_a, ex_a):
        out = save_execution_result(fix_plan_id=b, health_issue_id=issue_b, status="succeeded")
    assert out == f"REJECTED: this run executes FixPlan #{a} — it cannot record a result for FixPlan #{b}."
    assert (_snapshot(db, a, cr_a, ex_a), _snapshot(db, b, None, ex_b)) == before


def test_a_change_plan_outside_its_run_cannot_record(db):
    from agenticops.tools.metadata_tools import save_execution_result
    cr_id, pid, ex_id = _change_run(db)
    before = _snapshot(db, pid, cr_id, ex_id)
    out = save_execution_result(fix_plan_id=pid, status="succeeded", post_check_results=PASSED)  # no Run Context
    assert out.startswith("REJECTED:") and f"C#{cr_id}" in out
    assert _snapshot(db, pid, cr_id, ex_id) == before


def test_a_change_plan_not_yet_queued_cannot_record(db):
    from agenticops.tools.metadata_tools import save_execution_result
    cr_id, pid, _ = _change_run(db, plan_status="approved", cr_status="approved", ticket_status=None)
    before = _snapshot(db, pid, cr_id)
    out = save_execution_result(fix_plan_id=pid, status="succeeded", post_check_results=PASSED)  # no Run Context
    assert out.startswith("REJECTED:")
    assert _snapshot(db, pid, cr_id) == before


# ── (c) aborted ──────────────────────────────────────────────────────────────

def test_an_aborted_fix_run_fails_its_executing_plan(db):
    _, pid, ex_id = _fix_run(db)
    fake, _ = _recorder("aborted", error_message="pre-check failed")
    _run(ex_id, pid, fake)
    db.expire_all()
    assert [r.id for r in db.query(FixExecution).all()] == [ex_id]
    assert db.get(FixExecution, ex_id).status == "aborted" and db.get(FixPlan, pid).status == "failed"


def test_an_aborted_change_run_fails_its_plan_and_change_request(db):
    cr_id, pid, ex_id = _change_run(db)
    fake, _ = _recorder("aborted", error_message="pre-check failed")
    _run(ex_id, pid, fake)
    db.expire_all()
    assert db.get(FixExecution, ex_id).status == "aborted"
    assert db.get(FixPlan, pid).status == "failed" and db.get(ChangeRequest, cr_id).status == "failed"
    [row] = _audits(db, "change.failed")
    assert row.details["execution_status"] == "aborted"


# ── (d) the post-run reconcile ───────────────────────────────────────────────

def test_a_change_run_that_never_recorded_fails(db):
    cr_id, pid, ex_id = _change_run(db)
    _run(ex_id, pid, lambda fix_plan_id: "Executor agent error: throttled")
    db.expire_all()
    ex = db.get(FixExecution, ex_id)
    assert ex.status == "failed"
    assert ex.error_message.startswith("Executor ended without recording a result: Executor agent error: throttled")
    assert db.get(FixPlan, pid).status == "failed" and db.get(ChangeRequest, cr_id).status == "failed"
    rows = _audits(db, "change.failed")
    assert len(rows) == 1 and "without recording" in rows[0].details["reason"]


def test_a_fix_run_that_never_recorded_fails(db):
    _, pid, ex_id = _fix_run(db)
    _run(ex_id, pid, lambda fix_plan_id: "Executor agent error: throttled")
    db.expire_all()
    assert db.get(FixExecution, ex_id).status == "failed" and db.get(FixPlan, pid).status == "failed"


def test_a_timeout_fails_the_run_and_a_second_close_writes_nothing(db, monkeypatch):
    from agenticops.audit.models import AuditLog
    from agenticops.config import settings
    monkeypatch.setattr(settings, "executor_total_timeout", 7)
    cr_id, pid, ex_id = _change_run(db)
    svc = ExecutorService()
    svc._mark_timed_out(ex_id)
    db.expire_all()
    ex = db.get(FixExecution, ex_id)
    assert ex.status == "failed" and "timed out after 7s" in ex.error_message
    assert db.get(FixPlan, pid).status == "failed" and db.get(ChangeRequest, cr_id).status == "failed"
    audits = db.query(AuditLog).filter_by(entity_id=str(cr_id)).count()
    assert svc._fail_execution(ex_id, "x") is False
    db.expire_all()
    assert db.query(AuditLog).filter_by(entity_id=str(cr_id)).count() == audits
    assert "timed out after 7s" in db.get(FixExecution, ex_id).error_message


def test_a_failing_reconcile_is_contained(db, caplog):
    cr_id, pid, ex_id = _change_run(db)
    svc = ExecutorService()
    svc._active_executions[ex_id] = MagicMock()
    with caplog.at_level(logging.WARNING, logger="agenticops.services.executor_service"), \
         patch.object(ExecutorService, "_fail_execution", side_effect=RuntimeError("db down")) as reconcile, \
         patch("agenticops.agents.executor_agent.executor_agent", return_value="Executor agent error: x"):
        svc._run_executor(ex_id, pid)  # does not raise
    assert reconcile.called and ex_id not in svc._active_executions
    assert any(r.levelno == logging.WARNING and f"post-run reconcile failed for Execution #{ex_id}" in r.getMessage()
               for r in caplog.records)


# ── (a) account binding ──────────────────────────────────────────────────────

def test_a_change_whose_account_does_not_resolve_is_refused(db):
    from agenticops.agents.executor_agent import executor_agent
    cr_id, pid, ex_id = _change_run(db)
    with _executor_build() as (agent_cls, model_cls, cli_tool), _in_run(pid, cr_id, ex_id):
        out = executor_agent(fix_plan_id=pid)
    assert out.startswith("REJECTED: cannot resolve credentials for the account of change request C#")
    assert f"C#{cr_id}" in out
    assert cli_tool.called and not agent_cls.called and not model_cls.called


def test_a_change_whose_account_resolution_raises_is_refused_and_logged(db, caplog):
    from agenticops.agents.executor_agent import executor_agent
    cr_id, pid, ex_id = _change_run(db)
    with caplog.at_level(logging.WARNING, logger="agenticops.agents.executor_agent"), \
         _executor_build() as (agent_cls, model_cls, cli_tool), _in_run(pid, cr_id, ex_id):
        cli_tool.side_effect = RuntimeError("sts down")
        out = executor_agent(fix_plan_id=pid)
    assert out.startswith("REJECTED: cannot resolve credentials for the account of change request C#")
    assert not agent_cls.called and not model_cls.called
    assert any(r.levelno == logging.WARNING and f"Executor account resolution failed for FixPlan #{pid}" in r.getMessage()
               for r in caplog.records)


def _account_refusal(cr_id):
    return (f"REJECTED: cannot resolve credentials for the account of change request C#{cr_id} — "
            f"a change runs only on its own account, never on a fallback.")


def test_a_change_whose_account_read_raises_is_refused(db):
    """The account block's own first read raises, before the plan's kind is known: the Run Context names the
    change request, so the run is refused rather than handed the fallback tools."""
    import agenticops.models as models_mod
    from agenticops.agents.executor_agent import executor_agent
    cr_id, pid, ex_id = _change_run(db)
    real_session, calls = models_mod.get_db_session, []

    def flaky_session():  # executor_agent's 1st get_db_session() is the 9b gate, its 2nd the account block
        calls.append(len(calls) + 1)
        if len(calls) == 1:
            return real_session()
        raise RuntimeError("database is locked")

    with _executor_build() as (agent_cls, model_cls, cli_tool), _in_run(pid, cr_id, ex_id), \
         patch("agenticops.models.get_db_session", side_effect=flaky_session):
        out = executor_agent(fix_plan_id=pid)
    assert out == _account_refusal(cr_id)
    assert calls == [1, 2]  # refused right after the account block: no further read
    assert not cli_tool.called and not agent_cls.called and not model_cls.called


def test_a_change_whose_request_row_is_missing_is_refused(db):
    """Only a change request that WAS read and has no account clears the binding; a missing row does not."""
    from agenticops.agents.executor_agent import executor_agent
    cr_id, pid, ex_id = _change_run(db)
    db.query(ChangeRequest).filter_by(id=cr_id).delete(synchronize_session=False)  # bulk: the plan keeps its id
    db.commit()
    db.expire_all()
    assert db.get(FixPlan, pid).change_request_id == cr_id and db.get(ChangeRequest, cr_id) is None
    with _executor_build() as (agent_cls, model_cls, cli_tool), _in_run(pid, cr_id, ex_id), \
         patch("agenticops.services.change_service.change_execution_refusal", return_value=None):
        out = executor_agent(fix_plan_id=pid)
    assert out == _account_refusal(cr_id)
    assert not cli_tool.called and not agent_cls.called and not model_cls.called


def test_a_change_run_whose_plan_row_reads_as_missing_is_refused(db):
    """A plan row that reads as missing is treated like a failed read: the Run Context names the change request,
    so the run is refused rather than handed the fallback tools."""
    from agenticops.agents.executor_agent import executor_agent
    missing = 9999
    assert db.get(FixPlan, missing) is None
    with _executor_build() as (agent_cls, model_cls, cli_tool), _in_run(missing, 7, None):
        out = executor_agent(fix_plan_id=missing)
    assert out.startswith("REJECTED: cannot resolve credentials for the account of change request C#7")
    assert out == _account_refusal(7)
    assert not cli_tool.called and not agent_cls.called and not model_cls.called


def test_a_run_whose_plan_row_reads_as_missing_without_a_change_request_is_unchanged(db):
    """No change request in the Run Context (a fix-plan run, or no queued run at all): the fallback, as before."""
    from agenticops.agents.executor_agent import executor_agent
    missing = 9999
    for run in (_in_run(missing, None, None), nullcontext()):
        with _executor_build() as (agent_cls, _, cli_tool), run:
            out = executor_agent(fix_plan_id=missing)
        assert out == "done" and agent_cls.call_count == 1 and not cli_tool.called
        tools = agent_cls.call_args.kwargs["tools"]
        assert run_aws_cli in tools and run_aws_cli_readonly in tools


def test_a_change_with_no_account_uses_the_account_addressed_tools(db):
    from agenticops.agents.executor_agent import executor_agent
    cr_id, pid, ex_id = _change_run(db, account=False)
    with _executor_build() as (agent_cls, _, cli_tool), _in_run(pid, cr_id, ex_id):
        out = executor_agent(fix_plan_id=pid)
    assert out == "done" and agent_cls.call_count == 1 and not cli_tool.called
    tools = agent_cls.call_args.kwargs["tools"]
    assert run_aws_cli in tools and run_aws_cli_readonly in tools


def test_a_change_whose_account_resolves_runs_on_that_accounts_tool(db):
    from agenticops.agents.executor_agent import executor_agent

    def account_cli(command: str) -> str:  # the provider-resolved CLI tool for the change's account
        return ""

    cr_id, pid, ex_id = _change_run(db)
    with _executor_build() as (agent_cls, _, cli_tool), _in_run(pid, cr_id, ex_id):
        cli_tool.return_value = account_cli
        out = executor_agent(fix_plan_id=pid)
    assert out == "done" and agent_cls.call_count == 1
    cli_tool.assert_called_once_with(_dev_id(db))
    tools = agent_cls.call_args.kwargs["tools"]
    assert account_cli in tools and run_aws_cli not in tools and run_aws_cli_readonly not in tools


def test_a_fix_plan_keeps_its_account_fallback(db):
    # Pre-existing fallback, owner decision, pinned so that Task 9c's scope is visible: only a change plan
    # bound to an account refuses to run on a fallback; a fix plan whose account does not resolve still runs.
    from agenticops.agents.executor_agent import executor_agent
    _, pid, ex_id = _fix_run(db, account_id=_dev_id(db))
    with _executor_build() as (agent_cls, _, cli_tool), _in_run(pid, None, ex_id):
        out = executor_agent(fix_plan_id=pid)
    assert out == "done" and cli_tool.called and agent_cls.call_count == 1
    assert run_aws_cli in agent_cls.call_args.kwargs["tools"]


def test_an_unresolvable_change_fails_its_run_end_to_end(db):
    cr_id, pid, ex_id = _change_run(db)
    svc = ExecutorService()
    svc._active_executions[ex_id] = MagicMock()
    with _executor_build() as (agent_cls, _, _):
        svc._run_executor(ex_id, pid)  # the real executor_agent, under the Run Context the service sets
    assert not agent_cls.called and ex_id not in svc._active_executions
    db.expire_all()
    ex = db.get(FixExecution, ex_id)
    assert ex.status == "failed" and "REJECTED: cannot resolve credentials" in ex.error_message
    assert db.get(FixPlan, pid).status == "failed" and db.get(ChangeRequest, cr_id).status == "failed"


# ── (e) cancel ───────────────────────────────────────────────────────────────

def test_cancel_fails_a_change_run(db):
    cr_id, pid, ex_id = _change_run(db)
    assert ExecutorService().cancel_execution(ex_id) is True
    db.expire_all()
    ex = db.get(FixExecution, ex_id)
    assert ex.status == "aborted" and ex.error_message == "Cancelled by operator"
    assert db.get(FixPlan, pid).status == "failed" and db.get(ChangeRequest, cr_id).status == "failed"
    [row] = _audits(db, "change.failed")
    assert row.details["execution_status"] == "aborted" and row.details["reason"] == "Cancelled by operator"


def test_cancel_fails_a_fix_run(db):
    _, pid, ex_id = _fix_run(db)
    assert ExecutorService().cancel_execution(ex_id) is True
    db.expire_all()
    assert db.get(FixExecution, ex_id).status == "aborted" and db.get(FixPlan, pid).status == "failed"


def test_a_pending_ticket_cannot_be_cancelled(db):
    cr_id, pid, ex_id = _change_run(db, ticket_status="pending")
    before = _snapshot(db, pid, cr_id, ex_id)
    assert ExecutorService().cancel_execution(ex_id) is False
    assert _snapshot(db, pid, cr_id, ex_id) == before


def test_after_a_cancel_the_still_running_agent_can_neither_record_nor_run(db):
    from agenticops.services.command_audit import approved_plan_in_context
    from agenticops.tools.metadata_tools import save_execution_result
    cr_id, pid, ex_id = _change_run(db)
    assert ExecutorService().cancel_execution(ex_id) is True
    with _in_run(pid, cr_id, ex_id):
        out = save_execution_result(fix_plan_id=pid, status="succeeded", post_check_results=PASSED)
        in_plan = approved_plan_in_context()
    assert out.startswith("REJECTED:") and f"C#{cr_id}" in out
    db.expire_all()
    assert db.query(FixExecution).count() == 1 and db.get(ChangeRequest, cr_id).status == "failed"
    assert in_plan is None


def test_web_cancel_attributes_the_change_failure_to_the_canceller(db):
    from starlette.testclient import TestClient
    from agenticops.auth.actor import web_anonymous_actor
    from agenticops.web.app import app
    cr_id, pid, ex_id = _change_run(db)
    r = TestClient(app).post(f"/api/fix-executions/{ex_id}/cancel")
    assert r.status_code == 200 and r.json() == {"status": "cancelled", "execution_id": ex_id}
    db.expire_all()
    assert db.get(ChangeRequest, cr_id).status == "failed"
    [row] = _audits(db, "change.failed")
    assert row.actor != "agent:executor"
    assert row.actor == web_anonymous_actor().key  # auth off: the web actor


# ── the ticket is the arbiter: a cancel, a timeout and a recorded result close it by compare-and-set ─────

def _refused_late(ex_id, pid):
    return (f"REJECTED: Execution #{ex_id} for FixPlan #{pid} is no longer running — it was cancelled, timed out "
            f"or already recorded; this result was not recorded.")


@contextmanager
def _cancel_after_saves_read(ex_id):
    """Cancel the ticket after save_execution_result has read the plan and before it writes the ticket."""
    from agenticops.services import change_service
    real = change_service.change_execution_refusal

    def refusal_then_cancel(plan):
        refusal = real(plan)
        assert ExecutorService().cancel_execution(ex_id) is True  # in its own session, committed
        return refusal

    with patch("agenticops.services.change_service.change_execution_refusal", side_effect=refusal_then_cancel):
        yield


def _late_result_logged(caplog, ex_id, pid, status):
    """The lost compare-and-set's WARNING: the only record of the discarded late result."""
    want = (f"save_execution_result: Execution #{ex_id} for FixPlan #{pid} is no longer running — "
            f"the agent's '{status}' result was not recorded")
    return [r.levelno for r in caplog.records
            if r.name == "agenticops.tools.metadata_tools" and r.getMessage() == want] == [logging.WARNING]


def test_a_cancel_inside_a_change_runs_save_wins_and_the_save_is_refused(db, caplog):
    from agenticops.tools.metadata_tools import save_execution_result
    cr_id, pid, ex_id = _change_run(db)
    with caplog.at_level(logging.WARNING, logger="agenticops.tools.metadata_tools"), \
         _in_run(pid, cr_id, ex_id), _cancel_after_saves_read(ex_id):
        out = save_execution_result(fix_plan_id=pid, status="succeeded", post_check_results=PASSED)
    assert out == _refused_late(ex_id, pid)
    assert _late_result_logged(caplog, ex_id, pid, "succeeded")
    db.expire_all()
    [ex] = db.query(FixExecution).filter_by(fix_plan_id=pid).all()  # no second row
    assert ex.id == ex_id and ex.status == "aborted" and ex.error_message == "Cancelled by operator"
    assert db.get(FixPlan, pid).status == "failed" and db.get(ChangeRequest, cr_id).status == "failed"
    assert len(_audits(db, "change.failed")) == 1 and _audits(db, "change.completed") == []


def test_a_cancel_inside_a_fix_runs_save_wins_and_the_save_is_refused(db, caplog):
    from agenticops.tools.metadata_tools import save_execution_result
    issue_id, pid, ex_id = _fix_run(db)
    with caplog.at_level(logging.WARNING, logger="agenticops.tools.metadata_tools"), \
         _in_run(pid, None, ex_id), _cancel_after_saves_read(ex_id):
        out = save_execution_result(fix_plan_id=pid, health_issue_id=issue_id, status="succeeded")
    assert out == _refused_late(ex_id, pid)
    assert _late_result_logged(caplog, ex_id, pid, "succeeded")
    db.expire_all()
    [ex] = db.query(FixExecution).filter_by(fix_plan_id=pid).all()  # no second row
    assert ex.id == ex_id and ex.status == "aborted"
    assert db.get(FixPlan, pid).status == "failed" and db.get(HealthIssue, issue_id).status == "fix_approved"


def test_after_a_recorded_result_a_cancel_and_a_timeout_write_nothing(db):
    from agenticops.tools.metadata_tools import save_execution_result
    cr_id, pid, ex_id = _change_run(db)
    with _in_run(pid, cr_id, ex_id):
        out = save_execution_result(fix_plan_id=pid, status="succeeded", post_check_results=PASSED)
    assert out.startswith(f"FixExecution #{ex_id} saved")
    before = _snapshot(db, pid, cr_id, ex_id)
    assert before[:4] == ("succeeded", "executed", "completed", 1)
    svc = ExecutorService()
    assert svc.cancel_execution(ex_id) is False
    assert svc._fail_execution(ex_id, "Execution timed out after 7s") is False
    assert _snapshot(db, pid, cr_id, ex_id) == before and db.get(FixExecution, ex_id).error_message is None
    assert len(_audits(db, "change.completed")) == 1 and _audits(db, "change.failed") == []


def test_two_overlapping_mapper_calls_leave_one_terminal_and_one_audit_row(db, caplog):
    from agenticops.services import change_service
    cr_id, pid, _ = _change_run(db)
    real = change_service.evaluate

    def a_failure_lands_meanwhile(*args):  # the 1st call has read the request as executing
        verdict = real(*args)
        if args[0] == "succeeded":
            change_service.on_execution_result(pid, "failed", error="Execution timed out after 7s")  # commits first
        return verdict

    with caplog.at_level(logging.WARNING, logger="agenticops.services.change_service"), \
         patch.object(change_service, "evaluate", side_effect=a_failure_lands_meanwhile):
        snap = change_service.on_execution_result(pid, "succeeded",
                                                  post_check_results=[{"check": "c", "status": "pass"}])
    db.expire_all()
    assert db.get(ChangeRequest, cr_id).status == "failed" and snap["status"] == "failed"
    terminal = [a for a in ("change.completed", "change.needs_review", "change.failed", "change.rolled_back")
                for _ in _audits(db, a)]
    assert terminal == ["change.failed"]
    assert any(r.levelno == logging.WARNING and f"CR #{cr_id} lost the executing claim" in r.getMessage()
               for r in caplog.records)


def test_the_ticket_closes_scrub_secrets_as_the_orm_write_does(db):
    """Both compare-and-set closes write through Core, past the ORM's before_flush scrubber."""
    from agenticops.tools.metadata_tools import save_execution_result
    akid = "AKIAIOSFODNN7EXAMPLE"  # the AWS documentation example key id
    issue_a, a, ex_a = _fix_run(db)
    _, b, ex_b = _fix_run(db)
    with _in_run(a, None, ex_a):
        out = save_execution_result(fix_plan_id=a, health_issue_id=issue_a, status="failed",
                                    error_message=f"key {akid}", step_results=json.dumps([{"output": f"used {akid}"}]))
    assert out.startswith(f"FixExecution #{ex_a} saved")
    assert ExecutorService()._fail_execution(ex_b, f"Executor ended without recording a result: {akid}") is True
    db.expire_all()
    for ex_id in (ex_a, ex_b):
        ex = db.get(FixExecution, ex_id)
        assert ex.status == "failed" and akid not in f"{ex.step_results} {ex.error_message}"


# ── mark_fix_executed: only a succeeded run of the issue's executed plan ─────

def _mark(db, issue_id, ex_id):
    """mark_fix_executed's result and the issue's status afterwards."""
    from agenticops.tools.metadata_tools import mark_fix_executed
    out = mark_fix_executed(health_issue_id=issue_id, execution_id=ex_id)
    db.expire_all()
    return out, db.get(HealthIssue, issue_id).status


def test_mark_fix_executed_refuses_a_run_a_cancel_aborted(db):
    """After a refused late save (the cancel won) the ticket is aborted and the plan failed; the executor still
    calls mark_fix_executed, and the issue must not read fix_executed."""
    issue_id, pid, ex_id = _fix_run(db, plan_status="failed", ticket_status="aborted")
    before = _snapshot(db, pid, None, ex_id)
    out, status = _mark(db, issue_id, ex_id)
    assert out == (f"REJECTED: FixExecution #{ex_id} is 'aborted' and its FixPlan #{pid} is 'failed' "
                   f"(for HealthIssue #{issue_id}) — only a succeeded run of HealthIssue #{issue_id}'s executed "
                   f"plan marks it fix_executed.")
    assert status == "fix_approved" and _snapshot(db, pid, None, ex_id) == before


@pytest.mark.parametrize("plan_status, ticket_status", [
    ("executed", "failed"),      # the run failed (the plan was executed by another run)
    ("executing", "succeeded"),  # the plan is not executed
], ids=["failed-run", "plan-not-executed"])
def test_mark_fix_executed_refuses_an_unfinished_run(db, plan_status, ticket_status):
    issue_id, pid, ex_id = _fix_run(db, plan_status=plan_status, ticket_status=ticket_status)
    before = _snapshot(db, pid, None, ex_id)
    out, status = _mark(db, issue_id, ex_id)
    assert out.startswith(f"REJECTED: FixExecution #{ex_id} is '{ticket_status}' and its FixPlan #{pid} is "
                          f"'{plan_status}'")
    assert status == "fix_approved" and _snapshot(db, pid, None, ex_id) == before


def test_mark_fix_executed_refuses_another_issues_run(db):
    owner_id, pid, ex_id = _fix_run(db, plan_status="executed", ticket_status="succeeded")
    other_id, _, _ = _fix_run(db, plan_status="approved", ticket_status=None)
    before = _snapshot(db, pid, None, ex_id)
    out, status = _mark(db, other_id, ex_id)
    assert out == (f"REJECTED: FixExecution #{ex_id} is 'succeeded' and its FixPlan #{pid} is 'executed' "
                   f"(for HealthIssue #{owner_id}) — only a succeeded run of HealthIssue #{other_id}'s executed "
                   f"plan marks it fix_executed.")
    assert status == "fix_approved" and _snapshot(db, pid, None, ex_id) == before
    assert db.get(HealthIssue, owner_id).status == "fix_approved"


def test_mark_fix_executed_marks_a_succeeded_run_of_the_issues_executed_plan(db):
    issue_id, pid, ex_id = _fix_run(db, plan_status="executed", ticket_status="succeeded")
    out, status = _mark(db, issue_id, ex_id)
    assert out == f"HealthIssue #{issue_id} status: fix_approved -> fix_executed. Execution #{ex_id} recorded."
    assert status == "fix_executed"


def test_mark_fix_executed_leaves_an_auto_resolved_issue_alone(db):
    issue_id, pid, ex_id = _fix_run(db, plan_status="executed", ticket_status="succeeded")
    db.get(HealthIssue, issue_id).status = "resolved"
    db.commit()
    out, status = _mark(db, issue_id, ex_id)
    assert out == (f"HealthIssue #{issue_id} already auto-resolved. Execution #{ex_id} recorded. "
                   f"No status change needed.")
    assert status == "resolved"


# ── (f) G13: a change run is bound to its CR's account; a fix run is unbound ──

def _binding_recorder():
    """A fake executor_agent that records the bound_account_id of the RunContext it runs under."""
    from agenticops.run_context import get_run_context
    seen = {}

    def fake(fix_plan_id):
        seen["bound"] = get_run_context().bound_account_id
        return "recorded"
    return fake, seen


def test_a_change_run_is_bound_to_its_change_request_account(db):
    _cr_id, pid, ex_id = _change_run(db)  # cr.account_id = the 'dev' account
    fake, seen = _binding_recorder()
    _run(ex_id, pid, fake)
    assert seen["bound"] == _dev_id(db)


def test_a_fix_run_is_unbound(db):
    _issue_id, pid, ex_id = _fix_run(db)  # a fix plan has no change request
    fake, seen = _binding_recorder()
    _run(ex_id, pid, fake)
    assert seen["bound"] is None
