"""Tests for CLI /session slash commands with DB operations (task 6.3).

Validates: Requirements 9.1, 9.2, 9.3, 9.5, 9.6, 9.7, 9.9
"""

import json
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agenticops.models import (
    ChatSession,
    ChatMessage,
    get_db_session,
    init_db,
)
from agenticops.cli.context import ChatContext
from agenticops.cli.main import _slash_session, _session_toggle_field


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _ensure_db():
    """Ensure DB tables exist before each test."""
    init_db()


@pytest.fixture
def ctx():
    """A fresh ChatContext."""
    return ChatContext()


@pytest.fixture
def _seed_sessions():
    """Create test sessions with messages for /session command tests."""
    now = datetime.utcnow()
    ids = {
        "pinned": f"test-pinned-{uuid.uuid4().hex[:8]}",
        "starred": f"test-starred-{uuid.uuid4().hex[:8]}",
        "normal": f"test-normal-{uuid.uuid4().hex[:8]}",
        "archived": f"test-archived-{uuid.uuid4().hex[:8]}",
    }
    db_ids = {}
    with get_db_session() as db:
        s1 = ChatSession(
            session_id=ids["pinned"],
            name="Pinned Session",
            last_activity_at=now - timedelta(hours=1),
            pinned=True,
        )
        s2 = ChatSession(
            session_id=ids["starred"],
            name="Starred Session",
            last_activity_at=now - timedelta(minutes=30),
            starred=True,
        )
        s3 = ChatSession(
            session_id=ids["normal"],
            name="Normal Session",
            last_activity_at=now,
        )
        s4 = ChatSession(
            session_id=ids["archived"],
            name="Archived Session",
            last_activity_at=now - timedelta(minutes=10),
            archived=True,
        )
        db.add_all([s1, s2, s3, s4])
        db.flush()
        db_ids["pinned"] = s1.id
        db_ids["starred"] = s2.id
        db_ids["normal"] = s3.id
        db_ids["archived"] = s4.id

        # Add messages
        for i in range(5):
            db.add(ChatMessage(
                session_id=s3.id,
                role="user" if i % 2 == 0 else "assistant",
                content=f"Normal msg {i}",
            ))
        db.add(ChatMessage(session_id=s1.id, role="user", content="Pinned msg"))

    yield {"uuids": ids, "db_ids": db_ids}

    # Cleanup
    with get_db_session() as db:
        for sid in ids.values():
            row = db.query(ChatSession).filter(ChatSession.session_id == sid).first()
            if row:
                db.query(ChatMessage).filter(ChatMessage.session_id == row.id).delete()
                db.delete(row)


# ---------------------------------------------------------------------------
# /session list
# ---------------------------------------------------------------------------

class TestSessionList:
    """Validates: Requirement 9.1"""

    def test_list_shows_sessions(self, ctx, _seed_sessions):
        result = _slash_session(ctx, ["list"])
        assert "Chat Sessions" in result
        assert "Pinned Session" in result
        assert "Normal Session" in result

    def test_list_hides_archived(self, ctx, _seed_sessions):
        result = _slash_session(ctx, ["list"])
        assert "Archived Session" not in result

    def test_list_shows_message_count(self, ctx, _seed_sessions):
        result = _slash_session(ctx, ["list"])
        # Normal session has 5 messages
        assert "5 msgs" in result

    def test_list_shows_pin_star_icons(self, ctx, _seed_sessions):
        result = _slash_session(ctx, ["list"])
        assert "📌" in result
        assert "⭐" in result

    def test_list_default_no_args(self, ctx, _seed_sessions):
        """No args defaults to list."""
        result = _slash_session(ctx, [])
        assert "Chat Sessions" in result

    def test_list_shows_current_marker(self, ctx, _seed_sessions):
        ctx.db_session_id = _seed_sessions["db_ids"]["normal"]
        result = _slash_session(ctx, ["list"])
        assert "(current)" in result

    def test_list_empty_db(self, ctx):
        """When no sessions exist, show a message."""
        # Archive all existing sessions to simulate empty
        with get_db_session() as db:
            db.query(ChatSession).update({"archived": True})
        result = _slash_session(ctx, ["list"])
        assert "No sessions found" in result
        # Restore
        with get_db_session() as db:
            db.query(ChatSession).update({"archived": False})


# ---------------------------------------------------------------------------
# /session resume
# ---------------------------------------------------------------------------

class TestSessionResume:
    """Validates: Requirements 9.2, 9.3"""

    def test_resume_by_db_id(self, ctx, _seed_sessions):
        db_id = _seed_sessions["db_ids"]["normal"]
        result = _slash_session(ctx, ["resume", str(db_id)])
        assert "Resumed session" in result
        assert ctx.db_session_id == db_id

    def test_resume_by_uuid(self, ctx, _seed_sessions):
        uid = _seed_sessions["uuids"]["starred"]
        result = _slash_session(ctx, ["resume", uid])
        assert "Resumed session" in result
        assert ctx.db_session_uuid == uid

    def test_resume_by_name(self, ctx, _seed_sessions):
        result = _slash_session(ctx, ["resume", "Pinned"])
        assert "Resumed session" in result
        assert ctx.db_session_uuid == _seed_sessions["uuids"]["pinned"]

    def test_resume_no_args_picks_most_recent(self, ctx, _seed_sessions):
        result = _slash_session(ctx, ["resume"])
        assert "Resumed session" in result
        # Normal Session has the most recent last_activity_at
        assert ctx.db_session_uuid == _seed_sessions["uuids"]["normal"]

    def test_resume_not_found(self, ctx, _seed_sessions):
        result = _slash_session(ctx, ["resume", "nonexistent-xyz-999"])
        assert "not found" in result

    def test_resume_injects_history_into_agent(self, ctx, _seed_sessions):
        agent = MagicMock()
        agent.messages = []
        ctx.agent = agent
        db_id = _seed_sessions["db_ids"]["normal"]
        _slash_session(ctx, ["resume", str(db_id)])
        # Normal session has 5 messages, agent should have history
        assert len(agent.messages) > 0

    def test_resume_no_active_sessions(self, ctx):
        """When no non-archived sessions exist."""
        with get_db_session() as db:
            db.query(ChatSession).update({"archived": True})
        result = _slash_session(ctx, ["resume"])
        assert "No active sessions" in result
        with get_db_session() as db:
            db.query(ChatSession).update({"archived": False})


# ---------------------------------------------------------------------------
# /session rename
# ---------------------------------------------------------------------------

class TestSessionRename:
    """Validates: Requirement 9.7"""

    def test_rename_by_id(self, ctx, _seed_sessions):
        db_id = _seed_sessions["db_ids"]["normal"]
        result = _slash_session(ctx, ["rename", str(db_id), "New", "Name"])
        assert "Renamed" in result
        assert "New Name" in result

        # Verify in DB
        with get_db_session() as db:
            row = db.query(ChatSession).filter(ChatSession.id == db_id).first()
            assert row.name == "New Name"

    def test_rename_not_found(self, ctx, _seed_sessions):
        result = _slash_session(ctx, ["rename", "99999", "Whatever"])
        assert "not found" in result

    def test_rename_missing_args(self, ctx, _seed_sessions):
        result = _slash_session(ctx, ["rename", str(_seed_sessions["db_ids"]["normal"])])
        assert "Usage" in result


# ---------------------------------------------------------------------------
# /session pin, star, archive
# ---------------------------------------------------------------------------

class TestSessionToggle:
    """Validates: Requirements 9.5, 9.6"""

    def test_pin_toggle_on(self, ctx, _seed_sessions):
        db_id = _seed_sessions["db_ids"]["normal"]
        result = _slash_session(ctx, ["pin", str(db_id)])
        assert "Pinned on" in result
        with get_db_session() as db:
            row = db.query(ChatSession).filter(ChatSession.id == db_id).first()
            assert row.pinned is True

    def test_pin_toggle_off(self, ctx, _seed_sessions):
        db_id = _seed_sessions["db_ids"]["pinned"]
        result = _slash_session(ctx, ["pin", str(db_id)])
        assert "Pinned off" in result
        with get_db_session() as db:
            row = db.query(ChatSession).filter(ChatSession.id == db_id).first()
            assert row.pinned is False

    def test_star_toggle(self, ctx, _seed_sessions):
        db_id = _seed_sessions["db_ids"]["normal"]
        result = _slash_session(ctx, ["star", str(db_id)])
        assert "Starred on" in result
        with get_db_session() as db:
            row = db.query(ChatSession).filter(ChatSession.id == db_id).first()
            assert row.starred is True

    def test_archive_toggle(self, ctx, _seed_sessions):
        db_id = _seed_sessions["db_ids"]["normal"]
        result = _slash_session(ctx, ["archive", str(db_id)])
        assert "Archived on" in result
        with get_db_session() as db:
            row = db.query(ChatSession).filter(ChatSession.id == db_id).first()
            assert row.archived is True

    def test_toggle_not_found(self, ctx, _seed_sessions):
        result = _slash_session(ctx, ["pin", "99999"])
        assert "not found" in result

    def test_toggle_missing_id(self, ctx, _seed_sessions):
        result = _slash_session(ctx, ["pin"])
        assert "Usage" in result


# ---------------------------------------------------------------------------
# /session save / load — backward compatibility
# ---------------------------------------------------------------------------

class TestSessionBackwardCompat:
    """Validates: Requirement 9.9"""

    def test_save_and_load(self, ctx, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        ctx.account = "test-account"
        ctx.output_format = "json"
        ctx.detail_level = "detailed"

        result = _slash_session(ctx, ["save", "test_compat"])
        assert "Session saved" in result

        # Reset and load
        ctx.account = None
        ctx.output_format = "table"
        result = _slash_session(ctx, ["load", "test_compat"])
        assert "Session loaded" in result
        assert ctx.account == "test-account"
        assert ctx.output_format == "json"

    def test_load_not_found(self, ctx, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        result = _slash_session(ctx, ["load", "nonexistent"])
        assert "not found" in result

    def test_delete_local(self, ctx, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        _slash_session(ctx, ["save", "to_delete"])
        result = _slash_session(ctx, ["delete", "to_delete"])
        assert "Session deleted" in result


# ---------------------------------------------------------------------------
# Usage / unknown subcommand
# ---------------------------------------------------------------------------

class TestSessionUsage:
    def test_unknown_subcommand(self, ctx):
        result = _slash_session(ctx, ["foobar"])
        assert "Usage" in result
