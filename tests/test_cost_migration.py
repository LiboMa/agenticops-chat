# tests/test_cost_migration.py
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from agenticops.models import Base, AgentLog, init_db


def test_agent_log_has_cost_actor_columns():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    init_db(eng)
    cols = {c["name"] for c in inspect(eng).get_columns("agent_logs")}
    assert {"cache_write_tokens", "cost_usd", "actor_type", "actor_id"} <= cols
    chat_cols = {c["name"] for c in inspect(eng).get_columns("chat_messages")}
    assert "trace_id" in chat_cols


def test_agent_log_defaults():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    init_db(eng)
    s = sessionmaker(bind=eng)()
    row = AgentLog(agent_name="rca", action="x", input_summary="", output_summary="")
    s.add(row); s.commit(); s.refresh(row)
    assert row.cost_usd == 0.0
    assert row.actor_type == "system"
    assert row.cache_write_tokens == 0
