"""Multi-attachment multipart upload: two files in one chat message reach the agent."""

from datetime import datetime, timezone

import pytest
from starlette.testclient import TestClient

from agenticops.web.app import app
from agenticops.models import ChatSession, ChatMessage, get_db_session


@pytest.fixture
def client():
    return TestClient(app)


def test_multipart_two_files_both_attached(client, monkeypatch):
    """POST with 1 png (image branch) + 1 .txt (document branch) → both recorded as
    attachments. (.txt routes through is_document_file server-side, not the text else-branch;
    the assertions hold regardless of branch — the point is BOTH files are captured.)"""
    import agenticops.web.app as webapp

    session_id = "multi-attach-001"
    now = datetime.now(timezone.utc)
    with get_db_session() as db:
        db.add(ChatSession(session_id=session_id, name="Multi",
                           created_at=now, updated_at=now, last_activity_at=now))

    captured = {}

    class _CaptureAgent:
        async def stream_async(self, content):
            captured["content"] = content
            yield {"data": "ok"}

    monkeypatch.setattr(webapp._chat_sessions, "get_or_create", lambda sid: _CaptureAgent())

    # a tiny valid PNG (1x1) + a text file
    png_bytes = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
        "890000000a49444154789c6360000002000154a24f5e0000000049454e44ae426082"
    )
    files = [
        ("file", ("shot.png", png_bytes, "image/png")),
        ("file", ("notes.txt", b"hello log line", "text/plain")),
    ]
    try:
        resp = client.post(
            f"/api/chat/sessions/{session_id}/messages",
            data={"content": "analyze these"},
            files=files,
        )
        assert resp.status_code == 200

        with get_db_session() as db:
            row = db.query(ChatSession).filter(ChatSession.session_id == session_id).first()
            msgs = db.query(ChatMessage).filter(
                ChatMessage.session_id == row.id, ChatMessage.role == "user"
            ).all()
            assert msgs, "user message persisted"
            atts = msgs[-1].attachments or []
            names = sorted(a["filename"] for a in atts)
            assert names == ["notes.txt", "shot.png"], f"both attachments recorded, got {names}"
    finally:
        with get_db_session() as db:
            row = db.query(ChatSession).filter(ChatSession.session_id == session_id).first()
            if row:
                db.query(ChatMessage).filter(ChatMessage.session_id == row.id).delete()
                db.delete(row)
