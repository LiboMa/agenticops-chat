"""A change plan's lifecycle is owned by its change request (MVP-2.6.0 Task 9b).

Every fix-plan path refuses a change plan: the approve_fix_plan / get_approved_fix_plan tools, the
executor_agent entry, the Web fix-plan endpoints and the CLI plain-id /approve and /execute. A refused call
changes nothing: plan and change-request status, audit rows and FixExecution rows all stay as they were.
"""
import json
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from agenticops.models import Base, ChangeRequest, CloudAccount, FixExecution, FixPlan, HealthIssue, RCAResult, get_session


@pytest.fixture
def db(tmp_path, monkeypatch):
    import agenticops.models as models_mod
    import agenticops.audit.models  # noqa: F401
    from agenticops.config import settings
    monkeypatch.setattr(models_mod, "_engine", None)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/guard.db")
    monkeypatch.setattr(settings, "change_management_enabled", True)
    monkeypatch.setattr(settings, "executor_enabled", True)
    Base.metadata.create_all(models_mod.get_engine())
    s = get_session()
    yield s
    s.close()


@pytest.fixture
def client(db):
    from starlette.testclient import TestClient
    from agenticops.web.app import app
    yield TestClient(app)


def _change_plan(db, plan_status, cr_status, *, account_id=None):
    """A change plan and its change request, inserted directly (there is no ORM status validator)."""
    cr = ChangeRequest(title="tag web", description="d", requested_by="user:alice", status=cr_status,
                       account_id=account_id)
    db.add(cr); db.flush()
    plan = FixPlan(plan_kind="change", change_request_id=cr.id, risk_level="L1", title="p", summary="s",
                   status=plan_status, rollback_plan={"steps": ["undo"]}, post_checks=[{"check": "c"}])
    db.add(plan); db.commit()
    return plan.id, cr.id


def _fix_plan(db, status):
    """A plain fix plan, the same row shape as tests/test_fix_plan_hardening_api.py::_plan."""
    issue = HealthIssue(title="t", description="d", severity="low", source="test", status="fix_planned", resource_id="r")
    db.add(issue); db.flush()
    rca = RCAResult(health_issue_id=issue.id, root_cause="x", confidence=0.9)
    db.add(rca); db.flush()
    plan = FixPlan(health_issue_id=issue.id, rca_result_id=rca.id, risk_level="L1", title="p", summary="s",
                   status=status)
    db.add(plan); db.commit()
    return plan.id


def _audit_count():
    from agenticops.audit.models import AuditLog
    s = get_session()
    try:
        return s.query(AuditLog).count()
    finally:
        s.close()


def _state(db, pid, cr_id):
    """What a refused call must not change: plan status, change-request status, audit rows, executions."""
    db.expire_all()
    plan = db.get(FixPlan, pid)
    return (plan.status if plan else None, db.get(ChangeRequest, cr_id).status, _audit_count(),
            db.query(FixExecution).count())


@contextmanager
def _queued_run(pid, cr_id):
    """The Run Context ExecutorService._run_executor sets for the execution request_execution queued."""
    from agenticops.run_context import RunContext, reset_run_context, set_run_context
    token = set_run_context(RunContext(actor="agent:executor", agent_name="executor", fix_plan_id=pid,
                                       change_request_id=cr_id))
    try:
        yield
    finally:
        reset_run_context(token)


@contextmanager
def _executor_build():
    """Lets executor_agent build and run without Bedrock; yields the Agent and get_cli_tool_for_issue mocks."""
    ea = "agenticops.agents.executor_agent"
    with patch(f"{ea}.Agent") as agent_cls, patch(f"{ea}.BedrockModel"), \
         patch(f"{ea}.build_system_prompt", side_effect=lambda p, **kw: p), \
         patch(f"{ea}.get_cli_tool_for_issue", return_value=None) as cli_tool, \
         patch("agenticops.config.get_bedrock_boto_session", return_value=MagicMock()), \
         patch("agenticops.agents.preamble.invoke_with_retry", return_value="done"), \
         patch("agenticops.services.agent_log_service.track_agent"):
        yield agent_cls, cli_tool


@contextmanager
def _cli():
    """The CLI as operator 'malibo'; yields the Confirm.ask mock, which a refusal must never reach."""
    with patch("agenticops.cli.main.init_db"), patch("getpass.getuser", return_value="malibo"), \
         patch("rich.prompt.Confirm.ask", return_value=False) as ask:
        yield ask


# ── helpers ──────────────────────────────────────────────────────────────────

def test_helpers_refuse_only_a_change_plan_and_name_its_change_request(db, monkeypatch):
    from agenticops.config import settings
    from agenticops.services.change_service import change_execution_refusal, fix_path_refusal
    assert fix_path_refusal(None, "x") is None and change_execution_refusal(None) is None
    fix = db.get(FixPlan, _fix_plan(db, "approved"))
    assert fix_path_refusal(fix, "approved") is None and change_execution_refusal(fix) is None
    pid, cr_id = _change_plan(db, "pending_approval", "planned")
    plan = db.get(FixPlan, pid)
    msg = fix_path_refusal(plan, "approved")
    assert f"C#{cr_id}" in msg and "cannot be approved" in msg and f"/approve C{cr_id}" in msg
    monkeypatch.setattr(settings, "change_management_enabled", False)
    msg = fix_path_refusal(plan, "approved")  # still refused: the guard is not gated by the flag, only the hint
    assert "Change management is disabled" in msg and "/approve C" not in msg


# ── agent tools ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("plan_status", ["draft", "pending_approval"])
def test_approve_fix_plan_tool_refuses_a_change_plan(db, plan_status):
    from agenticops.tools.metadata_tools import approve_fix_plan
    pid, cr_id = _change_plan(db, plan_status, "planned")
    before = _state(db, pid, cr_id)
    with patch("agenticops.services.pipeline_service.trigger_auto_execute") as auto_exec:
        out = approve_fix_plan(fix_plan_id=pid, approved_by="agent:main")
    assert out.startswith("REJECTED:") and f"C#{cr_id}" in out
    assert _state(db, pid, cr_id) == before
    assert not auto_exec.called


def test_get_approved_fix_plan_refuses_a_change_plan_without_its_run_context(db):
    from agenticops.tools.metadata_tools import get_approved_fix_plan
    pid, cr_id = _change_plan(db, "approved", "approved")
    before = _state(db, pid, cr_id)
    out = get_approved_fix_plan(pid)
    assert out.startswith("REJECTED:") and f"C#{cr_id}" in out
    assert _state(db, pid, cr_id) == before


def test_get_approved_fix_plan_refuses_another_runs_context(db):
    from agenticops.tools.metadata_tools import get_approved_fix_plan
    pid, cr_id = _change_plan(db, "executing", "executing")
    before = _state(db, pid, cr_id)
    with _queued_run(pid + 1, cr_id):  # the Run Context of a different plan's execution
        out = get_approved_fix_plan(pid)
    assert out.startswith("REJECTED:") and f"C#{cr_id}" in out
    assert _state(db, pid, cr_id) == before


def test_get_approved_fix_plan_serves_the_queued_run(db):
    from agenticops.tools.metadata_tools import get_approved_fix_plan
    pid, cr_id = _change_plan(db, "executing", "executing")
    with _queued_run(pid, cr_id):
        data = json.loads(get_approved_fix_plan(pid))
    assert data["plan_kind"] == "change" and data["status"] == "executing" and data["change_request_id"] == cr_id


def test_get_approved_fix_plan_serves_a_fix_plan_as_before(db):
    from agenticops.tools.metadata_tools import get_approved_fix_plan
    data = json.loads(get_approved_fix_plan(_fix_plan(db, "approved")))  # no Run Context
    assert data["plan_kind"] == "fix" and data["status"] == "approved"


# ── executor_agent entry ─────────────────────────────────────────────────────

def test_executor_agent_refuses_a_change_plan_before_account_resolution(db):
    from agenticops.agents.executor_agent import executor_agent
    acct = CloudAccount(name="dev", provider="aws", is_enabled=True, credentials={}, regions=[])
    db.add(acct); db.commit()
    pid, cr_id = _change_plan(db, "approved", "approved", account_id=acct.id)  # account-bound: resolution would run
    before = _state(db, pid, cr_id)
    with _executor_build() as (agent_cls, cli_tool):
        out = executor_agent(fix_plan_id=pid)  # no Run Context
    assert out.startswith("REJECTED:") and f"C#{cr_id}" in out
    assert not agent_cls.called and not cli_tool.called
    assert _state(db, pid, cr_id) == before


def test_executor_agent_runs_the_queued_change_execution(db):
    from agenticops.agents.executor_agent import executor_agent
    pid, cr_id = _change_plan(db, "executing", "executing")
    with _executor_build() as (agent_cls, _), _queued_run(pid, cr_id):
        out = executor_agent(fix_plan_id=pid)
    assert agent_cls.call_count == 1 and out == "done"


def test_executor_agent_runs_a_fix_plan_as_before(db):
    from agenticops.agents.executor_agent import executor_agent
    pid = _fix_plan(db, "approved")
    with _executor_build() as (agent_cls, _):
        out = executor_agent(fix_plan_id=pid)  # no Run Context
    assert agent_cls.call_count == 1 and out == "done"


# ── Web API ──────────────────────────────────────────────────────────────────

_WEB_CALLS = {
    "edit": ("PUT", "/api/fix-plans/{pid}", {"title": "x"}),
    "reject-via-deprecated-put": ("PUT", "/api/fix-plans/{pid}", {"status": "rejected"}),
    "approve": ("PUT", "/api/fix-plans/{pid}/approve", {}),
    "reject": ("POST", "/api/fix-plans/{pid}/reject", {"reason": "no"}),
    "delete": ("DELETE", "/api/fix-plans/{pid}", None),
    "execute": ("POST", "/api/fix-plans/{pid}/execute", None),
}


@pytest.mark.parametrize("call", list(_WEB_CALLS))
def test_web_fix_plan_endpoints_refuse_a_change_plan(client, db, call):
    method, path, body = _WEB_CALLS[call]
    statuses = ("approved", "approved") if call == "execute" else ("pending_approval", "planned")
    pid, cr_id = _change_plan(db, *statuses)
    before = _state(db, pid, cr_id)
    with patch("agenticops.services.pipeline_service.trigger_auto_execute") as auto_exec:
        r = client.request(method, path.format(pid=pid), json=body)
    assert r.status_code == 409 and f"C#{cr_id}" in r.json()["detail"]
    assert _state(db, pid, cr_id) == before
    plan = db.get(FixPlan, pid)
    assert plan is not None and plan.title == "p"  # DELETE kept the row; PUT kept the content
    assert not auto_exec.called


def test_web_reject_of_a_fix_plan_unchanged(client, db):
    pid = _fix_plan(db, "pending_approval")
    r = client.post(f"/api/fix-plans/{pid}/reject", json={"reason": "no"})
    assert r.status_code == 200 and r.json()["status"] == "rejected"


# ── CLI ──────────────────────────────────────────────────────────────────────

def test_cli_approve_refuses_a_change_plan(db):
    from agenticops.cli import main as cli
    pid, cr_id = _change_plan(db, "pending_approval", "planned")
    before = _state(db, pid, cr_id)
    with _cli() as ask:
        out = cli._slash_approve(None, [str(pid)])
    assert f"C#{cr_id}" in out and f"/approve C{cr_id}" in out
    assert _state(db, pid, cr_id) == before
    assert not ask.called


def test_cli_execute_refuses_a_change_plan(db):
    from agenticops.cli import main as cli
    pid, cr_id = _change_plan(db, "approved", "approved")
    before = _state(db, pid, cr_id)
    with _cli() as ask:
        out = cli._slash_execute(None, [str(pid)])
    assert f"C#{cr_id}" in out
    assert _state(db, pid, cr_id) == before  # no FixExecution row
    assert not ask.called
