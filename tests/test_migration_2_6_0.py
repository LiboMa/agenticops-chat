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


def test_migration_adds_review_attempt_to_an_existing_change_requests_table(tmp_path):
    """A dev database on which the earlier 2.6.0 code already created change_requests gains the
    round-2 column in place; existing rows read 0 (SQLite allows NOT NULL here because of DEFAULT 0)."""
    path = tmp_path / "agenticops.db"
    con = sqlite3.connect(path)
    con.executescript(
        "CREATE TABLE change_requests (id INTEGER PRIMARY KEY, title VARCHAR(300), status VARCHAR(30),"
        " created_at DATETIME);"
        "INSERT INTO change_requests (id, title, status, created_at)"
        " VALUES (4, 'old cr', 'under_review', '2026-01-01 00:00:00');"
    )
    con.commit()
    con.close()
    engine = _run_init_db(path)
    assert _notnull(engine, "change_requests")["review_attempt"] is True
    with engine.connect() as c:
        assert tuple(c.execute(text("SELECT id, review_attempt FROM change_requests")).one()) == (4, 0)


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


# ── Final fix wave, group 2 (I-2 + M-2 + M-3 + M-8 + M-12) ────────────────────────────────────────────

import re

_MIGRATION_DDL = re.compile(
    r"ALTER TABLE|__new|UPDATE fix_plans|idx_fix_plan_kind|idx_fix_plan_change_request|idx_pipeline_event_change"
    r"|ix_audit_logs_actor|ck_fix_plans_origin",
    re.I,
)


def _spy_statements(engine, fn):
    from sqlalchemy import event
    seen: list[str] = []

    def spy(conn, cursor, statement, parameters, context, executemany):
        seen.append(statement)

    event.listen(engine, "before_cursor_execute", spy)
    try:
        fn()
    finally:
        event.remove(engine, "before_cursor_execute", spy)
    return seen


def test_migration_runs_once_per_process_per_database(old_db):
    """I-2: init_db() is a runtime hot path (audit writes, scheduler, ~47 CLI sites). The 2.6.0 pass must run
    once per process per database URL — a second init_db() on the same URL issues none of its DDL/DML."""
    import agenticops.models as models_mod
    engine = _run_init_db(old_db)
    assert _notnull(engine, "fix_plans")["health_issue_id"] is False  # the first call did migrate
    second = _spy_statements(engine, lambda: models_mod.init_db(engine))
    assert [s for s in second if _MIGRATION_DDL.search(s)] == []


def test_migration_still_runs_for_a_second_database_in_the_same_process(tmp_path):
    """The once-per-process guard is keyed by URL: two pre-2.6.0 files migrate independently."""
    a, b = tmp_path / "a" / "agenticops.db", tmp_path / "b" / "agenticops.db"
    for path in (a, b):
        path.parent.mkdir()
        con = sqlite3.connect(path)
        con.executescript(OLD_SCHEMA)
        con.commit()
        con.close()
    for path in (a, b):
        engine = _run_init_db(path)
        assert _notnull(engine, "fix_plans")["health_issue_id"] is False
        assert Path(str(path) + ".bak-pre-2.6.0").exists()


def test_backup_is_a_pre_migration_snapshot_published_atomically(old_db):
    """M-8: the backup is an online sqlite3 backup (consistent snapshot) of the PRE-rebuild file, written to a
    temp name in the same directory and published with os.replace — no torn copy, no temp leftovers."""
    _run_init_db(old_db)
    bak = Path(str(old_db) + ".bak-pre-2.6.0")
    assert bak.exists()
    con = sqlite3.connect(bak)
    try:
        assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        cols = {r[1]: bool(r[3]) for r in con.execute("PRAGMA table_info(fix_plans)")}
        assert cols["health_issue_id"] is True and "plan_kind" not in cols  # the old schema: taken before the rebuild
        assert con.execute("SELECT COUNT(*) FROM fix_plans").fetchone()[0] == 1
    finally:
        con.close()
    assert [p.name for p in old_db.parent.iterdir() if p.name.startswith(".bak-pre-2.6.0")] == []


def test_backup_helper_skips_when_backup_exists(old_db):
    import agenticops.models as models_mod
    bak = Path(str(old_db) + ".bak-pre-2.6.0")
    bak.write_bytes(b"keep me")
    engine = create_engine(f"sqlite:///{old_db}")
    assert models_mod._backup_sqlite_file(engine) == str(bak)
    assert bak.read_bytes() == b"keep me"


class _StubInspector:
    """Stand-in for sqlalchemy.inspect(engine): {table: [{"name","nullable","type"}]} plus FKs and indexes."""

    def __init__(self, columns, foreign_keys, indexes):
        self.columns, self.foreign_keys, self.indexes = columns, foreign_keys, indexes

    def has_table(self, name):
        return name in self.columns

    def get_columns(self, name):
        return self.columns[name]

    def get_foreign_keys(self, name):
        return self.foreign_keys.get(name, [])

    def get_indexes(self, name):
        return self.indexes.get(name, [])


_PG_TABLES = ("fix_plans", "fix_executions", "pipeline_events", "audit_logs", "change_requests", "command_audits")


def _orm_shaped_stub():
    """A catalog that looks exactly like create_all on the current ORM (i.e. fully migrated)."""
    import agenticops.audit.models  # noqa: F401
    from agenticops.models import Base
    cols, fks, idxs = {}, {}, {}
    for name in _PG_TABLES:
        t = Base.metadata.tables[name]
        cols[name] = [{"name": c.name, "nullable": c.nullable, "type": c.type} for c in t.columns]
        fks[name] = [{"constrained_columns": [fk.parent.name]} for fk in t.foreign_keys]
        idxs[name] = [{"name": ix.name} for ix in t.indexes]
    return cols, fks, idxs


def _drop_column(cols, table, name):
    cols[table] = [c for c in cols[table] if c["name"] != name]


def _set_column(cols, table, name, **fields):
    for c in cols[table]:
        if c["name"] == name:
            c.update(fields)


def _pre_2_6_0_stub():
    """What a 2.5.0 PostgreSQL database looks like after create_all added the NEW tables (change_requests,
    command_audits) but before any 2.6.0 ALTER: NOT NULL lineage columns, no new columns, VARCHAR(100) actors."""
    from sqlalchemy import String
    cols, fks, idxs = _orm_shaped_stub()
    for table, names in (("fix_plans", ("health_issue_id", "rca_result_id")), ("fix_executions", ("health_issue_id",)),
                         ("pipeline_events", ("health_issue_id",))):
        for n in names:
            _set_column(cols, table, n, nullable=False)
    for n in ("plan_kind", "change_request_id", "rejected_by", "rejected_at", "rejection_reason", "updated_at"):
        _drop_column(cols, "fix_plans", n)
    _drop_column(cols, "pipeline_events", "change_request_id")
    _drop_column(cols, "audit_logs", "actor")
    _drop_column(cols, "change_requests", "review_attempt")
    _set_column(cols, "fix_plans", "approved_by", type=String(100))
    _set_column(cols, "fix_executions", "executed_by", type=String(100))
    fks["fix_plans"] = [fk for fk in fks["fix_plans"] if fk["constrained_columns"] != ["change_request_id"]]
    gone = {"idx_fix_plan_kind", "idx_fix_plan_change_request", "idx_pipeline_event_change", "ix_audit_logs_actor"}
    idxs = {t: [ix for ix in lst if ix["name"] not in gone] for t, lst in idxs.items()}
    return cols, fks, idxs


def test_pg_statements_for_a_pre_2_6_0_catalog():
    from sqlalchemy.dialects import postgresql
    from agenticops.models import _add_column_ddl, _pg_migration_statements
    pg = postgresql.dialect()
    stmts = _pg_migration_statements(_StubInspector(*_pre_2_6_0_stub()), pg, existing_constraints=set())
    add = lambda tbl, col, extra=None: f"ALTER TABLE {tbl} ADD COLUMN IF NOT EXISTS {_add_column_ddl(pg, tbl, col, extra)}"
    assert stmts == [
        "ALTER TABLE fix_plans ALTER COLUMN health_issue_id DROP NOT NULL",
        "ALTER TABLE fix_plans ALTER COLUMN rca_result_id DROP NOT NULL",
        "ALTER TABLE fix_executions ALTER COLUMN health_issue_id DROP NOT NULL",
        "ALTER TABLE pipeline_events ALTER COLUMN health_issue_id DROP NOT NULL",
        add("fix_plans", "plan_kind", "DEFAULT 'fix'"),
        add("fix_plans", "change_request_id"),
        add("fix_plans", "rejected_by"),
        add("fix_plans", "rejected_at"),
        add("fix_plans", "rejection_reason"),
        add("fix_plans", "updated_at"),
        add("pipeline_events", "change_request_id"),
        add("audit_logs", "actor"),
        add("change_requests", "review_attempt", "DEFAULT 0 NOT NULL"),
        "UPDATE fix_plans SET plan_kind = 'fix' WHERE plan_kind IS NULL",
        "ALTER TABLE fix_plans ALTER COLUMN plan_kind SET NOT NULL",
        "ALTER TABLE fix_plans ADD CONSTRAINT fix_plans_change_request_id_fkey "
        "FOREIGN KEY (change_request_id) REFERENCES change_requests (id)",
        "ALTER TABLE fix_plans ADD CONSTRAINT ck_fix_plans_origin CHECK ("
        "(plan_kind = 'fix' AND health_issue_id IS NOT NULL AND rca_result_id IS NOT NULL AND change_request_id IS NULL) OR "
        "(plan_kind = 'change' AND change_request_id IS NOT NULL AND health_issue_id IS NULL AND rca_result_id IS NULL))",
        "ALTER TABLE fix_plans ALTER COLUMN approved_by TYPE VARCHAR(255)",
        "ALTER TABLE fix_executions ALTER COLUMN executed_by TYPE VARCHAR(255)",
        "CREATE INDEX IF NOT EXISTS idx_fix_plan_kind ON fix_plans(plan_kind)",
        "CREATE INDEX IF NOT EXISTS idx_fix_plan_change_request ON fix_plans(change_request_id)",
        "CREATE INDEX IF NOT EXISTS idx_pipeline_event_change ON pipeline_events(change_request_id)",
        "CREATE INDEX IF NOT EXISTS ix_audit_logs_actor ON audit_logs(actor)",
    ]
    assert not any("DATETIME" in s for s in stmts)
    assert "rejected_by VARCHAR(255)" in add("fix_plans", "rejected_by")  # new columns are born 255 wide


def test_pg_statements_for_a_fully_migrated_catalog_are_empty():
    """A catalog identical to create_all on the current ORM gets NO statement — no ACCESS EXCLUSIVE locks."""
    from sqlalchemy.dialects import postgresql
    from agenticops.models import _pg_migration_statements
    stmts = _pg_migration_statements(_StubInspector(*_orm_shaped_stub()), postgresql.dialect(),
                                     existing_constraints={"ck_fix_plans_origin", "fix_plans_change_request_id_fkey"})
    assert stmts == []


def test_pg_statements_for_an_early_2_6_0_catalog_complete_it():
    """M-2 / M-3: a database migrated by the earlier 2.6.0 build has nullable plan_kind, no FK on
    change_request_id, VARCHAR(100) actor keys and no review_attempt (the fix-round-2 column) —
    exactly those are finished, nothing else is touched."""
    from sqlalchemy import String
    from sqlalchemy.dialects import postgresql
    from agenticops.models import _ACTOR_KEY_COLUMNS_2_6_0, _add_column_ddl, _pg_migration_statements
    pg = postgresql.dialect()
    cols, fks, idxs = _orm_shaped_stub()
    _set_column(cols, "fix_plans", "plan_kind", nullable=True)
    _drop_column(cols, "change_requests", "review_attempt")  # the early build created the table without it
    fks["fix_plans"] = [fk for fk in fks["fix_plans"] if fk["constrained_columns"] != ["change_request_id"]]
    for table, names in _ACTOR_KEY_COLUMNS_2_6_0.items():
        for n in names:
            _set_column(cols, table, n, type=String(100))
    stmts = _pg_migration_statements(_StubInspector(cols, fks, idxs), pg,
                                     existing_constraints={"ck_fix_plans_origin"})
    add = lambda tbl, col, extra=None: f"ALTER TABLE {tbl} ADD COLUMN IF NOT EXISTS {_add_column_ddl(pg, tbl, col, extra)}"
    widen = [f"ALTER TABLE {t} ALTER COLUMN {c} TYPE VARCHAR(255)" for t, names in _ACTOR_KEY_COLUMNS_2_6_0.items() for c in names]
    assert stmts == [
        add("change_requests", "review_attempt", "DEFAULT 0 NOT NULL"),
        "UPDATE fix_plans SET plan_kind = 'fix' WHERE plan_kind IS NULL",
        "ALTER TABLE fix_plans ALTER COLUMN plan_kind SET NOT NULL",
        "ALTER TABLE fix_plans ADD CONSTRAINT fix_plans_change_request_id_fkey "
        "FOREIGN KEY (change_request_id) REFERENCES change_requests (id)",
        *widen,
    ]
    assert len(widen) == 10


def test_actor_key_columns_are_255_wide():
    """M-2: actor keys are `user:<email>` and users.email is String(255); every actor-key column matches."""
    import agenticops.audit.models  # noqa: F401
    from agenticops.models import Base, _ACTOR_KEY_COLUMNS_2_6_0
    assert _ACTOR_KEY_COLUMNS_2_6_0 == {
        "fix_plans": ("approved_by", "rejected_by"),
        "fix_executions": ("executed_by",),
        "change_requests": ("requested_by", "reviewed_by", "approved_by", "rejected_by"),
        "command_audits": ("actor", "on_behalf_of"),
        "audit_logs": ("actor",),
    }
    for table, names in _ACTOR_KEY_COLUMNS_2_6_0.items():
        for n in names:
            assert Base.metadata.tables[table].c[n].type.length == 255, (table, n)
