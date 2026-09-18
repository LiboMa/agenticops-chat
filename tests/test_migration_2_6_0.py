"""init_db must migrate a pre-2.6.0 SQLite database in place: NOT NULL → NULL on the three
plan-lineage tables, new columns, CHECK constraint, indexes rebuilt, rows preserved, idempotent."""
import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text

OLD_SCHEMA = """
CREATE TABLE cloud_accounts (id INTEGER PRIMARY KEY, name VARCHAR(100), provider VARCHAR(20), is_enabled BOOLEAN,
  credential_source_type VARCHAR(20), credentials JSON, regions JSON, labels JSON, created_at DATETIME, last_scanned_at DATETIME);
CREATE TABLE health_issues (id INTEGER PRIMARY KEY, title VARCHAR(300), description TEXT, severity VARCHAR(20),
  source VARCHAR(50), status VARCHAR(30), resource_id VARCHAR(500), trace_id VARCHAR(20), account_id INTEGER);
CREATE TABLE rca_results (id INTEGER PRIMARY KEY, health_issue_id INTEGER NOT NULL, root_cause TEXT, confidence FLOAT);
CREATE TABLE fix_plans (
  id INTEGER NOT NULL PRIMARY KEY, health_issue_id INTEGER NOT NULL, rca_result_id INTEGER NOT NULL,
  risk_level VARCHAR(20) NOT NULL, title VARCHAR(300) NOT NULL, summary TEXT NOT NULL, steps JSON NOT NULL, rollback_plan JSON NOT NULL,
  estimated_impact TEXT NOT NULL, pre_checks JSON NOT NULL, post_checks JSON NOT NULL, status VARCHAR(30) NOT NULL,
  approved_by VARCHAR(100), approved_at DATETIME, created_at DATETIME NOT NULL,
  FOREIGN KEY(health_issue_id) REFERENCES health_issues (id), FOREIGN KEY(rca_result_id) REFERENCES rca_results (id));
CREATE TABLE fix_executions (
  id INTEGER NOT NULL PRIMARY KEY, fix_plan_id INTEGER NOT NULL, health_issue_id INTEGER NOT NULL, status VARCHAR(30) NOT NULL,
  started_at DATETIME, completed_at DATETIME, executed_by VARCHAR(100) NOT NULL, pre_check_results JSON NOT NULL, step_results JSON NOT NULL,
  post_check_results JSON NOT NULL, rollback_results JSON NOT NULL, error_message TEXT, duration_ms INTEGER NOT NULL, created_at DATETIME NOT NULL,
  FOREIGN KEY(fix_plan_id) REFERENCES fix_plans (id), FOREIGN KEY(health_issue_id) REFERENCES health_issues (id));
CREATE INDEX idx_fix_exec_status ON fix_executions (status);
CREATE INDEX idx_fix_exec_plan ON fix_executions (fix_plan_id);
CREATE TABLE pipeline_events (
  id INTEGER NOT NULL PRIMARY KEY, health_issue_id INTEGER NOT NULL, event_type VARCHAR(50) NOT NULL, stage VARCHAR(30) NOT NULL,
  status VARCHAR(20) NOT NULL, detail TEXT, actor VARCHAR(100) NOT NULL, duration_ms INTEGER, created_at DATETIME NOT NULL,
  trace_id VARCHAR(20));
CREATE INDEX idx_pipeline_event_issue ON pipeline_events (health_issue_id);
CREATE INDEX idx_pipeline_event_time ON pipeline_events (created_at);
CREATE INDEX ix_pipeline_events_health_issue_id ON pipeline_events (health_issue_id);
CREATE INDEX ix_pipeline_events_trace_id ON pipeline_events (trace_id);
INSERT INTO health_issues (id, title, description, severity, source, status, resource_id) VALUES (1, 'i', 'd', 'low', 'test', 'fix_planned', 'r');
INSERT INTO rca_results (id, health_issue_id, root_cause, confidence) VALUES (1, 1, 'rc', 0.9);
INSERT INTO fix_plans (id, health_issue_id, rca_result_id, risk_level, title, summary, steps, rollback_plan, estimated_impact,
  pre_checks, post_checks, status, approved_by, created_at)
  VALUES (7, 1, 1, 'L1', 'old plan', 'sum', '[]', '{}', '', '[]', '[]', 'approved', 'web-user', '2026-01-01 00:00:00');
INSERT INTO fix_executions (id, fix_plan_id, health_issue_id, status, executed_by, pre_check_results, step_results,
  post_check_results, rollback_results, duration_ms, created_at)
  VALUES (3, 7, 1, 'succeeded', 'executor_agent', '[]', '[]', '[]', '[]', 10, '2026-01-01 00:00:00');
INSERT INTO pipeline_events (id, health_issue_id, event_type, stage, status, actor, created_at)
  VALUES (5, 1, 'fix_approved', 'approval', 'completed', 'system', '2026-01-01 00:00:00');
"""


@pytest.fixture(autouse=True)
def _restore_engine_singleton():
    """_run_init_db repoints the process-wide engine at a tmp DB; put it back for the rest of the suite."""
    import agenticops.models as models_mod
    from agenticops.config import settings

    saved_url = settings.database_url
    yield
    settings.database_url = saved_url
    models_mod._engine = None


@pytest.fixture
def old_db(tmp_path):
    path = tmp_path / "agenticops.db"
    con = sqlite3.connect(path)
    con.executescript(OLD_SCHEMA)
    con.commit()
    con.close()
    return path


def _notnull(engine, table):
    with engine.connect() as c:
        rows = c.execute(text(f"PRAGMA table_info({table})")).fetchall()
    return {r[1]: bool(r[3]) for r in rows}


def _table_sql(engine, table):
    with engine.connect() as c:
        return c.execute(text("SELECT sql FROM sqlite_master WHERE type='table' AND name=:n"), {"n": table}).scalar()


def _run_init_db(path):
    import agenticops.models as models_mod
    from agenticops.config import settings
    models_mod._engine = None
    settings.database_url = f"sqlite:///{path}"
    engine = models_mod.get_engine()
    models_mod.init_db(engine)
    return engine


def test_migration_relaxes_not_null_and_adds_columns(old_db):
    engine = _run_init_db(old_db)
    fp = _notnull(engine, "fix_plans")
    assert fp["health_issue_id"] is False and fp["rca_result_id"] is False
    for col in ("plan_kind", "change_request_id", "rejected_by", "rejected_at", "rejection_reason", "updated_at"):
        assert col in fp
    assert _notnull(engine, "fix_executions")["health_issue_id"] is False
    pe = _notnull(engine, "pipeline_events")
    assert pe["health_issue_id"] is False and "change_request_id" in pe
    assert "ck_fix_plans_origin" in _table_sql(engine, "fix_plans")


def test_migration_preserves_rows_and_defaults_plan_kind(old_db):
    engine = _run_init_db(old_db)
    with engine.connect() as c:
        row = c.execute(text("SELECT id, health_issue_id, rca_result_id, status, approved_by, plan_kind FROM fix_plans")).one()
        assert tuple(row) == (7, 1, 1, "approved", "web-user", "fix")
        assert c.execute(text("SELECT COUNT(*) FROM fix_executions")).scalar() == 1
        assert c.execute(text("SELECT id, health_issue_id FROM pipeline_events")).one()[1] == 1


def test_migration_rebuilds_indexes(old_db):
    engine = _run_init_db(old_db)
    names = {ix["name"] for ix in inspect(engine).get_indexes("fix_executions")}
    assert {"idx_fix_exec_status", "idx_fix_exec_plan"} <= names
    names = {ix["name"] for ix in inspect(engine).get_indexes("pipeline_events")}
    assert {"idx_pipeline_event_issue", "idx_pipeline_event_change", "idx_pipeline_event_time"} <= names


def test_migration_creates_backup_and_is_idempotent(old_db):
    engine = _run_init_db(old_db)
    bak = Path(str(old_db) + ".bak-pre-2.6.0")
    assert bak.exists()
    before = {t: _table_sql(engine, t) for t in ("fix_plans", "fix_executions", "pipeline_events")}
    import agenticops.models as models_mod
    models_mod.init_db(engine)  # second run: no rebuild, no error
    after = {t: _table_sql(engine, t) for t in ("fix_plans", "fix_executions", "pipeline_events")}
    assert before == after


def test_fresh_database_needs_no_rebuild(tmp_path):
    engine = _run_init_db(tmp_path / "fresh.db")
    assert not Path(str(tmp_path / "fresh.db") + ".bak-pre-2.6.0").exists()
    assert _notnull(engine, "fix_plans")["health_issue_id"] is False


def test_add_column_ddl_types_follow_dialect():
    """ADD COLUMN types come from the ORM column compiled for the target dialect — never a
    hard-coded DATETIME, which PostgreSQL rejects (type "datetime" does not exist)."""
    from sqlalchemy.dialects import postgresql, sqlite

    import agenticops.audit.models  # noqa: F401 — registers audit_logs
    from agenticops.models import _ADD_COLUMNS_2_6_0, _add_column_ddl

    assert _add_column_ddl(sqlite.dialect(), "fix_plans", "updated_at", None) == "updated_at DATETIME"
    assert _add_column_ddl(postgresql.dialect(), "fix_plans", "updated_at", None) == "updated_at TIMESTAMP WITHOUT TIME ZONE"
    assert _add_column_ddl(postgresql.dialect(), "fix_plans", "plan_kind", "DEFAULT 'fix'") == "plan_kind VARCHAR(10) DEFAULT 'fix'"
    for tbl, cols in _ADD_COLUMNS_2_6_0.items():
        for col, extra in cols.items():
            assert "DATETIME" not in _add_column_ddl(postgresql.dialect(), tbl, col, extra)
