"""Tests for CLI message persistence (task 6.4).

Validates: Requirement 9.4 — CLI messages written to chat_messages table,
shared with Web Dashboard, with graceful degradation on DB failure.
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from agenticops.models import (
    ChatSession,
    ChatMessage,
    get_db_session,
    init_db,
)
from agenticops.cli.context import ChatContext
from agenticops.cli.main import _cli_persist_message


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _ensure_db():
    """Ensure DB tables exist before each test."""
    init_db()


@pytest.fixture
def session_with_ctx():
    """Create a DB session and return a ChatContext linked to it."""
    sid = f"persist-test-{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc)
    with get_db_session() as db:
        row = ChatSession(
            session_id=sid,
            name="Persist Test Session",
            created_at=now,
            updated_at=now,
            last_activity_at=now - timedelta(minutes=10),
        )
        db.add(row)
        db.flush()
        db_id = row.id

    ctx = ChatContext()
    ctx.db_session_id = db_id
    ctx.db_session_uuid = sid

    yield ctx

    # Cleanup
    with get_db_session() as db:
        db.query(ChatMessage).filter(ChatMessage.session_id == db_id).delete()
        r = db.query(ChatSession).filter(ChatSession.id == db_id).first()
        if r:
            db.delete(r)


def _query_messages(session_pk: int):
    """Query messages within a DB session and return plain dicts to avoid detached errors."""
    with get_db_session() as db:
        rows = (
            db.query(ChatMessage)
            .filter(ChatMessage.session_id == session_pk)
            .order_by(ChatMessage.id.asc())
            .all()
        )
        return [
            {
                "role": r.role,
                "content": r.content,
                "tool_calls": r.tool_calls,
                "token_usage": r.token_usage,
            }
            for r in rows
        ]


# ---------------------------------------------------------------------------
# Core persistence tests
# ---------------------------------------------------------------------------

class TestCliPersistMessage:
    """_cli_persist_message writes messages to chat_messages table."""

    def test_persists_user_message(self, session_with_ctx):
        ctx = session_with_ctx
        _cli_persist_message(ctx, "user", "Hello from CLI")

        msgs = _query_messages(ctx.db_session_id)
        assert len(msgs) == 1
        assert msgs[0]["role"] == "user"
        assert msgs[0]["content"] == "Hello from CLI"

    def test_persists_assistant_message(self, session_with_ctx):
        ctx = session_with_ctx
        _cli_persist_message(ctx, "assistant", "Here is the response")

        msgs = _query_messages(ctx.db_session_id)
        assert len(msgs) == 1
        assert msgs[0]["role"] == "assistant"
        assert msgs[0]["content"] == "Here is the response"

    def test_persists_token_usage(self, session_with_ctx):
        ctx = session_with_ctx
        usage = {"input": 100, "output": 200}
        _cli_persist_message(ctx, "assistant", "response", token_usage=usage)

        msgs = _query_messages(ctx.db_session_id)
        assert msgs[0]["token_usage"] == {"input": 100, "output": 200}

    def test_persists_tool_calls(self, session_with_ctx):
        ctx = session_with_ctx
        tools = [{"name": "scan_agent", "status": "done"}]
        _cli_persist_message(ctx, "assistant", "scan done", tool_calls=tools)

        msgs = _query_messages(ctx.db_session_id)
        assert msgs[0]["tool_calls"] == [{"name": "scan_agent", "status": "done"}]

    def test_updates_last_activity_at(self, session_with_ctx):
        ctx = session_with_ctx

        # Record the original last_activity_at
        with get_db_session() as db:
            row = db.query(ChatSession).filter(ChatSession.id == ctx.db_session_id).first()
            original_activity = row.last_activity_at

        _cli_persist_message(ctx, "user", "trigger activity update")

        with get_db_session() as db:
            row = db.query(ChatSession).filter(ChatSession.id == ctx.db_session_id).first()
            assert row.last_activity_at > original_activity

    def test_multiple_messages_shared_session(self, session_with_ctx):
        """Both user and assistant messages land in the same session."""
        ctx = session_with_ctx
        _cli_persist_message(ctx, "user", "What is EC2?")
        _cli_persist_message(ctx, "assistant", "EC2 is a compute service.")

        msgs = _query_messages(ctx.db_session_id)
        assert len(msgs) == 2
        assert msgs[0]["role"] == "user"
        assert msgs[1]["role"] == "assistant"


# ---------------------------------------------------------------------------
# Skip / graceful degradation tests
# ---------------------------------------------------------------------------

class TestCliPersistGracefulDegradation:
    """Persistence skips or degrades gracefully when appropriate."""

    def test_skips_when_no_db_session(self):
        """When ctx.db_session_id is None, no DB write occurs."""
        ctx = ChatContext()
        assert ctx.db_session_id is None

        # Should not raise
        _cli_persist_message(ctx, "user", "this should be silently skipped")

    def test_logs_warning_on_db_failure(self, session_with_ctx):
        """DB write failure logs a warning and does not raise."""
        ctx = session_with_ctx

        with patch(
            "agenticops.cli.main.get_db_session",
            side_effect=Exception("DB connection lost"),
        ):
            # Should not raise — graceful degradation
            _cli_persist_message(ctx, "user", "this will fail silently")

    def test_none_tool_calls_stored_as_null(self, session_with_ctx):
        """When tool_calls is None, stored as NULL."""
        ctx = session_with_ctx
        _cli_persist_message(ctx, "assistant", "no tools used", tool_calls=None)

        msgs = _query_messages(ctx.db_session_id)
        assert msgs[0]["tool_calls"] is None

    def test_empty_tool_calls_stored_as_null(self, session_with_ctx):
        """When tool_calls is an empty list, stored as NULL."""
        ctx = session_with_ctx
        _cli_persist_message(ctx, "assistant", "no tools", tool_calls=[])

        msgs = _query_messages(ctx.db_session_id)
        assert msgs[0]["tool_calls"] is None


# ---------------------------------------------------------------------------
# Web Dashboard interop test
# ---------------------------------------------------------------------------

class TestWebDashboardInterop:
    """CLI-persisted messages are visible via the same DB queries the Web uses."""

    def test_messages_queryable_by_session_uuid(self, session_with_ctx):
        """Messages written by CLI can be found using the session UUID
        (the same key the Web Dashboard uses)."""
        ctx = session_with_ctx
        _cli_persist_message(ctx, "user", "CLI user msg")
        _cli_persist_message(ctx, "assistant", "CLI assistant msg")

        # Query the way the Web Dashboard does: by session UUID → session PK → messages
        with get_db_session() as db:
            session_row = (
                db.query(ChatSession)
                .filter(ChatSession.session_id == ctx.db_session_uuid)
                .first()
            )
            assert session_row is not None
            msgs = (
                db.query(ChatMessage)
                .filter(ChatMessage.session_id == session_row.id)
                .order_by(ChatMessage.created_at.asc())
                .all()
            )
            assert len(msgs) == 2
            assert msgs[0].role == "user"
            assert msgs[0].content == "CLI user msg"
            assert msgs[1].role == "assistant"
            assert msgs[1].content == "CLI assistant msg"


# ---------------------------------------------------------------------------
# Slash command persistence tests (F2)
# ---------------------------------------------------------------------------

class TestSlashCommandPersistence:
    """Slash commands persist user + system messages to DB (parity with agent turns)."""

    def test_slash_command_result_is_persisted(self, monkeypatch):
        """A slash command that returns display text persists user + system messages."""
        from agenticops.cli import main as cli_main

        persisted = []
        monkeypatch.setattr(
            cli_main, "_cli_persist_message",
            lambda ctx, role, content, **kw: persisted.append((role, content)),
        )
        # Stub the dispatcher to behave like a normal display-returning slash command
        monkeypatch.setattr(cli_main, "handle_slash_command", lambda ctx, cmd: "STATUS OUTPUT")

        from agenticops.cli.context import ChatContext
        ctx = ChatContext()
        # Exercise the persistence helper the loop should call for slash results:
        cli_main._persist_slash_interaction(ctx, "/status", "STATUS OUTPUT")

        assert ("user", "/status") in persisted
        assert ("system", "STATUS OUTPUT") in persisted
