"""init_db adds the MVP-2.6.1 graph-anchoring, RCA-location and plan-identity columns to an existing database in place:
rows preserved, indexes added, idempotent (once per process per URL, and no DDL left once migrated),
PostgreSQL DDL guarded with IF NOT EXISTS and typed for the dialect."""
import re
import sqlite3

import pytest
from sqlalchemy import event, inspect, text

OLD_SCHEMA = """
CREATE TABLE cloud_accounts (id INTEGER PRIMARY KEY, name VARCHAR(100), provider VARCHAR(20), is_enabled BOOLEAN,
  credential_source_type VARCHAR(20), credentials JSON, regions JSON, labels JSON, created_at DATETIME, last_scanned_at DATETIME);
CREATE TABLE cloud_resources (id INTEGER PRIMARY KEY, account_id INTEGER, provider VARCHAR(20), region VARCHAR(30),
  resource_type VARCHAR(50), resource_id VARCHAR(500), name VARCHAR(200), tags JSON, raw_data JSON, status VARCHAR(30),
  managed BOOLEAN, created_at DATETIME, updated_at DATETIME, scanned_at DATETIME);
CREATE TABLE health_issues (id INTEGER PRIMARY KEY, resource_id VARCHAR(500), provider VARCHAR(20), severity VARCHAR(20),
  source VARCHAR(50), title VARCHAR(300), description TEXT, alarm_name VARCHAR(200), metric_data JSON, related_changes JSON,
  status VARCHAR(30), detected_at DATETIME, detected_by VARCHAR(50), resolved_at DATETIME, issue_type VARCHAR(40),
  fingerprint VARCHAR(64), occurrence_count INTEGER, first_seen DATETIME, last_seen DATETIME, trace_id VARCHAR(20),
  account_id INTEGER);
CREATE TABLE galaxy_builds (id INTEGER PRIMARY KEY, status VARCHAR(20), "trigger" VARCHAR(20), "full" BOOLEAN,
  started_at DATETIME, finished_at DATETIME, model_id VARCHAR(200), prompt_version VARCHAR(50), input_tokens INTEGER,
  output_tokens INTEGER, cost_usd FLOAT, node_count INTEGER, edge_count INTEGER, dropped_edge_count INTEGER,
  rule_graph JSON, llm_graph JSON, error TEXT);
CREATE TABLE rca_results (id INTEGER PRIMARY KEY, health_issue_id INTEGER, root_cause TEXT, confidence FLOAT,
  contributing_factors JSON, recommendations JSON, fix_plan JSON, fix_risk_level VARCHAR(20), sop_used VARCHAR(200),
  similar_cases JSON, model_id VARCHAR(100), created_at DATETIME, evidence JSON, evidence_verified BOOLEAN,
  critic_verdict VARCHAR(30), critic_notes TEXT, human_verdict VARCHAR(10), human_note TEXT, verified_at DATETIME);
INSERT INTO cloud_accounts (id, name, provider, is_enabled, credential_source_type, credentials, regions, labels)
  VALUES (1, 'prod', 'aws', 1, 'environment', '{"account_id": "111111111111"}', '[]', '{}');
INSERT INTO cloud_resources (id, account_id, provider, region, resource_type, resource_id, name, tags, raw_data, status, managed)
  VALUES (10, 1, 'aws', 'us-east-1', 'EC2', 'i-0abc', 'web-1', '{}', '{}', 'running', 1);
INSERT INTO health_issues (id, resource_id, provider, severity, source, title, description, metric_data, related_changes,
  status, detected_by, issue_type, occurrence_count, account_id)
  VALUES (1, 'i-0abc', 'aws', 'high', 'test', 't', 'd', '{}', '[]', 'open', 'test', 'cpu_spike', 1, NULL);
INSERT INTO rca_results (id, health_issue_id, root_cause, confidence, contributing_factors, recommendations, fix_plan,
  fix_risk_level, similar_cases, model_id, evidence)
  VALUES (1, 1, 'rc', 0.8, '[]', '[]', '{}', 'unknown', '[]', '', '[]');
"""

_NEW_HEALTH_COLUMNS = {"resource_ref", "anchor_status", "anchor_candidates", "observed_at"}
_NEW_RCA_COLUMNS = {"location", "location_status", "location_build_id", "location_verdict", "location_verdict_by",
                    "location_verdict_at"}
_NEW_PLAN_COLUMNS = {"plan_version", "content_hash", "approved_hash", "approved_version"}

# A 2.6.0 fix_plans table (no plan-identity columns): plan 1 approved before the upgrade, plan 2 still a draft
OLD_PLANS = """
CREATE TABLE fix_plans (id INTEGER PRIMARY KEY, plan_kind VARCHAR(10) DEFAULT 'fix', health_issue_id INTEGER,
  rca_result_id INTEGER, change_request_id INTEGER, risk_level VARCHAR(20), title VARCHAR(300), summary TEXT,
  steps JSON, rollback_plan JSON, estimated_impact TEXT, pre_checks JSON, post_checks JSON, status VARCHAR(30),
  approved_by VARCHAR(255), approved_at DATETIME, rejected_by VARCHAR(255), rejected_at DATETIME,
  rejection_reason TEXT, created_at DATETIME, updated_at DATETIME);
INSERT INTO fix_plans (id, plan_kind, health_issue_id, rca_result_id, risk_level, title, summary, steps, rollback_plan,
  estimated_impact, pre_checks, post_checks, status, approved_by)
  VALUES (1, 'fix', 1, 1, 'L1', 'p1', 's', '[{"command": "echo a"}]', '{}', '', '[]', '[]', 'approved', 'user:bob'),
         (2, 'fix', 1, 1, 'L1', 'p2', 's', '[{"command": "echo b"}]', '{}', '', '[]', '[]', 'draft', NULL);
"""
_MIGRATION_DDL = re.compile(
    r"ADD COLUMN (IF NOT EXISTS )?(resource_ref|anchor_status|anchor_candidates|observed_at|absent_since"
    r"|content_changed_at|rules_published_at|location\w*|plan_version|content_hash|approved_hash|approved_version)"
    r"|idx_health_issue_resource_ref|idx_health_issue_anchor_status",
    re.I,
)


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


def _run_init_db(path):
    import agenticops.models as models_mod
    from agenticops.config import settings

    models_mod._engine = None
    settings.database_url = f"sqlite:///{path}"
    engine = models_mod.get_engine()
    models_mod.init_db(engine)
    return engine


def _cols(engine, table):
    return {c["name"] for c in inspect(engine).get_columns(table)}


def _index_names(engine, table):
    return {ix["name"] for ix in inspect(engine).get_indexes(table)}


class _StubInspector:
    def __init__(self, columns, indexes):
        self.columns, self.indexes = columns, indexes

    def has_table(self, name):
        return name in self.columns

    def get_columns(self, name):
        return self.columns[name]

    def get_indexes(self, name):
        return self.indexes.get(name, [])


def test_adds_columns_indexes_and_relation_table(old_db):
    engine = _run_init_db(old_db)
    assert _NEW_HEALTH_COLUMNS <= _cols(engine, "health_issues")
    assert {"absent_since", "content_changed_at"} <= _cols(engine, "cloud_resources")
    assert "rules_published_at" in _cols(engine, "galaxy_builds")
    assert _NEW_RCA_COLUMNS <= _cols(engine, "rca_results")
    assert {"idx_health_issue_resource_ref", "idx_health_issue_anchor_status"} <= _index_names(engine, "health_issues")
    assert {"idx_resource_relation_src", "idx_resource_relation_dst", "idx_resource_relation_build"} <= _index_names(
        engine, "resource_relations"
    )


def test_rows_preserved(old_db):
    engine = _run_init_db(old_db)
    with engine.connect() as c:
        assert tuple(c.execute(text("SELECT id, resource_id, status FROM health_issues")).one()) == (1, "i-0abc", "open")
        assert c.execute(text("SELECT COUNT(*) FROM cloud_resources WHERE absent_since IS NULL")).scalar() == 1


def test_no_ddl_left_once_migrated(old_db):
    from agenticops.models import _statements_2_6_1

    engine = _run_init_db(old_db)
    assert _statements_2_6_1(inspect(engine), engine.dialect) == []


def test_second_init_db_issues_no_2_6_1_ddl(old_db):
    import agenticops.models as models_mod

    engine = _run_init_db(old_db)
    seen: list[str] = []

    def spy(conn, cursor, statement, parameters, context, executemany):
        seen.append(statement)

    event.listen(engine, "before_cursor_execute", spy)
    try:
        models_mod.init_db(engine)
    finally:
        event.remove(engine, "before_cursor_execute", spy)
    assert [s for s in seen if _MIGRATION_DDL.search(s)] == []


def test_fresh_database_needs_no_2_6_1_ddl(tmp_path):
    from agenticops.models import _statements_2_6_1

    engine = _run_init_db(tmp_path / "fresh.db")
    assert _NEW_HEALTH_COLUMNS <= _cols(engine, "health_issues")
    assert _statements_2_6_1(inspect(engine), engine.dialect) == []


def test_pg_statements_are_guarded_and_dialect_typed():
    from sqlalchemy.dialects import postgresql

    import agenticops.galaxy.models  # noqa: F401 — registers galaxy_builds
    from agenticops.models import _add_column_ddl, _statements_2_6_1

    pg = postgresql.dialect()
    stub = _StubInspector(
        {"health_issues": [{"name": "id"}], "cloud_resources": [{"name": "id"}], "galaxy_builds": [{"name": "id"}],
         "rca_results": [{"name": "id"}], "fix_plans": [{"name": "id"}]},
        {},
    )
    stmts = _statements_2_6_1(stub, pg)
    ref_ddl = _add_column_ddl(pg, "health_issues", "resource_ref", "REFERENCES cloud_resources(id) ON DELETE SET NULL")
    assert f"ALTER TABLE health_issues ADD COLUMN IF NOT EXISTS {ref_ddl}" in stmts
    assert "ALTER TABLE galaxy_builds ADD COLUMN IF NOT EXISTS rules_published_at TIMESTAMP WITHOUT TIME ZONE" in stmts
    assert "ALTER TABLE cloud_resources ADD COLUMN IF NOT EXISTS absent_since TIMESTAMP WITHOUT TIME ZONE" in stmts
    assert "ALTER TABLE cloud_resources ADD COLUMN IF NOT EXISTS content_changed_at TIMESTAMP WITHOUT TIME ZONE" in stmts
    assert "ALTER TABLE rca_results ADD COLUMN IF NOT EXISTS location JSON" in stmts
    assert "ALTER TABLE rca_results ADD COLUMN IF NOT EXISTS location_verdict_at TIMESTAMP WITHOUT TIME ZONE" in stmts
    assert "ALTER TABLE fix_plans ADD COLUMN IF NOT EXISTS plan_version INTEGER NOT NULL DEFAULT 1" in stmts
    assert "ALTER TABLE fix_plans ADD COLUMN IF NOT EXISTS approved_hash VARCHAR(64)" in stmts
    assert "CREATE INDEX IF NOT EXISTS idx_health_issue_resource_ref ON health_issues(resource_ref)" in stmts
    assert "CREATE INDEX IF NOT EXISTS idx_health_issue_anchor_status ON health_issues(anchor_status)" in stmts
    assert all("DATETIME" not in s for s in stmts)


# The post-2.2.0 Signal ledger, with the row that created issue 1: its signal stated no account.
LEDGER = """
CREATE TABLE alert_events (id INTEGER PRIMARY KEY, source VARCHAR(50), external_id VARCHAR(200), severity VARCHAR(20),
  title VARCHAR(500), description TEXT, resource_hint VARCHAR(500), raw_payload JSON, health_issue_id INTEGER,
  status VARCHAR(30), received_at DATETIME, trace_id VARCHAR(20), kind VARCHAR(20), fingerprint VARCHAR(64),
  resource_id VARCHAR(500), account_id VARCHAR(100), issue_type VARCHAR(40), disposition VARCHAR(20),
  disposition_reason VARCHAR(200), gate_evidence JSON);
INSERT INTO alert_events (id, source, external_id, severity, title, description, resource_hint, raw_payload,
  health_issue_id, status, received_at, kind, resource_id, account_id, issue_type, disposition, disposition_reason,
  gate_evidence)
  VALUES (1, 'webhook_prometheus', 'e1', 'high', 't', '', '', '{}', 1, 'processed', '2026-09-01 12:00:00', 'alert',
  'i-0abc', '', 'cpu_spike', 'promoted', 'new_issue', '{}');
"""


def test_backfill_anchors_existing_issues(old_db):
    """Spec §4 backfill 2: issue 1 names i-0abc, and its signal stated no account; the only enabled account
    holds it."""
    con = sqlite3.connect(old_db)
    con.executescript(LEDGER)
    con.commit()
    con.close()
    engine = _run_init_db(old_db)
    with engine.connect() as c:
        row = c.execute(text("SELECT resource_ref, anchor_status, account_id FROM health_issues WHERE id = 1")).one()
    assert tuple(row) == (10, "anchored", 1)


def test_backfill_failure_does_not_block_init_db(old_db, monkeypatch):
    import agenticops.services.identity_resolver as ir

    def boom(*args, **kwargs):
        raise RuntimeError("resolver down")

    monkeypatch.setattr(ir, "resolve", boom)
    engine = _run_init_db(old_db)
    with engine.connect() as c:
        assert c.execute(text("SELECT anchor_status FROM health_issues WHERE id = 1")).scalar() is None
    assert _NEW_HEALTH_COLUMNS <= _cols(engine, "health_issues")


def test_backfill_marks_existing_rcas_location_absent(old_db):
    """Spec §4 backfill 3: an RCA saved before 2.6.1 gave no location."""
    engine = _run_init_db(old_db)
    with engine.connect() as c:
        row = c.execute(text("SELECT location, location_status, location_build_id FROM rca_results WHERE id = 1")).one()
    assert tuple(row) == (None, "absent", None)


@pytest.fixture
def old_db_with_plans(old_db):
    con = sqlite3.connect(old_db)
    con.executescript(OLD_PLANS + LEDGER)  # LEDGER: the signal behind issue 1, so the anchor backfill places it
    con.commit()
    con.close()
    return old_db


def test_backfill_hashes_existing_plans_and_keeps_an_approval_runnable(old_db_with_plans):
    """Spec §4 / §3.D.1: every pre-2.6.1 plan gets its hash (over the account the anchor backfill just gave its
    issue); an approved one also gets it as its approved hash, so the execution gate still serves it."""
    from sqlalchemy.orm import Session

    from agenticops.models import FixPlan, HealthIssue
    from agenticops.services.plan_content import approval_drift, current_hash

    engine = _run_init_db(old_db_with_plans)
    assert _NEW_PLAN_COLUMNS <= _cols(engine, "fix_plans")
    with Session(engine) as s:
        approved, draft = s.get(FixPlan, 1), s.get(FixPlan, 2)
        assert s.get(HealthIssue, 1).account_id == 1
        assert approved.content_hash == current_hash(s, approved)
        assert (approved.approved_hash, approved.plan_version, approved.approved_version) == (
            approved.content_hash, 1, 1)
        assert approval_drift(s, approved) is None
        assert draft.content_hash == current_hash(s, draft) and draft.content_hash != approved.content_hash
        assert (draft.approved_hash, draft.approved_version) == (None, None)
