"""GET /api/schedules says each schedule's latest REAL run (MVP-2.8.0 S1): the newest schedule_executions row, never a
state inferred from is_enabled / last_run_at. A schedule that never ran has no last_execution."""
import inspect
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import agenticops.web.app  # noqa: F401 — imported at collection (the auth middleware is added only when auth is on at import)


@pytest.fixture
def client(tmp_path, monkeypatch):
    import agenticops.models as models_mod
    import agenticops.scheduler.scheduler  # noqa: F401 — registers schedules / schedule_executions on Base
    from agenticops.config import settings
    from agenticops.web.app import app
    monkeypatch.setattr(models_mod, "_engine", None)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/sched.db")
    models_mod.init_db()
    return TestClient(app)


def _schedule(name, **kw):
    from agenticops.models import get_db_session
    from agenticops.scheduler.scheduler import Schedule
    with get_db_session() as s:
        row = Schedule(name=name, pipeline_name="HealthPatrol", cron_expression=kw.pop("cron", "0 * * * *"), **kw)
        s.add(row)
        s.flush()
        return row.id


def _execution(schedule_id, status, minutes_ago, error=None, completed=True):
    from agenticops.models import get_db_session
    from agenticops.scheduler.scheduler import ScheduleExecution
    started = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    with get_db_session() as s:
        row = ScheduleExecution(schedule_id=schedule_id, status=status, started_at=started,
                                completed_at=started + timedelta(seconds=40) if completed else None,
                                duration_ms=40000 if completed else None, result={}, error=error)
        s.add(row)
        s.flush()
        return row.id


def _row(client, schedule_id):
    rows = client.get("/api/schedules").json()
    return next(r for r in rows if r["id"] == schedule_id)


def test_a_schedule_that_never_ran_has_no_last_execution(client):
    sid = _schedule("never-ran", cron="@once", schedule_type="one_time", is_enabled=True)
    assert _row(client, sid)["last_execution"] is None


def test_the_newest_run_is_the_last_execution(client):
    sid = _schedule("three-runs")
    _execution(sid, "completed", 120)
    _execution(sid, "failed", 60, error="boom")
    newest = _execution(sid, "completed", 5)
    last = _row(client, sid)["last_execution"]
    assert last["id"] == newest and last["status"] == "completed"
    assert last["duration_ms"] == 40000 and last["error_summary"] is None
    assert last["started_at"] and last["completed_at"]


def test_a_long_error_is_summarised_to_200_characters(client):
    sid = _schedule("long-error")
    _execution(sid, "failed", 1, error="x" * 300)
    assert _row(client, sid)["last_execution"]["error_summary"] == "x" * 200


def test_a_running_run_is_returned_as_it_is(client):
    sid = _schedule("still-running")
    _execution(sid, "completed", 90)
    running = _execution(sid, "running", 1, completed=False)
    last = _row(client, sid)["last_execution"]
    assert last["id"] == running and last["status"] == "running" and last["completed_at"] is None


def test_each_schedule_gets_its_own_latest_run(client):
    a, b = _schedule("a"), _schedule("b")
    ra = _execution(a, "completed", 10)
    rb = _execution(b, "failed", 20, error="nope")
    assert _row(client, a)["last_execution"]["id"] == ra
    assert _row(client, b)["last_execution"]["id"] == rb


def test_the_list_handler_is_plain_def():
    """A DB read in an async def blocks the one event loop (MVP-2.7.0 S1)."""
    from agenticops.web.routers.schedules import api_list_schedules
    assert not inspect.iscoroutinefunction(api_list_schedules)
