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


def test_pipeline_auto_sre_thread_sets_context(db):
    from agenticops.services import pipeline_service
    seen = {}
    with patch("agenticops.agents.sre_agent.sre_agent", side_effect=lambda issue_id: seen.update(get_run_context().__dict__) or "ok"):
        pipeline_service._run_auto_sre(1, trace_id="TRC-y")
    assert seen["actor"] == "agent:auto-pipeline" and seen["agent_name"] == "sre"


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
