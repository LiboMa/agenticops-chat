"""Multi-attachment multipart upload: two files in one chat message reach the agent."""
import uuid

from datetime import datetime, timezone

import pytest
from starlette.testclient import TestClient

from agenticops.web.app import app
from agenticops.models import ChatSession, ChatMessage, get_db_session


@pytest.fixture
def client(tmp_path, monkeypatch):
    from agenticops.config import settings
    monkeypatch.setattr(settings, "chat_attachments_dir", str(tmp_path / "files"))  # never the repo's data/
    return TestClient(app)


def test_multipart_two_files_both_attached(client, monkeypatch):
    """POST with a png, a .txt and a .log in one multipart send → all three are staged, processed and recorded on
    the message (2026-11-07: through the same path as POST /api/chat/attachments)."""
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
        ("file", ("app.log", b"ERROR something failed", "text/plain")),
    ]
    try:
        resp = client.post(
            f"/api/chat/sessions/{session_id}/messages",
            data={"content": "analyze these", "client_message_id": str(uuid.uuid4())},
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
            assert names == ["app.log", "notes.txt", "shot.png"], f"all three attachments recorded, got {names}"
    finally:
        with get_db_session() as db:
            row = db.query(ChatSession).filter(ChatSession.session_id == session_id).first()
            if row:
                db.query(ChatMessage).filter(ChatMessage.session_id == row.id).delete()
                db.delete(row)


def test_too_many_files_rejected(client):
    """Server rejects more files than the upload config allows, even if the client would have blocked it."""
    session_id = "multi-attach-cap-002"
    now = datetime.now(timezone.utc)
    with get_db_session() as db:
        db.add(ChatSession(session_id=session_id, name="Cap",
                           created_at=now, updated_at=now, last_activity_at=now))
    from agenticops.chat import upload_config
    files = [("file", (f"f{i}.txt", b"hi", "text/plain")) for i in range(upload_config.effective().max_files + 1)]
    try:
        resp = client.post(
            f"/api/chat/sessions/{session_id}/messages",
            data={"content": "x", "client_message_id": str(uuid.uuid4())},
            files=files,
        )
        assert resp.status_code == 400
        assert "maximum" in resp.json().get("detail", "").lower()
    finally:
        with get_db_session() as db:
            row = db.query(ChatSession).filter(ChatSession.session_id == session_id).first()
            if row:
                db.query(ChatMessage).filter(ChatMessage.session_id == row.id).delete()
                db.delete(row)
