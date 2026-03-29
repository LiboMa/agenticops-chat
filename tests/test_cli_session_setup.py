"""Tests for CLI --resume and --session startup parameters (task 6.2).

Validates: Requirement 9.8
"""

import uuid
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from agenticops.models import (
    ChatSession,
    ChatMessage,
    get_db_session,
    init_db,
)
from agenticops.cli.context import ChatContext
from agenticops.cli.main import _cli_setup_db_session


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _ensure_db():
    """Ensure DB tables exist before each test."""
    init_db()


@pytest.fixture
def mock_agent():
    """A lightweight mock agent with a messages list."""
    agent = MagicMock()
    agent.messages = []
    return agent


@pytest.fixture
def mock_console():
    """A mock Rich Console that captures print calls."""
    return MagicMock()


@pytest.fixture
def _seed_sessions():
    """Create test sessions with messages for resume/session tests."""
    ids = {
        "recent": f"cli-test-recent-{uuid.uuid4().hex[:8]}",
        "older": f"cli-test-older-{uuid.uuid4().hex[:8]}",
        "archived": f"cli-test-archived-{uuid.uuid4().hex[:8]}",
    }
    now = datetime.utcnow()
    db_ids = {}
    with get_db_session() as db:
        s1 = ChatSession(
            session_id=ids["recent"],
            name="Recent Session",
            created_at=now,
            updated_at=now,
            last_activity_at=now,
        )
        s2 = ChatSession(
            session_id=ids["older"],
            name="Older Session",
            created_at=now - timedelta(hours=2),
            updated_at=now - timedelta(hours=2),
            last_activity_at=now - timedelta(hours=2),
        )
        s3 = ChatSession(
            session_id=ids["archived"],
            name="Archived Session",
            created_at=now - timedelta(minutes=30),
            updated_at=now - timedelta(minutes=30),
            last_activity_at=now - timedelta(minutes=30),
            archived=True,
        )
        db.add_all([s1, s2, s3])
        db.flush()
        db_ids["recent"] = s1.id
        db_ids["older"] = s2.id
        db_ids["archived"] = s3.id

        # Add messages to the recent session
        for i in range(3):
            db.add(ChatMessage(
                session_id=s1.id,
                role="user" if i % 2 == 0 else "assistant",
                content=f"Test message {i}",
            ))
        # Add a message to the older session
        db.add(ChatMessage(
            session_id=s2.id,
            role="user",
            content="Older message",
        ))

    yield {"uuids": ids, "db_ids": db_ids}

    # Cleanup
    with get_db_session() as db:
        for sid in ids.values():
            row = db.query(ChatSession).filter(ChatSession.session_id == sid).first()
            if row:
                db.query(ChatMessage).filter(ChatMessage.session_id == row.id).delete()
                db.delete(row)


# ---------------------------------------------------------------------------
# Default: create new session
# ---------------------------------------------------------------------------

class TestDefaultNewSession:
    """aiops chat (no flags) should create a new DB session."""

    def test_creates_new_session(self, mock_agent, mock_console):
        ctx = ChatContext()
        _cli_setup_db_session(ctx, mock_agent, mock_console, resume=False, session_id=None)

        assert ctx.db_session_id is not None
        assert ctx.db_session_uuid is not None

        # Verify session exists in DB
        with get_db_session() as db:
            row = db.query(ChatSession).filter(
                ChatSession.session_id == ctx.db_session_uuid
            ).first()
            assert row is not None
            assert row.name.startswith("CLI Chat")

        # Cleanup
        with get_db_session() as db:
            row = db.query(ChatSession).filter(
                ChatSession.session_id == ctx.db_session_uuid
            ).first()
            if row:
                db.delete(row)

    def test_no_history_injected(self, mock_agent, mock_console):
        ctx = ChatContext()
        _cli_setup_db_session(ctx, mock_agent, mock_console, resume=False, session_id=None)

        # New session should not inject any history
        assert len(mock_agent.messages) == 0

        # Cleanup
        with get_db_session() as db:
            row = db.query(ChatSession).filter(
                ChatSession.session_id == ctx.db_session_uuid
            ).first()
            if row:
                db.delete(row)


# ---------------------------------------------------------------------------
# --resume: resume most recent non-archived session
# ---------------------------------------------------------------------------

class TestResumeFlag:
    """aiops chat --resume should resume the most recent non-archived session."""

    def test_resumes_most_recent(self, mock_agent, mock_console, _seed_sessions):
        ctx = ChatContext()
        _cli_setup_db_session(ctx, mock_agent, mock_console, resume=True, session_id=None)

        # Should pick the "recent" session (most recent non-archived)
        assert ctx.db_session_uuid == _seed_sessions["uuids"]["recent"]
        assert ctx.db_session_id == _seed_sessions["db_ids"]["recent"]

    def test_loads_history_into_agent(self, mock_agent, mock_console, _seed_sessions):
        ctx = ChatContext()
        _cli_setup_db_session(ctx, mock_agent, mock_console, resume=True, session_id=None)

        # History should be injected into agent.messages
        assert len(mock_agent.messages) > 0

    def test_prints_resumed_message(self, mock_agent, mock_console, _seed_sessions):
        ctx = ChatContext()
        _cli_setup_db_session(ctx, mock_agent, mock_console, resume=True, session_id=None)

        # Should print "Resumed session: ..."
        mock_console.print.assert_called()
        printed_args = [str(call) for call in mock_console.print.call_args_list]
        assert any("Resumed session" in arg for arg in printed_args)

    def test_skips_archived_sessions(self, mock_agent, mock_console, _seed_sessions):
        ctx = ChatContext()
        _cli_setup_db_session(ctx, mock_agent, mock_console, resume=True, session_id=None)

        # Should NOT resume the archived session
        assert ctx.db_session_uuid != _seed_sessions["uuids"]["archived"]

    def test_creates_new_when_no_sessions(self, mock_agent, mock_console):
        """When no non-archived sessions exist, --resume creates a new one."""
        # Archive all existing sessions first
        with get_db_session() as db:
            db.query(ChatSession).update({"archived": True})

        ctx = ChatContext()
        _cli_setup_db_session(ctx, mock_agent, mock_console, resume=True, session_id=None)

        assert ctx.db_session_id is not None
        assert ctx.db_session_uuid is not None

        # Should print a warning about creating new session
        printed_args = [str(call) for call in mock_console.print.call_args_list]
        assert any("No active sessions" in arg or "Creating" in arg for arg in printed_args)

        # Cleanup: un-archive sessions and remove the new one
        with get_db_session() as db:
            db.query(ChatSession).filter(ChatSession.archived == True).update({"archived": False})
            row = db.query(ChatSession).filter(
                ChatSession.session_id == ctx.db_session_uuid
            ).first()
            if row:
                db.delete(row)


# ---------------------------------------------------------------------------
# --session <id>: resume specific session
# ---------------------------------------------------------------------------

class TestSessionIdFlag:
    """aiops chat --session <id> should resume the specified session."""

    def test_resume_by_uuid(self, mock_agent, mock_console, _seed_sessions):
        target_uuid = _seed_sessions["uuids"]["older"]
        ctx = ChatContext()
        _cli_setup_db_session(ctx, mock_agent, mock_console, resume=False, session_id=target_uuid)

        assert ctx.db_session_uuid == target_uuid
        assert ctx.db_session_id == _seed_sessions["db_ids"]["older"]

    def test_resume_by_db_id(self, mock_agent, mock_console, _seed_sessions):
        target_db_id = _seed_sessions["db_ids"]["older"]
        ctx = ChatContext()
        _cli_setup_db_session(
            ctx, mock_agent, mock_console,
            resume=False, session_id=str(target_db_id),
        )

        assert ctx.db_session_id == target_db_id

    def test_loads_history(self, mock_agent, mock_console, _seed_sessions):
        target_uuid = _seed_sessions["uuids"]["older"]
        ctx = ChatContext()
        _cli_setup_db_session(ctx, mock_agent, mock_console, resume=False, session_id=target_uuid)

        # Older session has 1 message, so history should be injected
        assert len(mock_agent.messages) > 0

    def test_prints_resumed_message(self, mock_agent, mock_console, _seed_sessions):
        target_uuid = _seed_sessions["uuids"]["older"]
        ctx = ChatContext()
        _cli_setup_db_session(ctx, mock_agent, mock_console, resume=False, session_id=target_uuid)

        printed_args = [str(call) for call in mock_console.print.call_args_list]
        assert any("Resumed session" in arg for arg in printed_args)

    def test_nonexistent_session_exits(self, mock_agent, mock_console, _seed_sessions):
        from click.exceptions import Exit
        with pytest.raises(Exit):
            ctx = ChatContext()
            _cli_setup_db_session(
                ctx, mock_agent, mock_console,
                resume=False, session_id="nonexistent-uuid-12345",
            )

    def test_can_resume_archived_session(self, mock_agent, mock_console, _seed_sessions):
        """--session can explicitly target an archived session."""
        target_uuid = _seed_sessions["uuids"]["archived"]
        ctx = ChatContext()
        _cli_setup_db_session(ctx, mock_agent, mock_console, resume=False, session_id=target_uuid)

        assert ctx.db_session_uuid == target_uuid
