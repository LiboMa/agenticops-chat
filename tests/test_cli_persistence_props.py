"""Property-based tests for CLI message persistence consistency.

Feature: chat-session-persistence, Property 13: CLI 会话消息持久化一致性

Uses hypothesis to generate random message content (text strings) and roles
("user" or "assistant").  For each generated message, calls
``_cli_persist_message()`` then queries the DB to verify the content and role
match exactly.

**Validates: Requirements 9.4**
"""

import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from hypothesis import given, settings as h_settings, HealthCheck
from hypothesis import strategies as st

from agenticops.models import (
    ChatSession,
    ChatMessage,
    get_db_session,
    init_db,
)
from agenticops.cli.context import ChatContext
from agenticops.cli.main import _cli_persist_message


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Role: "user" or "assistant"
_role_st = st.sampled_from(["user", "assistant"])

# Message content: non-empty text strings (printable, reasonable length)
_content_st = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "M", "N", "P", "S", "Z"),
        blacklist_characters="\x00",
    ),
    min_size=1,
    max_size=500,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@contextmanager
def _make_session_ctx():
    """Create a DB ChatSession + ChatContext, clean up on exit."""
    sid = f"prop13-{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc)
    with get_db_session() as db:
        row = ChatSession(
            session_id=sid,
            name="Property 13 Test Session",
            created_at=now,
            updated_at=now,
            last_activity_at=now - timedelta(minutes=5),
        )
        db.add(row)
        db.flush()
        db_id = row.id

    ctx = ChatContext()
    ctx.db_session_id = db_id
    ctx.db_session_uuid = sid

    try:
        yield ctx
    finally:
        with get_db_session() as db:
            db.query(ChatMessage).filter(ChatMessage.session_id == db_id).delete()
            r = db.query(ChatSession).filter(ChatSession.id == db_id).first()
            if r:
                db.delete(r)


# ---------------------------------------------------------------------------
# Ensure DB is ready
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True, scope="module")
def _ensure_db():
    """Ensure DB tables exist."""
    init_db()


# ---------------------------------------------------------------------------
# Property 13: CLI 会话消息持久化一致性
# ---------------------------------------------------------------------------

class TestCliMessagePersistenceConsistency:
    """Property 13: CLI 会话消息持久化一致性

    For any CLI message (user or assistant), after calling
    ``_cli_persist_message()``, querying the DB should return a row with
    the exact same content and role.

    Feature: chat-session-persistence, Property 13: CLI 会话消息持久化一致性
    **Validates: Requirements 9.4**
    """

    @given(role=_role_st, content=_content_st)
    @h_settings(max_examples=120)
    def test_persisted_message_matches_input(self, role, content):
        """Content and role written by CLI are identical when read back."""
        with _make_session_ctx() as ctx:
            _cli_persist_message(ctx, role, content)

            with get_db_session() as db:
                msg = (
                    db.query(ChatMessage)
                    .filter(
                        ChatMessage.session_id == ctx.db_session_id,
                    )
                    .order_by(ChatMessage.id.desc())
                    .first()
                )
                assert msg is not None, (
                    f"Message not found in DB — role={role!r}, "
                    f"content={content!r}"
                )
                assert msg.role == role, (
                    f"Role mismatch: expected {role!r}, got {msg.role!r}"
                )
                assert msg.content == content, (
                    f"Content mismatch: expected {content!r}, got {msg.content!r}"
                )
