"""SQLite runs in WAL mode with a 30 s busy timeout (2026-11-08): a reader never waits for a writer.

On the dev box a chat turn failed with "database is locked" while the Signal Gate's daily prune deleted 5706 rows in
one transaction — the rollback journal blocks readers once a large change spills to the file, and Python's sqlite3
waits only 5 s for a lock by default."""
import sqlite3
import time

import pytest


@pytest.fixture
def fresh_engine(tmp_path, monkeypatch):
    import agenticops.models as models_mod
    from agenticops.config import settings

    db = tmp_path / "wal.db"
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{db}")
    monkeypatch.setattr(models_mod, "_engine", None)
    engine = models_mod.get_engine()
    yield models_mod, engine, db
    engine.dispose()
    models_mod._engine = None


def test_init_db_switches_the_database_file_to_wal(fresh_engine):
    models_mod, engine, db = fresh_engine
    models_mod.init_db(engine)
    con = sqlite3.connect(db)
    try:
        assert con.execute("pragma journal_mode").fetchone()[0] == "wal"
    finally:
        con.close()


def test_every_connection_waits_30_seconds_for_a_lock(fresh_engine):
    _, engine, _ = fresh_engine
    with engine.connect() as conn:
        assert conn.exec_driver_sql("pragma busy_timeout").scalar() == 30000


def test_a_reader_is_not_blocked_by_an_open_bulk_delete(fresh_engine):
    models_mod, engine, db = fresh_engine
    models_mod.init_db(engine)
    from agenticops.models import AlertEvent

    with models_mod.get_db_session() as s:
        s.add_all([AlertEvent(source="s", external_id=str(i), severity="low", title="t") for i in range(3000)])
    # the dev box's daily prune: a bulk delete, not yet committed, large enough to spill to the database file
    writer = sqlite3.connect(db, timeout=1)
    try:
        writer.execute("pragma cache_size=1")
        writer.execute("begin immediate")
        writer.execute("delete from alert_events")
        started = time.monotonic()
        with models_mod.get_db_session() as s:
            seen = s.query(AlertEvent).count()
        elapsed = time.monotonic() - started
    finally:
        writer.rollback()
        writer.close()
    assert seen == 3000          # the last committed state
    assert elapsed < 1.0         # read at once, no wait for the writer
