"""MVP-2.9.0 N20 (2.8.0 S3): the snapshot table learns `collection_health`, a snapshot may have no score, and a
security issue that never got an account takes the one its own signal rows state."""
import logging

import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.orm import Session

import agenticops.models as models


def _old_db(tmp_path):
    """The table as 2.5.0 created it: every column NOT NULL, no collection_health."""
    eng = sa.create_engine(f"sqlite:///{tmp_path}/old.db")
    with eng.begin() as c:
        c.execute(sa.text(
            "CREATE TABLE security_snapshots (id INTEGER NOT NULL, account_id VARCHAR(64) NOT NULL, "
            "provider VARCHAR(32) NOT NULL, created_at DATETIME NOT NULL, overall_score FLOAT NOT NULL, "
            "category_scores JSON NOT NULL, metrics JSON NOT NULL, exposure_paths JSON NOT NULL, "
            "cis_results JSON NOT NULL, PRIMARY KEY (id))"))
        c.execute(sa.text("CREATE INDEX ix_security_snapshots_account_id ON security_snapshots (account_id)"))
        c.execute(sa.text("CREATE INDEX ix_security_snapshots_created_at ON security_snapshots (created_at)"))
        c.execute(sa.text(
            "INSERT INTO security_snapshots (id, account_id, provider, created_at, overall_score, category_scores, "
            "metrics, exposure_paths, cis_results) VALUES (7, 'acct-a', 'aws', '2026-09-01 00:00:00', 62.5, "
            "'{\"iam\": 50.0}', '{}', '[]', '{\"cis-1.3\": \"fail\"}')"))
    return eng


def test_the_old_table_gets_the_column_and_may_hold_no_score(tmp_path):
    eng = _old_db(tmp_path)
    models._run_migrate_2_7_0(eng)
    cols = {c["name"]: c for c in inspect(eng).get_columns("security_snapshots")}
    assert "collection_health" in cols and cols["overall_score"]["nullable"]
    with Session(eng) as s:
        old = s.query(models.SecuritySnapshot).one()
        assert (old.id, old.account_id, old.overall_score, old.category_scores, old.cis_results, old.collection_health) == \
               (7, "acct-a", 62.5, {"iam": 50.0}, {"cis-1.3": "fail"}, None)
        s.add(models.SecuritySnapshot(account_id="acct-a", provider="aws", overall_score=None, category_scores={},
                                      metrics={}, exposure_paths=[], cis_results={},
                                      collection_health={"status": "failed", "sources": {}}))
        s.commit()          # before the migration: NOT NULL constraint failed
    assert {i["name"] for i in inspect(eng).get_indexes("security_snapshots")} == {
        "ix_security_snapshots_account_id", "ix_security_snapshots_created_at"}


def test_the_migration_runs_once(tmp_path, caplog):
    eng = _old_db(tmp_path)
    models._run_migrate_2_7_0(eng)
    assert models._statements_2_7_0(inspect(eng), eng.dialect) == []
    caplog.clear()      # the first run's own «Rebuilt table» line, when the logger's level lets it through
    with caplog.at_level(logging.INFO, logger="agenticops.models"):
        models._run_migrate_2_7_0(eng)
    assert not [r for r in caplog.records if "Rebuilt table" in r.getMessage()]      # nothing left to relax


def test_postgresql_drops_the_constraint_in_place():
    from sqlalchemy.dialects import postgresql

    class _Insp:
        def has_table(self, name):
            return name == "security_snapshots"

        def get_columns(self, name):
            return [{"name": "overall_score", "nullable": False}, {"name": "collection_health", "nullable": True}]

        def get_indexes(self, name):
            return []
    assert models._statements_2_7_0(_Insp(), postgresql.dialect()) == [
        "ALTER TABLE security_snapshots ALTER COLUMN overall_score DROP NOT NULL"]


# ── the one-time account backfill ─────────────────────────────────────────────────────────────────────────────


def _db(tmp_path):
    eng = sa.create_engine(f"sqlite:///{tmp_path}/now.db")
    models.Base.metadata.create_all(eng)
    with Session(eng) as s:
        s.add_all([models.CloudAccount(id=1, name="prod", provider="aws"),
                   models.CloudAccount(id=2, name="lab", provider="aws")])
        s.commit()
    return eng


def _issue(s, detected_by="security_poll", account_id=None, status="open", **kw):
    issue = models.HealthIssue(resource_id="arn:aws:s3:::b", severity="high", source=detected_by, title="t",
                               description="", status=status, detected_by=detected_by, account_id=account_id, **kw)
    s.add(issue)
    s.flush()
    return issue.id


def _signal(s, issue_id, account, disposition="promoted"):
    s.add(models.AlertEvent(source="security_poll", external_id="k", severity="high", title="t", description="",
                            resource_hint="", raw_payload={}, health_issue_id=issue_id, account_id=account,
                            disposition=disposition))


def test_an_issue_takes_the_account_its_signal_rows_state(tmp_path, caplog):
    eng = _db(tmp_path)
    with Session(eng) as s:
        named = _issue(s)
        _signal(s, named, "prod")
        _signal(s, named, "prod", disposition="merged")
        by_number = _issue(s, detected_by="security_posture", status="fix_planned")
        _signal(s, by_number, "2", disposition="merged")            # a primary key written as text
        s.commit()
    with caplog.at_level(logging.INFO, logger="agenticops.models"):
        models._backfill_security_issue_accounts_2_9_0(eng)
    with Session(eng) as s:
        assert s.get(models.HealthIssue, named).account_id == 1
        got = s.get(models.HealthIssue, by_number)
        assert (got.account_id, got.status) == (2, "fix_planned")   # the status is not touched
        assert s.query(models.PipelineEvent).count() == 0           # and nothing is written to a timeline
    assert "2 filled, 0 left without an account" in caplog.text


def test_an_issue_whose_rows_do_not_name_one_account_stays_empty(tmp_path, caplog):
    eng = _db(tmp_path)
    with Session(eng) as s:
        no_rows = _issue(s)
        two = _issue(s)
        _signal(s, two, "prod")
        _signal(s, two, "lab", disposition="merged")
        unknown = _issue(s)
        _signal(s, unknown, "an-account-nobody-manages")
        silent = _issue(s)
        _signal(s, silent, "")
        s.commit()
    with caplog.at_level(logging.INFO, logger="agenticops.models"):
        models._backfill_security_issue_accounts_2_9_0(eng)
    with Session(eng) as s:
        assert [s.get(models.HealthIssue, i).account_id for i in (no_rows, two, unknown, silent)] == [None] * 4
    assert "0 filled, 4 left without an account" in caplog.text


def test_only_security_findings_and_only_empty_ones_are_touched(tmp_path):
    eng = _db(tmp_path)
    with Session(eng) as s:
        other = _issue(s, detected_by="detect_agent")
        _signal(s, other, "prod")
        placed = _issue(s, account_id=2)
        _signal(s, placed, "prod")
        s.commit()
    models._backfill_security_issue_accounts_2_9_0(eng)
    with Session(eng) as s:
        assert s.get(models.HealthIssue, other).account_id is None      # another detector's anchoring rule is unchanged
        assert s.get(models.HealthIssue, placed).account_id == 2


def test_it_is_part_of_the_startup_migration_and_fail_soft(tmp_path, monkeypatch):
    eng = _db(tmp_path)
    with Session(eng) as s:
        issue = _issue(s)
        _signal(s, issue, "lab")
        s.commit()
    models._run_migrate_2_7_0(eng)
    with Session(eng) as s:
        assert s.get(models.HealthIssue, issue).account_id == 2
    import agenticops.services.identity_resolver as resolver
    monkeypatch.setattr(resolver, "account_pk", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    with Session(eng) as s:
        again = _issue(s)
        _signal(s, again, "lab")
        s.commit()
    models._run_migrate_2_7_0(eng)                                      # logs, never raises
    with Session(eng) as s:
        assert s.get(models.HealthIssue, again).account_id is None


def test_an_issue_placed_while_the_backfill_runs_is_left_alone(tmp_path, monkeypatch):
    """The write is a compare-and-set on «still empty»: the backfill never overwrites an account."""
    eng = _db(tmp_path)
    with Session(eng) as s:
        issue = _issue(s)
        _signal(s, issue, "prod")
        s.commit()
    import agenticops.services.identity_resolver as resolver
    real = resolver.account_pk

    def _meanwhile(session, value):
        with Session(eng) as other:                       # someone else places the issue first
            other.query(models.HealthIssue).filter_by(id=issue).update({"account_id": 2})
            other.commit()
        return real(session, value)
    monkeypatch.setattr(resolver, "account_pk", _meanwhile)
    models._backfill_security_issue_accounts_2_9_0(eng)
    with Session(eng) as s:
        assert s.get(models.HealthIssue, issue).account_id == 2
