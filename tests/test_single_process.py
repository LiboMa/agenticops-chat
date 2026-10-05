# tests/test_single_process.py
"""AgenticOps runs as ONE process (MVP-2.7.0 S1c), so nothing may hold its event loop.

Chat and IM agents, the connector / Galaxy / intake locks and runtime settings live in the process's memory,
so every deployment runs a single uvicorn worker; a second process on the same data_dir is reported. With
one process, a blocking call inside an `async def` handler would stall every other request — SSE streams
included — so slow network work runs off the loop."""
import asyncio
import inspect
import logging
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest

from agenticops.models import Base

ROOT = Path(__file__).resolve().parents[1]
SLOW = 1.0


@pytest.fixture
def app_db(tmp_path, monkeypatch):
    import agenticops.models as models_mod
    from agenticops.config import settings
    monkeypatch.setattr(models_mod, "_engine", None)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/sp.db")
    monkeypatch.setattr(settings, "api_auth_enabled", False)
    Base.metadata.create_all(models_mod.get_engine())
    from agenticops.web.app import app
    return app


async def _second_request_waits(app, slow_call, fast=("GET", "/api/chat/sessions")) -> float:
    """Seconds the fast request took while slow_call (a coroutine factory on the same client) was running."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        start = time.monotonic()  # before the slow request starts: a blocked loop delays even the sleep below
        slow = asyncio.create_task(slow_call(client))
        await asyncio.sleep(0.05)  # the slow request is inside its handler now
        r = await client.request(*fast)
        took = time.monotonic() - start
        assert r.status_code == 200, r.text
        await slow
        return took


def test_a_slow_sts_call_in_health_does_not_hold_other_requests(app_db):
    def slow_identity():
        time.sleep(SLOW)
        return {"Account": "123456789012"}
    fake = SimpleNamespace(client=lambda name: SimpleNamespace(get_caller_identity=slow_identity))
    with patch("agenticops.config.get_bedrock_boto_session", return_value=fake):
        took = asyncio.run(_second_request_waits(app_db, lambda c: c.get("/api/health")))
    assert took < SLOW / 2


def test_a_slow_alert_judgement_does_not_hold_other_requests(app_db, monkeypatch):
    from agenticops.config import settings
    from agenticops.integrations.alert_processor import AlertProcessResult
    monkeypatch.setattr(settings, "alert_pipeline_mode", "both")
    monkeypatch.setattr(settings, "webhook_secret", "")

    def slow_process(alert, trace_id=None):
        time.sleep(SLOW)  # the Signal Gate's L2 Bedrock judge, under its lock
        return AlertProcessResult(action="created", health_issue_id=1, message="ok")
    payload = {"alerts": [{"labels": {"alertname": "HighCPU", "instance": "i-0abc"}, "status": "firing"}]}
    with patch("agenticops.integrations.alert_processor.process_alert", side_effect=slow_process):
        took = asyncio.run(_second_request_waits(
            app_db, lambda c: c.post("/api/webhooks/alert/prometheus", json=payload)))
    assert took < SLOW / 2


def test_an_im_agent_turn_runs_off_the_event_loop(app_db):
    """The IM callbacks schedule _handle_im_message with ensure_future; it used to call agent(...) inline."""
    from agenticops.web import app as app_mod

    def slow_agent(_text):
        time.sleep(SLOW)
        return "done"
    sessions = SimpleNamespace(get_or_create=lambda *a: slow_agent, get_notifier=lambda *a: None)
    msg = SimpleNamespace(content="why is web down", chat_id="oc_1", app_name="bot", sender_id="u1")

    async def scenario():
        start = time.monotonic()
        task = asyncio.create_task(app_mod._handle_im_message("feishu", msg))
        await asyncio.sleep(0.05)  # resumes on time only if the handler's turn is off the loop
        waited = time.monotonic() - start
        await task
        return waited
    with patch.object(app_mod, "_get_im_sessions", return_value=sessions):
        assert asyncio.run(scenario()) < SLOW / 2


@pytest.mark.parametrize("module,names", [
    ("agenticops.web.app", ["api_health", "api_create_health_issue", "api_run_rag_pipeline", "api_generate_report",
                            "api_get_settings"]),
    ("agenticops.web.routers.skills", ["api_generate_skill"]),
    ("agenticops.web.routers.accounts", ["api_test_account_connection"]),
    ("agenticops.web.routers.changes", ["api_create_change", "api_approve_change", "api_execute_change",
                                        "api_get_change", "api_review_change"]),
    ("agenticops.graph.api", ["get_region_graph", "get_vpc_graph", "get_multi_region_graph", "get_spof"]),
])
def test_handlers_that_do_blocking_work_run_in_the_threadpool(module, names):
    """A plain `def` handler runs in FastAPI's threadpool; these call AWS, Bedrock or the agents synchronously."""
    import importlib
    mod = importlib.import_module(module)
    assert [n for n in names if inspect.iscoroutinefunction(getattr(mod, n))] == []


def test_a_second_process_on_the_same_data_dir_is_reported(tmp_path, monkeypatch, caplog):
    from agenticops.config import settings
    from agenticops.web import app as app_mod
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    first = app_mod._acquire_instance_lock()
    try:
        assert first is not None
        with caplog.at_level(logging.ERROR, logger="agenticops.web.app"):
            assert app_mod._acquire_instance_lock() is None  # a second open file = a second process
        assert "run ONE process" in caplog.text
    finally:
        first.close()
    again = app_mod._acquire_instance_lock()
    assert again is not None
    again.close()


def test_the_default_executor_is_sized_from_settings(monkeypatch):
    from agenticops.config import settings
    from agenticops.web import app as app_mod
    monkeypatch.setattr(settings, "event_loop_executor_threads", 48)
    loop = asyncio.new_event_loop()
    try:
        app_mod._size_default_executor(loop)
        assert loop._default_executor._max_workers == 48
    finally:
        loop.close()


def test_the_settings_file_sets_the_executor_size():
    import yaml
    assert int(yaml.safe_load((ROOT / "config/settings.yaml").read_text())["event_loop_executor_threads"]) >= 16


@pytest.mark.parametrize("path", ["docker/Dockerfile", "iac/deploy-sg/user_data.sh", "iac/deploy-sg/deploy.sh"])
def test_every_deployment_runs_one_worker(path):
    text = (ROOT / path).read_text()
    assert "--workers 4" not in text and '"--workers", "4"' not in text
    assert "--workers 1" in text or '"--workers", "1"' in text


def test_the_scheduler_worker_override_is_gone():
    """AIOPS_SCHEDULER_WORKER forced the scheduler on in every worker (and crashed shutdown); the instance lock
    is now the only election."""
    assert "AIOPS_SCHEDULER_WORKER" not in (ROOT / "src/agenticops/web/app.py").read_text()


def test_listing_bedrock_models_never_runs_on_the_event_loop():
    """_allowed_model_ids() may list Bedrock models synchronously; the two async handlers that need it (PATCH
    /api/settings, PATCH /api/chat/sessions/{id}) run it in a thread (MVP-2.7.0 S2)."""
    src = (ROOT / "src/agenticops/web/app.py").read_text()
    assert src.count("await asyncio.to_thread(_allowed_model_ids)") == 2
    import re
    assert re.findall(r"(?<!def )_allowed_model_ids\(\)", src) == []  # no direct call left (the def is fine)
