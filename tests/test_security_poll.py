# tests/test_security_poll.py
"""Stage 4: cursor-based incremental security polling."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from agenticops import models


@pytest.fixture
def sess_factory():
    engine = create_engine("sqlite:///:memory:")
    models.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    @contextmanager
    def _sess():
        s = Session()
        try:
            yield s
            s.commit()
        finally:
            s.close()

    return _sess


class TestCursorStore:
    def test_get_cursor_default_is_recent_iso(self, sess_factory):
        from agenticops.security.incremental_poll import _get_cursor
        with sess_factory() as s:
            cur = _get_cursor(s, "acct-a", "guardduty", "us-east-1")
        dt = datetime.fromisoformat(cur)
        age = datetime.now(timezone.utc) - dt
        assert timedelta(hours=23) < age < timedelta(hours=25)  # ~24h backfill

    def test_set_then_get_roundtrip(self, sess_factory):
        from agenticops.security.incremental_poll import _get_cursor, _set_cursor
        with sess_factory() as s:
            _set_cursor(s, "acct-a", "guardduty", "us-east-1", "2026-08-31T01:00:00+00:00")
        with sess_factory() as s:
            assert _get_cursor(s, "acct-a", "guardduty", "us-east-1") == "2026-08-31T01:00:00+00:00"

    def test_set_cursor_upserts_single_row(self, sess_factory):
        from agenticops.security.incremental_poll import _set_cursor
        with sess_factory() as s:
            _set_cursor(s, "acct-a", "securityhub", "us-east-1", "2026-08-31T01:00:00+00:00")
        with sess_factory() as s:
            _set_cursor(s, "acct-a", "securityhub", "us-east-1", "2026-08-31T02:00:00+00:00")
        with sess_factory() as s:
            rows = s.query(models.SecurityPollCursor).all()
            assert len(rows) == 1
            assert rows[0].cursor == "2026-08-31T02:00:00+00:00"
