"""MVP-2.7.0 S5: chat context + dispatch columns arrive by the additive 2.7.0 migration; old rows stay NULL."""
import sqlalchemy as sa
from sqlalchemy import inspect

import agenticops.models as models


def _old_db(tmp_path):
    eng = sa.create_engine(f"sqlite:///{tmp_path}/old.db")
    with eng.begin() as c:
        c.execute(sa.text("CREATE TABLE chat_sessions (id INTEGER PRIMARY KEY, session_id VARCHAR(36), name VARCHAR(200))"))
        c.execute(sa.text("CREATE TABLE chat_messages (id INTEGER PRIMARY KEY, session_id INTEGER, role VARCHAR(20), content TEXT)"))
        c.execute(sa.text("INSERT INTO chat_messages (session_id, role, content) VALUES (1, 'user', 'hi')"))
    return eng


def test_migration_adds_the_columns_and_the_unique_index(tmp_path):
    eng = _old_db(tmp_path)
    models._run_migrate_2_7_0(eng)
    insp = inspect(eng)
    sess = {c["name"] for c in insp.get_columns("chat_sessions")}
    assert {"context_entity_type", "context_entity_id", "context_account_id", "context_region", "context_locked_at"} <= sess
    msg = {c["name"] for c in insp.get_columns("chat_messages")}
    assert {"client_message_id", "dispatch_state"} <= msg
    idx = {i["name"]: i for i in insp.get_indexes("chat_messages")}
    assert idx["uq_chat_message_client_id"]["unique"]
    with eng.begin() as c:
        assert c.execute(sa.text("SELECT client_message_id, dispatch_state FROM chat_messages")).one() == (None, None)


def test_migration_is_idempotent(tmp_path):
    eng = _old_db(tmp_path)
    models._run_migrate_2_7_0(eng)
    assert models._statements_2_7_0(inspect(eng), eng.dialect) == []


def test_two_null_client_ids_are_allowed_but_not_two_equal_ones(tmp_path):
    eng = _old_db(tmp_path)
    models._run_migrate_2_7_0(eng)
    with eng.begin() as c:
        c.execute(sa.text("INSERT INTO chat_messages (session_id, role, content) VALUES (1, 'user', 'b')"))
        c.execute(sa.text("INSERT INTO chat_messages (session_id, role, content, client_message_id) VALUES (1,'user','c','x')"))
    import pytest
    with pytest.raises(sa.exc.IntegrityError):
        with eng.begin() as c:
            c.execute(sa.text("INSERT INTO chat_messages (session_id, role, content, client_message_id) VALUES (1,'user','d','x')"))
