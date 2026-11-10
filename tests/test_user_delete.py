"""Deleting a user (MVP-2.8.0, owner 2026-11-10: «Admin user可以删除用户»).

A delete is soft: the row stays with `deleted_at` set, so
- the login name is never given to anyone else (the unique email; records name people by `user:<email>`),
- private chats and reports keep pointing at a row nobody else can ever get,
- and no sign-in path (password, session, API key) accepts the user again, even if `is_active` were flipped back.
Real users, sessions and keys on a temp DB, the HTTP layer through the app (imported before sign-in is turned on)."""
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from starlette.testclient import TestClient

from agenticops.auth.roles import grants
from agenticops.models import Base


@pytest.fixture
def env(tmp_path, monkeypatch):
    import agenticops.audit.models  # noqa: F401
    import agenticops.auth.models  # noqa: F401
    import agenticops.models as models_mod
    from agenticops.config import settings
    from agenticops.web.app import app
    monkeypatch.setattr(models_mod, "_engine", None)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/del.db")
    monkeypatch.setattr(settings, "api_auth_enabled", True)
    Base.metadata.create_all(models_mod.get_engine())
    return SimpleNamespace(client=TestClient(app), settings=settings)


def _user(email, role="writer"):
    from agenticops.auth import AuthService
    is_admin, perms = grants(role)
    user = AuthService.create_user(email=email, password=f"pw-{email}-0", is_admin=is_admin, permissions=perms)
    return user, AuthService.create_session(user.id)


def H(token):
    return {"Authorization": f"Bearer {token}"}


# ── T1: the marker and the sign-in gates ────────────────────────────────────────────────────────────────────


def test_the_migration_adds_users_deleted_at_once(tmp_path):
    from sqlalchemy import create_engine, inspect, text
    import agenticops.auth.models  # noqa: F401  (users in the metadata the DDL is built from)
    import agenticops.models as models_mod
    engine = create_engine(f"sqlite:///{tmp_path}/legacy.db")
    with engine.begin() as c:
        c.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, email VARCHAR(255) UNIQUE, password_hash VARCHAR(255),"
                       " is_admin BOOLEAN, is_active BOOLEAN, permissions JSON)"))
        c.execute(text("INSERT INTO users (email, password_hash, is_admin, is_active, permissions) "
                       "VALUES ('old', 'x', 0, 1, '[\"read\"]')"))
    models_mod._run_migrate_2_7_0(engine)
    assert "deleted_at" in {c["name"] for c in inspect(engine).get_columns("users")}
    with engine.connect() as c:
        assert c.execute(text("SELECT deleted_at FROM users")).one() == (None,)
    assert models_mod._statements_2_7_0(inspect(engine), engine.dialect) == []   # once


def test_a_deleted_user_never_signs_in_even_if_reactivated_by_hand(env):
    from agenticops.auth import AuthService
    from agenticops.auth.models import User
    from agenticops.models import get_db_session
    ops, session = _user("ops")
    key = AuthService.create_api_key(user_id=ops.id, name="k", permissions=["read"])
    assert AuthService.authenticate("ops", "pw-ops-0") is not None and AuthService.validate_session(session) is not None
    with get_db_session() as s:   # deleted, then is_active flipped back by hand: still nothing gets in
        u = s.query(User).filter_by(id=ops.id).one()
        u.deleted_at = datetime.now(timezone.utc)
        u.is_active = True
    assert AuthService.authenticate("ops", "pw-ops-0") is None
    assert AuthService.validate_session(session) is None
    assert AuthService.validate_api_key(key) is None
    assert env.client.get("/api/users/me", headers=H(session)).status_code == 401
