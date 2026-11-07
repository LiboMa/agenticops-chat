"""Sending a chat message with attachment ids: bound only when the dispatch is new, delivered for the answering
model, reported in an `attachments` SSE event (2026-11-07)."""
import json
import time
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from starlette.testclient import TestClient

from agenticops.config import ChatUploadSettings
from tests.fixtures.attachments import TOKENS, make

CLAUDE = "global.anthropic.claude-opus-5-5"
GPT_OSS = "openai.gpt-oss-120b-1:0"


def frames(text: str) -> list[tuple[str, dict]]:
    out = []
    for block in text.replace("\r\n", "\n").split("\n\n"):
        ev, data = "message", []
        for line in block.split("\n"):
            if line.startswith("event:"):
                ev = line[6:].strip()
            elif line.startswith("data:"):
                data.append(line[5:].strip())
        if data:
            out.append((ev, json.loads("\n".join(data))))
    return out


@pytest.fixture
def env(tmp_path, monkeypatch):
    import agenticops.models as models_mod
    import agenticops.web.app as webapp
    from agenticops.chat.attachments import service
    from agenticops.config import settings
    from agenticops.services import runtime_settings
    monkeypatch.setattr(models_mod, "_engine", None)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/send.db")
    monkeypatch.setattr(settings, "chat_attachments_dir", str(tmp_path / "files"))
    monkeypatch.setattr(settings, "chat_upload", ChatUploadSettings())
    models_mod.init_db()
    runtime_settings.reset_cache()
    service._last_sweep = 0.0
    calls = SimpleNamespace(n=0, content=None, model=CLAUDE)

    class _Agent:
        def __init__(self):
            self.model = SimpleNamespace(config={"model_id": calls.model})

        async def stream_async(self, content):
            calls.n += 1
            calls.content = content
            yield {"data": "done"}

    monkeypatch.setattr(webapp._chat_sessions, "get_or_create", lambda sid, *a: _Agent())
    monkeypatch.setattr(webapp, "_generate_session_title", lambda *_a: None)
    yield SimpleNamespace(client=TestClient(webapp.app), calls=calls, webapp=webapp, tmp=tmp_path)
    runtime_settings.reset_cache()


def _session():
    from agenticops.models import ChatSession, get_db_session
    now = datetime.now(timezone.utc)
    with get_db_session() as db:
        row = ChatSession(session_id=str(uuid.uuid4()), name="Chat", created_at=now, updated_at=now,
                          last_activity_at=now)
        db.add(row)
        db.flush()
        return row.session_id, row.id


def _upload(env, kind, sub=None):
    path = make(kind, env.tmp / "in" / (sub or uuid.uuid4().hex))
    r = env.client.post("/api/chat/attachments", files={"file": (path.name, path.read_bytes())})
    assert r.status_code == 201, r.text
    att_id = r.json()["id"]
    deadline = time.monotonic() + 60
    while env.client.get(f"/api/chat/attachments/{att_id}").json()["status"] == "processing":
        assert time.monotonic() < deadline
        time.sleep(0.1)
    return att_id


def _send(env, sid, ids, content="what is in these?", cmid=None):
    return env.client.post(f"/api/chat/sessions/{sid}/messages",
                           json={"content": content, "client_message_id": cmid or str(uuid.uuid4()),
                                 "attachment_ids": ids})


def _rows(**filters):
    from agenticops.models import ChatAttachment, get_db_session
    with get_db_session() as db:
        rows = db.query(ChatAttachment).filter_by(**filters).all()
        for r in rows:
            db.expunge(r)
        return rows


def _user_messages(pk):
    from agenticops.models import ChatMessage, get_db_session
    with get_db_session() as db:
        rows = db.query(ChatMessage).filter_by(session_id=pk, role="user").order_by(ChatMessage.id).all()
        for r in rows:
            db.expunge(r)
        return rows


def test_send_with_ids_binds_and_streams_attachments_event(env):
    from agenticops.chat.attachments import store
    sid, pk = _session()
    docx, png = _upload(env, "docx"), _upload(env, "png")
    r = _send(env, sid, [docx, png])
    assert r.status_code == 200, r.text
    events = frames(r.text)
    names = [e for e, _ in events]
    assert names.index("accepted") < names.index("attachments") < names.index("text")
    items = dict(events)["attachments"]["items"]
    assert [(i["id"], i["delivery"]) for i in items] == [(docx, "native_document"), (png, "native_image")]
    content = env.calls.content
    assert isinstance(content, list)
    assert any("document" in b for b in content) and any("image" in b for b in content)
    assert "sample-docx.docx" in content[0]["text"] and content[0]["text"].rstrip().endswith("what is in these?")
    msg = _user_messages(pk)[-1]
    assert dict(events)["attachments"]["user_message_id"] == msg.id
    assert [(a["id"], a["filename"], a["kind"], a["delivery"]) for a in msg.attachments] == [
        (docx, "sample-docx.docx", "office", "native_document"), (png, "sample-png.png", "image", "native_image")]
    bound = {a.id: a for a in _rows(session_id=pk)}
    assert set(bound) == {docx, png} and all(a.message_id == msg.id for a in bound.values())
    assert (store.session_root(sid) / docx / "original").is_file() and not store.staging_dir(docx).exists()


def test_processing_attachment_409_no_message_row(env):
    from agenticops.chat.attachments import service
    from agenticops.chat.attachments.types import classify
    from agenticops.models import get_db_session
    sid, pk = _session()
    with get_db_session() as db:
        att_id = service.create_staged(db, owner_key="web:anonymous", filename="a.txt", ft=classify("a.txt"),
                                       size=3).id
    r = _send(env, sid, [att_id])
    assert r.status_code == 409 and r.json()["detail"]["code"] == "attachments_processing"
    assert _user_messages(pk) == [] and env.calls.n == 0


def test_too_many_and_too_large_422(env):
    from agenticops.chat import upload_config
    sid, pk = _session()
    a, b = _upload(env, "txt"), _upload(env, "md")
    upload_config.save_patch({"max_files": 1}, "user:admin")
    r = _send(env, sid, [a, b])
    assert r.status_code == 422 and r.json()["detail"]["code"] == "too_many_attachments"
    r = _send(env, sid, ["0" * 32])
    assert r.status_code == 422 and r.json()["detail"]["code"] == "attachment_unavailable"
    assert _user_messages(pk) == []
    assert all(row.session_id is None for row in _rows())   # nothing bound, both still sendable


def test_replay_does_not_rebind_or_422(env):
    sid, pk = _session()
    att = _upload(env, "txt")
    cmid = str(uuid.uuid4())
    assert _send(env, sid, [att], cmid=cmid).status_code == 200
    again = _send(env, sid, [att], cmid=cmid)
    assert again.status_code == 200
    assert dict(frames(again.text))["done"]["replayed"] is True
    assert env.calls.n == 1 and len(_user_messages(pk)) == 1


def test_busy_leaves_attachments_staged(env):
    sid, pk = _session()
    att = _upload(env, "txt")
    env.webapp._streaming_sessions.add(sid)
    try:
        r = _send(env, sid, [att])
        assert r.status_code == 409 and r.json()["detail"]["code"] == "session_busy"
    finally:
        env.webapp._streaming_sessions.discard(sid)
    assert _rows(id=att)[0].session_id is None
    assert _send(env, sid, [att]).status_code == 200    # the same upload goes with the next try


def test_slash_command_with_attachments_422(env):
    sid, _ = _session()
    att = _upload(env, "txt")
    for text in ("/channel list", "/send_to ops hello"):
        r = _send(env, sid, [att], content=text)
        assert r.status_code == 422 and r.json()["detail"]["code"] == "attachments_not_allowed"


def test_multipart_still_works_and_cleans_on_busy(env):
    from agenticops.chat.attachments import store
    sid, pk = _session()
    files = [("file", ("notes.txt", b"hello MULTI-1", "text/plain")),
             ("file", ("shot.png", make("png", env.tmp / "mp").read_bytes(), "image/png"))]
    r = env.client.post(f"/api/chat/sessions/{sid}/messages",
                        data={"content": "", "client_message_id": str(uuid.uuid4())}, files=files)
    assert r.status_code == 200, r.text
    assert [i["delivery"] for i in dict(frames(r.text))["attachments"]["items"]] == ["text", "native_image"]
    assert "hello MULTI-1" in env.calls.content[0]["text"]
    assert "Please analyze the attached file(s): notes.txt, shot.png" in env.calls.content[0]["text"]
    assert len(_rows(session_id=pk)) == 2
    env.webapp._streaming_sessions.add(sid)
    try:
        r = env.client.post(f"/api/chat/sessions/{sid}/messages",
                            data={"content": "x", "client_message_id": str(uuid.uuid4())}, files=files[:1])
        assert r.status_code == 409
    finally:
        env.webapp._streaming_sessions.discard(sid)
    assert [row for row in _rows() if row.session_id is None] == []
    assert store.staged_ids() == set()


def test_multipart_refuses_bad_file_with_its_code(env):
    sid, pk = _session()
    r = env.client.post(f"/api/chat/sessions/{sid}/messages",
                        data={"content": "x", "client_message_id": str(uuid.uuid4())},
                        files=[("file", ("setup.exe", b"MZ", "application/octet-stream"))])
    assert r.status_code == 415 and r.json()["detail"]["code"] == "unsupported_type"
    assert _user_messages(pk) == [] and _rows() == []


def test_delivery_per_model(env):
    sid, _ = _session()
    env.calls.model = GPT_OSS
    png, txt = _upload(env, "png"), _upload(env, "txt")
    r = _send(env, sid, [png, txt])
    items = dict(frames(r.text))["attachments"]["items"]
    assert [(i["delivery"], i["reason"]) for i in items] == [("notice", "model_no_images"), ("text", None)]
    assert isinstance(env.calls.content, str) and TOKENS["txt"] in env.calls.content


def test_empty_content_with_attachments_gets_default_text(env):
    sid, pk = _session()
    att = _upload(env, "txt")
    r = _send(env, sid, [att], content="")
    assert r.status_code == 200
    assert _user_messages(pk)[-1].content == "Please analyze the attached file(s): sample-txt.txt"
    r = _send(env, sid, [], content="  ")
    assert r.status_code == 422


def test_other_users_attachment_cannot_be_sent(env):
    from agenticops.chat.attachments import service
    from agenticops.chat.attachments.types import classify
    from agenticops.models import ChatAttachment, get_db_session
    sid, _ = _session()
    with get_db_session() as db:
        att_id = service.create_staged(db, owner_key="user:mallory@x", filename="a.txt", ft=classify("a.txt"),
                                       size=3).id
        db.query(ChatAttachment).filter_by(id=att_id).update({"status": "ready"})
    r = _send(env, sid, [att_id])
    assert r.status_code == 422 and r.json()["detail"]["code"] == "attachment_unavailable"
