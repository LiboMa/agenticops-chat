"""Every entry point that starts an agent or a worker thread sets the Run Context (Task 11).

Web chat SSE, CLI headless, IM gateways (Feishu/Slack), ExecutorService worker, pipeline
threads (auto-SRE / auto-execute) and the scheduler's AgentChain run. The thread functions
are invoked directly here (no worker thread), so their set_run_context()/set_trace_id()
writes land in the pytest main thread — the autouse fixture restores both afterwards.
"""

import getpass
import threading
from collections import defaultdict
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

import agenticops.scheduler.scheduler as scheduler_mod  # registers Schedule/ScheduleExecution on Base
from agenticops.models import Base, FixExecution, FixPlan, HealthIssue, RCAResult, get_session
from agenticops.run_context import get_run_context, reset_run_context, set_run_context


@pytest.fixture(autouse=True)
def _restore_context_vars():
    """Undo the run-context / trace-id writes the entry points make in this (test) thread."""
    from agenticops.config import get_trace_id, set_trace_id
    rc_token = set_run_context(get_run_context())
    saved_tid = get_trace_id()
    yield
    set_trace_id(saved_tid)
    reset_run_context(rc_token)


@pytest.fixture
def db(tmp_path, monkeypatch):
    import agenticops.models as models_mod
    from agenticops.config import settings
    models_mod._engine = None
    # monkeypatch (not plain assignment) so the tmp database_url does not leak into later tests
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/rc.db")
    Base.metadata.create_all(models_mod.get_engine())
    s = get_session()
    yield s
    s.close()
    models_mod._engine = None


def _approved_plan(db):
    issue = HealthIssue(title="t", description="d", severity="low", source="test", status="fix_approved",
                        resource_id="r", trace_id="TRC-issue1")
    db.add(issue); db.flush()
    rca = RCAResult(health_issue_id=issue.id, root_cause="x", confidence=0.9)
    db.add(rca); db.flush()
    plan = FixPlan(health_issue_id=issue.id, rca_result_id=rca.id, risk_level="L1", title="p", summary="s",
                   status="executing", approved_by="user:alice")
    db.add(plan); db.flush()
    ex = FixExecution(fix_plan_id=plan.id, health_issue_id=issue.id, status="running", executed_by="user:alice")
    db.add(ex); db.commit()
    return plan, ex


# ── ExecutorService worker ───────────────────────────────────────────────────


def test_executor_service_worker_sets_context(db):
    from agenticops.services.command_audit import approved_plan_in_context
    from agenticops.services.executor_service import ExecutorService
    plan, ex = _approved_plan(db)
    seen = {}

    def fake_executor(fix_plan_id):
        seen.update(get_run_context().__dict__)
        # what lets change_required commands run inside the approved plan (Task 10)
        seen["approved_plan"] = approved_plan_in_context()
        return "done"

    with patch("agenticops.agents.executor_agent.executor_agent", side_effect=fake_executor):
        ExecutorService()._run_executor(ex.id, plan.id)
    assert seen["actor"] == "agent:executor" and seen["on_behalf_of"] == "user:alice"
    assert seen["fix_plan_id"] == plan.id and seen["trace_id"] == "TRC-issue1" and seen["agent_name"] == "executor"
    assert seen["approved_plan"] == plan.id


def test_executor_service_worker_clears_trace_after_run(db):
    """Symmetric with the IM sites: the worker clears its trace id next to the RunContext reset."""
    from agenticops.config import get_trace_id
    from agenticops.services.executor_service import ExecutorService
    plan, ex = _approved_plan(db)
    with patch("agenticops.agents.executor_agent.executor_agent", return_value="done"):
        ExecutorService()._run_executor(ex.id, plan.id)
    assert get_trace_id() is None


# ── pipeline threads ─────────────────────────────────────────────────────────


def test_pipeline_auto_execute_thread_sets_context(db):
    from agenticops.services import pipeline_service
    plan, _ = _approved_plan(db)
    seen = {}

    def fake_executor(fix_plan_id):
        seen.update(get_run_context().__dict__)
        return "done"

    with patch("agenticops.agents.executor_agent.executor_agent", side_effect=fake_executor):
        pipeline_service._run_auto_execute(plan.id, trace_id="TRC-x")
    assert seen["actor"] == "agent:auto-pipeline" and seen["fix_plan_id"] == plan.id and seen["trace_id"] == "TRC-x"


def test_pipeline_auto_execute_resets_context_when_started_event_raises(db):
    """The RunContext is set immediately before the try, so the finally's reset always pairs with it —
    a failure in the execution_started event must not leave the plan context on the thread."""
    from agenticops.services import pipeline_service
    plan, _ = _approved_plan(db)
    before = get_run_context()
    with patch("agenticops.services.pipeline_events.log_event", side_effect=RuntimeError("event sink down")), \
         pytest.raises(RuntimeError):
        pipeline_service._run_auto_execute(plan.id, trace_id="TRC-x")
    assert get_run_context() == before


def test_pipeline_auto_sre_thread_sets_context(db):
    from agenticops.services import pipeline_service
    seen = {}
    with patch("agenticops.agents.sre_agent.sre_agent", side_effect=lambda issue_id: seen.update(get_run_context().__dict__) or "ok"):
        pipeline_service._run_auto_sre(1, trace_id="TRC-y")
    assert seen["actor"] == "agent:auto-pipeline" and seen["agent_name"] == "sre"


@pytest.mark.parametrize("timeout", [0, 30])
def test_pipeline_auto_rca_thread_sets_context(db, monkeypatch, timeout):
    """With rca_timeout_seconds > 0 (the default) rca_agent runs on a nested watchdog thread, so the
    Run Context must reach that thread too; either way it is reset once the pipeline thread is done."""
    from agenticops.config import set_trace_id, settings
    from agenticops.services import rca_service
    monkeypatch.setattr(settings, "rca_timeout_seconds", timeout)
    set_trace_id(None)  # start clean so the restored trace is observable (autouse fixture puts it back)
    seen = {}
    before = get_run_context()
    with patch("agenticops.agents.rca_agent.rca_agent", side_effect=lambda issue_id: seen.update(get_run_context().__dict__) or "ok"):
        rca_service._run_auto_rca(1, trace_id="TRC-z")
    assert seen["actor"] == "agent:auto-pipeline" and seen["agent_name"] == "rca"
    assert seen["trace_id"] == "TRC-z"
    assert get_run_context() == before, "context must be reset in finally"


# ── scheduler AgentChain ─────────────────────────────────────────────────────


def test_scheduler_agent_chain_sets_context(db):
    schedule = scheduler_mod.Schedule(name="rc-chain", pipeline_name="AgentChain", cron_expression="0 0 * * *",
                                      config={"prompt": "say hi"})
    db.add(schedule); db.commit()
    info = {"id": schedule.id, "name": "rc-chain", "pipeline_name": "AgentChain", "account_name": None,
            "config": {"prompt": "say hi"}}
    seen = {}

    def fake_agent(_prompt):
        seen.update(get_run_context().__dict__)
        return "ok"

    storage = MagicMock()
    storage.presigned_url.return_value = None  # a MagicMock is not JSON-serializable into ScheduleExecution.result
    with patch("agenticops.agents.main_agent.create_main_agent", return_value=fake_agent), \
         patch("agenticops.storage.backend.get_storage_backend", return_value=storage), \
         patch("agenticops.services.notification_service.notify_schedule_result"):
        scheduler_mod.Scheduler()._execute_schedule_by_info(info)

    assert seen["actor"] == "agent:scheduler" and seen["agent_name"] == "main"
    assert seen["trace_id"] and seen["trace_id"].startswith("TRC-")
    db.expire_all()
    ex = db.query(scheduler_mod.ScheduleExecution).filter_by(schedule_id=schedule.id).one()
    assert ex.status == "completed"


# ── web chat SSE ─────────────────────────────────────────────────────────────


def test_web_chat_sse_sets_context(db, monkeypatch):
    from starlette.testclient import TestClient

    import agenticops.web.app as webapp
    from agenticops.models import ChatSession

    session_id = "rc-entry-chat-001"
    now = datetime.now(timezone.utc)
    db.add(ChatSession(session_id=session_id, name="rc", created_at=now, updated_at=now, last_activity_at=now))
    db.commit()
    seen = {}

    class _Agent:
        async def stream_async(self, _content):
            seen.update(get_run_context().__dict__)
            yield {"data": "ok"}

    monkeypatch.setattr(webapp._chat_sessions, "get_or_create", lambda sid: _Agent())
    resp = TestClient(webapp.app).post(f"/api/chat/sessions/{session_id}/messages", json={"content": "hi"})
    assert resp.status_code == 200
    assert seen["actor"] == "web:anonymous" and seen["actor_user_id"] is None and seen["actor_permissions"] == ()
    assert seen["agent_name"] == "main" and seen["chat_session_id"] == session_id
    assert seen["trace_id"] and seen["trace_id"].startswith("TRC-")


# ── CLI headless ─────────────────────────────────────────────────────────────


def test_cli_headless_sets_context(db, monkeypatch, capsys):
    from agenticops.cli import main as cli_main
    seen = {}

    def fake_agent(_content):
        seen.update(get_run_context().__dict__)
        return "done"

    monkeypatch.setattr("agenticops.agents.create_main_agent", lambda: fake_agent)
    cli_main._run_headless("hello")  # stdout is captured → non-TTY branch
    assert seen["actor"] == f"cli:{getpass.getuser()}" and seen["agent_name"] == "main"
    assert seen["trace_id"] and seen["trace_id"].startswith("TRC-")
    assert "done" in capsys.readouterr().out


@pytest.mark.parametrize("argv,module,tool_shaped,agent_name", [
    pytest.param(["run", "scan"], "agenticops.agents.scan_agent", True, "scan", id="scan"),
    pytest.param(["run", "detect"], "agenticops.agents.detect_agent", True, "detect", id="detect"),
    pytest.param(["run", "analyze", "1"], "agenticops.agents.rca_agent", False, "rca", id="analyze"),
    pytest.param(["run", "report"], "agenticops.agents.reporter_agent", False, "reporter", id="report"),
])
def test_cli_run_subcommand_sets_context(db, monkeypatch, argv, module, tool_shaped, agent_name):
    """`aiops run …` subcommands are fresh processes that start an agent directly (scan/detect via
    `_tool_func`, analyze/report by calling the agent tool) — each must set trace + cli:<user> context."""
    import importlib
    from types import SimpleNamespace
    from typer.testing import CliRunner
    from agenticops.cli import main as cli_main
    if argv[1] == "analyze":  # run_analyze looks the issue up first
        db.add(HealthIssue(title="t", description="d", severity="low", source="test", status="open", resource_id="r"))
        db.commit()
    seen = {}

    def recorder(**_kw):
        seen.update(get_run_context().__dict__)
        return "agent-ok"

    # patch the SUBMODULE attribute (`from agenticops.agents.<m> import <tool>` reads it); the package
    # re-exports the tool under the same name, so a dotted-path target would resolve to the tool object
    attr = module.rsplit(".", 1)[1]
    monkeypatch.setattr(importlib.import_module(module), attr, SimpleNamespace(_tool_func=recorder) if tool_shaped else recorder)
    res = CliRunner().invoke(cli_main.app, argv)
    assert res.exit_code == 0, res.output
    assert seen["actor"] == f"cli:{getpass.getuser()}" and seen["agent_name"] == agent_name
    assert seen["trace_id"] and seen["trace_id"].startswith("TRC-")


def test_cli_repl_slash_commands_run_under_fresh_context(db, monkeypatch, tmp_path):
    """/scan is dispatched before the main-agent turn — the per-turn trace + Run Context must already
    be set, and every turn (slash or agent) gets a fresh trace."""
    import importlib
    import logging
    from types import SimpleNamespace
    from typer.testing import CliRunner
    from agenticops.cli import main as cli_main
    from agenticops.config import get_trace_id

    turns = []

    def recorder(**_kw):
        turns.append({**get_run_context().__dict__, "trace_var": get_trace_id()})
        return "scan-ok"

    monkeypatch.setattr(importlib.import_module("agenticops.agents.scan_agent"), "scan_agent", SimpleNamespace(_tool_func=recorder))
    monkeypatch.setattr("agenticops.agents.create_main_agent", lambda: MagicMock(name="main_agent"))
    monkeypatch.setenv("HOME", str(tmp_path))  # ~/.aiops/chat_history goes to tmp

    inputs = iter(["/scan", "/scan", "exit"])

    class _FakePromptSession:
        def __init__(self, *_a, **_kw):
            pass

        def prompt(self, *_a, **_kw):
            return next(inputs)

    monkeypatch.setattr("prompt_toolkit.PromptSession", _FakePromptSession)
    root_level = logging.getLogger().level  # chat() lowers log noise process-wide; put it back
    try:
        res = CliRunner().invoke(cli_main.app, ["chat"])
    finally:
        logging.getLogger().setLevel(root_level)
    assert res.exit_code == 0, res.output
    assert len(turns) == 2
    for t in turns:
        assert t["actor"] == f"cli:{getpass.getuser()}" and t["agent_name"] == "main"
        assert t["trace_id"] and t["trace_id"].startswith("TRC-") and t["trace_var"] == t["trace_id"]
    assert turns[0]["trace_id"] != turns[1]["trace_id"], "each REPL turn gets a fresh trace"


# ── IM gateways ──────────────────────────────────────────────────────────────


def _im_service(cls):
    svc = cls.__new__(cls)
    svc._app_name = "default"
    svc._im_sessions = MagicMock()
    svc._chat_locks = defaultdict(threading.Lock)
    svc._send_reply = MagicMock()
    svc._persist_messages = MagicMock()
    return svc


@pytest.mark.parametrize("platform", ["feishu", "slack"])
def test_im_gateway_sets_and_resets_context(platform):
    if platform == "feishu":
        from agenticops.im.feishu_ws import FeishuWSService as cls
    else:
        from agenticops.im.slack_ws import SlackWSService as cls
    svc = _im_service(cls)
    seen = {}
    svc._im_sessions.get_or_create.return_value = lambda _input: seen.update(get_run_context().__dict__) or "ok"
    before = get_run_context()

    with patch("agenticops.notify.im_config.load_channels", return_value=[]):
        svc._process_and_reply("C_OPS", "hi", "1.0", "U_USER")

    assert seen["actor"] == f"im:{platform}:C_OPS" and seen["agent_name"] == "main"
    assert seen["trace_id"] and seen["trace_id"].startswith("TRC-")
    assert get_run_context() == before, "context must be reset after the turn (pooled worker thread)"


@pytest.mark.parametrize("platform", ["feishu", "slack"])
def test_im_gateway_resets_context_when_agent_raises(platform):
    """The clears (im_origin / trace id / Run Context) run in finally — a crashing turn must not leave
    its identity behind on the pooled worker thread for the next chat's turn."""
    from agenticops.config import get_im_origin, get_trace_id
    if platform == "feishu":
        from agenticops.im.feishu_ws import FeishuWSService as cls
    else:
        from agenticops.im.slack_ws import SlackWSService as cls
    svc = _im_service(cls)

    def _boom(_input):
        raise RuntimeError("agent crashed mid-turn")

    svc._im_sessions.get_or_create.return_value = _boom
    before = get_run_context()

    with patch("agenticops.notify.im_config.load_channels", return_value=[]):
        svc._process_and_reply("C_OPS", "hi", "1.0", "U_USER")  # outer handler swallows + sends the error reply

    assert get_run_context() == before, "context must be reset even when the agent raises"
    assert get_trace_id() is None and get_im_origin() is None
    svc._send_reply.assert_called_once()


# ── web manual RCA / fix-plan triggers + post-resolution thread (fix wave, I-4 + M-10) ──────────


@pytest.mark.parametrize("agent_name,target", [
    ("rca", "agenticops.agents.rca_agent.rca_agent"),
    ("sre", "agenticops.agents.sre_agent.sre_agent"),
])
def test_web_issue_agent_thread_sets_and_resets_context(db, agent_name, target):
    """The thread target behind POST /api/health-issues/{id}/rca and /generate-fix-plan sets this thread's trace
    (the issue's) and a Run Context — agent:<name> acting on behalf of the requesting web actor — and resets
    BOTH in finally."""
    import agenticops.web.app as webapp
    from agenticops.config import get_trace_id
    seen = {}

    def fake(issue_id):
        seen.update(get_run_context().__dict__)
        seen["trace_var"] = get_trace_id()
        return "ok"

    before, before_tid = get_run_context(), get_trace_id()
    with patch(target, side_effect=fake):
        webapp._run_issue_agent(agent_name, 1, "TRC-issue1", "web:anonymous")
    assert seen["actor"] == f"agent:{agent_name}" and seen["on_behalf_of"] == "web:anonymous"
    assert seen["agent_name"] == agent_name and seen["trace_id"] == "TRC-issue1" == seen["trace_var"]
    assert get_run_context() == before and get_trace_id() == before_tid, "both must be reset in finally"


def test_web_issue_agent_thread_resets_context_when_agent_raises(db):
    import agenticops.web.app as webapp
    from agenticops.config import get_trace_id
    before, before_tid = get_run_context(), get_trace_id()
    with patch("agenticops.agents.rca_agent.rca_agent", side_effect=RuntimeError("boom")):
        webapp._run_issue_agent("rca", 1, "TRC-issue1", "web:anonymous")  # logged, never raised out of the thread
    assert get_run_context() == before and get_trace_id() == before_tid


@pytest.mark.parametrize("route,target,agent_name", [
    ("/api/health-issues/{id}/rca", "agenticops.agents.rca_agent.rca_agent", "rca"),
    ("/api/health-issues/{id}/generate-fix-plan", "agenticops.agents.sre_agent.sre_agent", "sre"),
])
def test_web_issue_routes_pass_requesting_actor_and_issue_trace(db, route, target, agent_name):
    """Wiring: the route resolves the requesting actor (current_actor) and the issue's trace_id and hands both to
    the thread; the agent observes agent:<name> on behalf of that actor under that trace."""
    from starlette.testclient import TestClient
    import agenticops.web.app as webapp
    issue = HealthIssue(title="t", description="d", severity="low", source="test", status="root_cause_identified",
                        resource_id="r", trace_id="TRC-route1")
    db.add(issue); db.flush()
    db.add(RCAResult(health_issue_id=issue.id, root_cause="x", confidence=0.9))  # generate-fix-plan needs an RCA
    db.commit()
    seen, done = {}, threading.Event()

    def fake(issue_id):
        from agenticops.config import get_trace_id
        seen.update(get_run_context().__dict__)
        seen["trace_var"] = get_trace_id()
        done.set()
        return "ok"

    with patch(target, side_effect=fake):
        resp = TestClient(webapp.app).post(route.format(id=issue.id))
        assert resp.status_code == 202, resp.text
        assert done.wait(10), "agent thread did not run"
    assert seen["actor"] == f"agent:{agent_name}" and seen["on_behalf_of"] == "web:anonymous"
    assert seen["trace_id"] == "TRC-route1" == seen["trace_var"] and seen["agent_name"] == agent_name


def test_post_resolution_thread_sets_and_resets_context(db, monkeypatch):
    """M-10: the post-resolution thread runs as agent:auto-pipeline (nobody to act on behalf of) under the
    issue's trace, and resets both afterwards."""
    from types import SimpleNamespace
    from agenticops.config import get_trace_id, settings
    from agenticops.services import resolution_service
    issue = HealthIssue(title="t", description="d", severity="low", source="test", status="resolved",
                        resource_id="r", trace_id="TRC-res1")
    db.add(issue); db.commit()
    monkeypatch.setattr(settings, "skills_auto_improve_enabled", False)
    seen = {}

    def fake_rag(issue_id):
        seen.update(get_run_context().__dict__)
        seen["trace_var"] = get_trace_id()
        return SimpleNamespace(action="skip", success=True, sop_filename=None)

    before, before_tid = get_run_context(), get_trace_id()
    with patch("agenticops.pipeline.rag_pipeline.run_rag_pipeline", side_effect=fake_rag), \
         patch("agenticops.tools.kb_tools.distill_case_study", return_value="distilled"):
        resolution_service._run_post_resolution(issue.id)
    assert seen["actor"] == "agent:auto-pipeline" and seen["on_behalf_of"] is None
    assert seen["agent_name"] == "resolution" and seen["trace_id"] == "TRC-res1" == seen["trace_var"]
    assert get_run_context() == before and get_trace_id() == before_tid
