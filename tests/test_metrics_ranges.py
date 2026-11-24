"""MVP-2.9.0 N24 (the 2.8.0 spec's S7): the Agent metrics page has ONE range — 7, 30 or 90 days — that every module
follows. Each endpoint must take it, and must refuse a range it does not know instead of answering another one."""
import inspect
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from agenticops.web.app import app

FAKE = {"totals": {"cost_usd": 0}, "series": [], "breakdown": []}


@pytest.fixture
def client(tmp_path, monkeypatch):
    import agenticops.models as models_mod
    from agenticops.config import settings
    monkeypatch.setattr(models_mod, "_engine", None)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/metrics.db")
    models_mod.init_db()
    yield TestClient(app)


@pytest.mark.parametrize("period,days", [("7d", 7), ("30d", 30), ("90d", 90)])
def test_cost_takes_each_range_of_the_page(period, days):
    with patch("agenticops.services.cost_service.cost_summary", return_value=FAKE) as mock:
        r = TestClient(app).get(f"/api/cost/summary?period={period}")
    assert r.status_code == 200
    kw = mock.call_args.kwargs
    assert kw["end"] - kw["start"] == timedelta(days=days) and kw["bucket"] == "day"


def test_cost_refuses_a_range_it_does_not_know():
    """It used to answer the last 30 days under whatever name it was asked for."""
    with patch("agenticops.services.cost_service.cost_summary", return_value=FAKE) as mock:
        r = TestClient(app).get("/api/cost/summary?period=14d")
    assert r.status_code == 422 and mock.call_count == 0


def _log(session, agent, hours_ago, tokens=100):
    from agenticops.models import AgentLog
    session.add(AgentLog(agent_name=agent, action="run", input_summary="", output_summary="", status="success", input_tokens=tokens, output_tokens=1,
                         created_at=datetime.now(timezone.utc) - timedelta(hours=hours_ago)))


def test_the_token_summary_reaches_ninety_days(client):
    from agenticops.models import get_db_session
    with get_db_session() as s:
        _log(s, "main", 2)
        _log(s, "rca", 24 * 40)
        _log(s, "sre", 24 * 95)                                              # outside every range of the page
    day = client.get("/api/agent-logs/summary?hours=24").json()
    assert set(day["per_agent"]) == {"main"}
    all90 = client.get(f"/api/agent-logs/summary?hours={24 * 90}")
    assert all90.status_code == 200 and set(all90.json()["per_agent"]) == {"main", "rca"}
    assert client.get(f"/api/agent-logs/summary?hours={24 * 90 + 1}").status_code == 422
    assert client.get("/api/agent-logs/summary?hours=0").status_code == 422


def test_the_metric_handlers_are_plain_functions():
    """One process: a blocking database read never runs inside an `async def` handler."""
    from agenticops.web import app as app_mod
    from agenticops.web.routers import agent_logs, cost
    for fn in (cost.api_cost_summary, agent_logs.api_agent_log_summary, app_mod.api_rca_location_stats):
        assert not inspect.iscoroutinefunction(fn), fn.__name__
