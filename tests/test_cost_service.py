# tests/test_cost_service.py
from datetime import datetime, timezone, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import agenticops.models as models
from agenticops.models import Base, AgentLog, init_db
from agenticops.services import cost_service


def _seed(monkeypatch):
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    init_db(eng)
    Session = sessionmaker(bind=eng)
    from contextlib import contextmanager
    @contextmanager
    def fake_session():
        s = Session()
        try:
            yield s; s.commit()
        finally:
            s.close()
    monkeypatch.setattr(models, "get_db_session", fake_session)
    s = Session()
    d1 = datetime(2026, 6, 20, 10, tzinfo=timezone.utc)
    d2 = datetime(2026, 6, 21, 10, tzinfo=timezone.utc)
    s.add_all([
        AgentLog(agent_name="rca", action="a", input_summary="", output_summary="",
                 input_tokens=1000, output_tokens=500, cost_usd=2.0, actor_type="user", actor_id="malibo",
                 model_id="claude-opus-4-8", created_at=d1),
        AgentLog(agent_name="sre", action="a", input_summary="", output_summary="",
                 input_tokens=2000, output_tokens=800, cost_usd=3.0, actor_type="system",
                 model_id="claude-opus-4-8", created_at=d2),
    ])
    s.commit(); s.close()


def test_cost_summary_totals_and_buckets(monkeypatch):
    _seed(monkeypatch)
    out = cost_service.cost_summary(
        start=datetime(2026, 6, 19, tzinfo=timezone.utc),
        end=datetime(2026, 6, 22, tzinfo=timezone.utc),
        bucket="day", group_by="agent",
    )
    assert round(out["totals"]["cost_usd"], 2) == 5.0
    assert out["totals"]["call_count"] == 2
    # two distinct day buckets
    buckets = {row["bucket"] for row in out["series"]}
    assert buckets == {"2026-06-20", "2026-06-21"}
    # breakdown by agent, sorted desc by cost
    assert out["breakdown"][0]["key"] == "sre"
    assert out["breakdown"][0]["cost_usd"] == 3.0


def test_cost_summary_actor_filter(monkeypatch):
    _seed(monkeypatch)
    out = cost_service.cost_summary(
        start=datetime(2026, 6, 19, tzinfo=timezone.utc),
        end=datetime(2026, 6, 22, tzinfo=timezone.utc),
        bucket="day", group_by="actor", filters={"actor_type": "user"},
    )
    assert round(out["totals"]["cost_usd"], 2) == 2.0
    assert out["breakdown"][0]["key"] == "user"


def test_cost_summary_group_by_none(monkeypatch):
    _seed(monkeypatch)
    out = cost_service.cost_summary(
        start=datetime(2026, 6, 19, tzinfo=timezone.utc),
        end=datetime(2026, 6, 22, tzinfo=timezone.utc),
        bucket="day", group_by="none",
    )
    assert round(out["totals"]["cost_usd"], 2) == 5.0          # totals unchanged
    assert len(out["breakdown"]) == 1
    assert out["breakdown"][0]["key"] == "all"
    assert round(out["breakdown"][0]["cost_usd"], 2) == 5.0
