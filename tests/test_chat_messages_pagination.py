"""Tests for cursor-paginated chat messages endpoint + metadata-only detail.

Validates the concurrent-chat-sessions design:
- GET /sessions/{id}/messages?limit=&before= returns chronological page + cursor
- GET /sessions/{id} returns metadata only (no messages payload)
"""

from datetime import datetime, timezone

import pytest
from starlette.testclient import TestClient

from agenticops.web.app import app
from agenticops.models import ChatSession, ChatMessage, get_db_session


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def _seed_session_with_messages():
    """Create a session with 120 messages (ids ascending)."""
    sid = "page-test-session-001"
    now = datetime.now(timezone.utc)
    with get_db_session() as db:
        s = ChatSession(session_id=sid, name="Page Test",
                        created_at=now, updated_at=now, last_activity_at=now)
        db.add(s)
        db.flush()
        for i in range(120):
            db.add(ChatMessage(
                session_id=s.id,
                role="user" if i % 2 == 0 else "assistant",
                content=f"msg-{i:03d}",
            ))
    yield sid
    with get_db_session() as db:
        row = db.query(ChatSession).filter(ChatSession.session_id == sid).first()
        if row:
            db.query(ChatMessage).filter(ChatMessage.session_id == row.id).delete()
            db.delete(row)


class TestMessagesPagination:
    def test_default_returns_newest_page_chronological(self, client, _seed_session_with_messages):
        sid = _seed_session_with_messages
        resp = client.get(f"/api/chat/sessions/{sid}/messages", params={"limit": 50})
        assert resp.status_code == 200
        body = resp.json()
        # newest 50 messages, returned oldest→newest
        assert len(body["messages"]) == 50
        contents = [m["content"] for m in body["messages"]]
        assert contents == sorted(contents)  # chronological ascending
        assert contents[-1] == "msg-119"     # last is the newest
        assert contents[0] == "msg-070"      # newest 50 = msg-070..msg-119
        assert body["has_more"] is True
        assert body["next_cursor"] is not None

    def test_before_cursor_returns_older_page(self, client, _seed_session_with_messages):
        sid = _seed_session_with_messages
        first = client.get(f"/api/chat/sessions/{sid}/messages", params={"limit": 50}).json()
        cursor = first["next_cursor"]
        older = client.get(
            f"/api/chat/sessions/{sid}/messages",
            params={"limit": 50, "before": cursor},
        ).json()
        assert len(older["messages"]) == 50
        older_contents = [m["content"] for m in older["messages"]]
        # older page is msg-020..msg-069 (the 50 immediately before the newest 50)
        assert older_contents[-1] == "msg-069"
        assert older_contents[0] == "msg-020"
        # no overlap with the first page
        first_contents = {m["content"] for m in first["messages"]}
        assert not (set(older_contents) & first_contents)

    def test_last_page_has_more_false(self, client, _seed_session_with_messages):
        sid = _seed_session_with_messages
        # walk to the oldest page (120 msgs / 50 = pages of 50,50,20)
        p1 = client.get(f"/api/chat/sessions/{sid}/messages", params={"limit": 50}).json()
        p2 = client.get(f"/api/chat/sessions/{sid}/messages",
                        params={"limit": 50, "before": p1["next_cursor"]}).json()
        p3 = client.get(f"/api/chat/sessions/{sid}/messages",
                        params={"limit": 50, "before": p2["next_cursor"]}).json()
        assert len(p3["messages"]) == 20
        assert p3["messages"][0]["content"] == "msg-000"
        assert p3["has_more"] is False
        assert p3["next_cursor"] is None

    def test_empty_session_returns_empty_page(self, client):
        sid = "page-test-empty-002"
        now = datetime.now(timezone.utc)
        with get_db_session() as db:
            db.add(ChatSession(session_id=sid, name="Empty",
                               created_at=now, updated_at=now, last_activity_at=now))
        try:
            resp = client.get(f"/api/chat/sessions/{sid}/messages")
            assert resp.status_code == 200
            body = resp.json()
            assert body["messages"] == []
            assert body["has_more"] is False
            assert body["next_cursor"] is None
        finally:
            with get_db_session() as db:
                row = db.query(ChatSession).filter(ChatSession.session_id == sid).first()
                if row:
                    db.delete(row)

    def test_nonexistent_session_404(self, client):
        resp = client.get("/api/chat/sessions/does-not-exist-xyz/messages")
        assert resp.status_code == 404

    def test_limit_capped_at_100(self, client, _seed_session_with_messages):
        sid = _seed_session_with_messages
        resp = client.get(f"/api/chat/sessions/{sid}/messages", params={"limit": 500})
        assert resp.status_code == 422  # Query(le=100) rejects >100


class TestDetailMetadataOnly:
    def test_detail_returns_no_messages(self, client, _seed_session_with_messages):
        sid = _seed_session_with_messages
        resp = client.get(f"/api/chat/sessions/{sid}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["messages"] == []          # metadata-only now
        assert body["message_count"] == 120     # count still accurate
        assert body["name"] == "Page Test"
