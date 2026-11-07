"""Chat attachments: the row, the files on disk, who may see them, binding to a message, cleanup (2026-11-07)."""
import shutil
import uuid
from datetime import datetime, timedelta, timezone

import pytest

import agenticops.web.app  # noqa: F401 — imported at collection, as every API test does: the auth middleware is
#                            added only when api_auth_enabled is on at import time, and the env fixture turns it on
from agenticops.auth.actor import Actor
from agenticops.chat.attachments.types import classify
from agenticops.config import ChatUploadSettings, settings
from tests.fixtures.attachments import TOKENS, make

ALICE = Actor("user", "alice@x", 1, ("read", "write"))
BOB = Actor("user", "bob@x", 2, ("read", "write"))
ADMIN = Actor("user", "root@x", 3, ("read", "write", "admin"))


@pytest.fixture
def env(tmp_path, monkeypatch):
    import agenticops.models as models_mod
    from agenticops.chat.attachments import service
    from agenticops.services import runtime_settings
    monkeypatch.setattr(models_mod, "_engine", None)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/att.db")
    monkeypatch.setattr(settings, "chat_attachments_dir", str(tmp_path / "files"))
    monkeypatch.setattr(settings, "chat_upload", ChatUploadSettings())
    monkeypatch.setattr(settings, "api_auth_enabled", True)
    models_mod.init_db()
    runtime_settings.reset_cache()
    service._last_sweep = 0.0
    return tmp_path


def _session(owner=None, visibility="workspace"):
    from agenticops.models import ChatSession, get_db_session
    sid = str(uuid.uuid4())
    with get_db_session() as db:
        row = ChatSession(session_id=sid, name="t", owner_user_id=owner, visibility=visibility)
        db.add(row)
        db.flush()
        return row.id, sid


def _stage(kind="docx", actor=ALICE, tmp=None, process=True):
    from agenticops.chat.attachments import service, store
    from agenticops.models import get_db_session
    src = make(kind, tmp / "src" / uuid.uuid4().hex)
    ft = classify(src.name)
    with get_db_session() as db:
        att = service.create_staged(db, owner_key=actor.key, filename=src.name, ft=ft, size=src.stat().st_size)
        att_id = att.id
    d = store.staging_dir(att_id)
    d.mkdir(parents=True)
    shutil.copyfile(src, d / "original")
    if process:
        service.process_now(att_id)
    return att_id


def _row(att_id):
    from agenticops.models import ChatAttachment, get_db_session
    with get_db_session() as db:
        row = db.get(ChatAttachment, att_id)
        if row is None:
            return None
        db.expunge(row)
        return row


def test_create_and_process_ready(env):
    att_id = _stage(tmp=env)
    row = _row(att_id)
    assert row.status == "ready" and row.kind == "office" and row.ext == ".docx"
    assert row.session_id is None and row.owner_key == "user:alice@x"
    assert row.meta["sha256"] and len(att_id) == 32
    from agenticops.chat.attachments import store
    assert TOKENS["docx"] in (store.staging_dir(att_id) / "text.txt").read_text()


def test_process_failed_sets_reason(env):
    att_id = _stage("encrypted_pdf", tmp=env)
    row = _row(att_id)
    assert (row.status, row.reason) == ("failed", "encrypted")


def test_long_filename_is_cut_to_column(env):
    from agenticops.chat.attachments import service
    from agenticops.models import get_db_session
    with get_db_session() as db:
        att = service.create_staged(db, owner_key="web:anonymous", filename="报" * 400 + ".pdf",
                                    ft=classify("a.pdf"), size=1)
        att_id = att.id
    assert len(_row(att_id).filename) <= 255 and _row(att_id).filename.endswith(".pdf")


def test_row_deleted_during_processing_removes_dir(env, monkeypatch):
    from agenticops.chat.attachments import service, store, worker
    from agenticops.models import ChatAttachment, get_db_session
    att_id = _stage(tmp=env, process=False)
    real_run = worker.run

    def run_then_vanish(*a, **k):
        result = real_run(*a, **k)
        with get_db_session() as db:
            db.query(ChatAttachment).filter(ChatAttachment.id == att_id).delete()
        return result
    monkeypatch.setattr(worker, "run", run_then_vanish)
    service.process_now(att_id)
    assert _row(att_id) is None and not store.staging_dir(att_id).exists()


def test_visible_rules(env):
    from fastapi import HTTPException
    from agenticops.chat.attachments import service
    from agenticops.models import get_db_session
    staged = _stage(tmp=env)
    with get_db_session() as db:
        assert service.visible(db, staged, ALICE).id == staged
        with pytest.raises(service.AttachmentError) as e:
            service.visible(db, staged, BOB)
        assert e.value.status == 404
        with pytest.raises(service.AttachmentError):
            service.visible(db, "nope", ALICE)
    for visibility, bob_sees in (("workspace", True), ("private", False)):
        pk, sid = _session(owner=1, visibility=visibility)
        att_id = _stage(tmp=env)
        with get_db_session() as db:
            atts = service.check_for_send(db, [att_id], ALICE, ChatUploadSettings())
            service.bind(db, atts, db.get(__import__("agenticops.models", fromlist=["ChatSession"]).ChatSession, pk), None)
        service.move_bound([att_id], sid)
        with get_db_session() as db:
            assert service.visible(db, att_id, ALICE).id == att_id
            assert service.visible(db, att_id, ADMIN).id == att_id
            if bob_sees:
                assert service.visible(db, att_id, BOB).id == att_id
            else:
                with pytest.raises(service.AttachmentError):
                    service.visible(db, att_id, BOB)
    assert HTTPException  # noqa: the API maps AttachmentError, the service never raises HTTPException


def test_check_for_send_errors(env):
    from agenticops.chat.attachments import service
    from agenticops.models import ChatSession, get_db_session
    cfg = ChatUploadSettings(max_files=2, max_file_mb=1, max_total_mb=1)
    a, b, c = (_stage("txt", tmp=env) for _ in range(3))
    mine_processing = _stage("txt", tmp=env, process=False)
    bobs = _stage("txt", actor=BOB, tmp=env)
    pk, _ = _session()
    with get_db_session() as db:
        def code(ids, actor=ALICE, c=cfg):
            with pytest.raises(service.AttachmentError) as e:
                service.check_for_send(db, ids, actor, c)
            return e.value.status, e.value.code
        assert code([a, b, c]) == (422, "too_many_attachments")
        assert code([a, a]) == (422, "too_many_attachments")
        assert code([a, bobs]) == (422, "attachment_unavailable")
        assert code([a, "missing"]) == (422, "attachment_unavailable")
        assert code([a, mine_processing]) == (409, "attachments_processing")
        assert [x.id for x in service.check_for_send(db, [b, a], ALICE, cfg)] == [b, a]
        service.bind(db, service.check_for_send(db, [a], ALICE, cfg), db.get(ChatSession, pk), None)
    with get_db_session() as db:
        assert code([a]) == (422, "attachment_unavailable")       # already bound
    from agenticops.models import ChatAttachment
    with get_db_session() as db:
        db.query(ChatAttachment).filter(ChatAttachment.id == b).update({"size": 2 * 1024 * 1024})
    with get_db_session() as db:
        with pytest.raises(service.AttachmentError) as e:
            service.check_for_send(db, [b], ALICE, cfg)
        assert (e.value.status, e.value.code) == (422, "attachments_too_large")


def test_failed_attachment_may_be_sent(env):
    from agenticops.chat.attachments import service
    from agenticops.models import get_db_session
    bad = _stage("encrypted_pdf", tmp=env)
    with get_db_session() as db:
        assert [x.id for x in service.check_for_send(db, [bad], ALICE, ChatUploadSettings())] == [bad]


def test_bind_then_move(env):
    from agenticops.chat.attachments import service, store
    from agenticops.models import ChatSession, get_db_session
    pk, sid = _session()
    att_id = _stage(tmp=env)
    with get_db_session() as db:
        atts = service.check_for_send(db, [att_id], ALICE, ChatUploadSettings())
        service.bind(db, atts, db.get(ChatSession, pk), None)
        prepared = service.prepared(atts[0], sid)
    assert prepared.dir == store.session_root(sid) / att_id
    service.move_bound([att_id], sid)
    assert (store.session_root(sid) / att_id / "original").is_file()
    assert not store.staging_dir(att_id).exists()
    assert TOKENS["docx"] in (prepared.dir / "text.txt").read_text()
    assert _row(att_id).session_id == pk


def test_move_bound_skips_deleted_session(env):
    from agenticops.chat.attachments import service, store
    from agenticops.models import ChatSession, get_db_session
    pk, sid = _session()
    att_id = _stage(tmp=env)
    with get_db_session() as db:
        service.bind(db, service.check_for_send(db, [att_id], ALICE, ChatUploadSettings()), db.get(ChatSession, pk),
                     None)
    with get_db_session() as db:
        db.query(ChatSession).filter(ChatSession.id == pk).delete()
    service.move_bound([att_id], sid)
    assert not store.session_root(sid).exists()


def test_attachment_dir_falls_back_to_staging(env):
    from agenticops.chat.attachments import service, store
    from agenticops.models import ChatSession, get_db_session
    pk, sid = _session()
    att_id = _stage(tmp=env)
    with get_db_session() as db:
        service.bind(db, service.check_for_send(db, [att_id], ALICE, ChatUploadSettings()), db.get(ChatSession, pk),
                     None)
    assert store.attachment_dir(_row(att_id), sid) == store.staging_dir(att_id)   # not moved yet
    service.move_bound([att_id], sid)
    assert store.attachment_dir(_row(att_id), sid) == store.session_root(sid) / att_id


def test_delete_staged(env):
    from agenticops.chat.attachments import service, store
    from agenticops.models import ChatSession, get_db_session
    att_id = _stage(tmp=env)
    with get_db_session() as db:
        with pytest.raises(service.AttachmentError):
            service.delete_staged(db, att_id, BOB)
        service.delete_staged(db, att_id, ALICE)
    assert _row(att_id) is None and not store.staging_dir(att_id).exists()
    pk, _ = _session()
    bound = _stage(tmp=env)
    with get_db_session() as db:
        service.bind(db, service.check_for_send(db, [bound], ALICE, ChatUploadSettings()), db.get(ChatSession, pk),
                     None)
    with get_db_session() as db:
        with pytest.raises(service.AttachmentError) as e:
            service.delete_staged(db, bound, ALICE)
        assert (e.value.status, e.value.code) == (409, "attachment_bound")


def test_delete_for_session(env):
    from agenticops.chat.attachments import service, store
    from agenticops.models import ChatAttachment, ChatSession, get_db_session
    pk, sid = _session()
    att_id = _stage(tmp=env)
    with get_db_session() as db:
        service.bind(db, service.check_for_send(db, [att_id], ALICE, ChatUploadSettings()), db.get(ChatSession, pk),
                     None)
    service.move_bound([att_id], sid)
    with get_db_session() as db:
        service.delete_for_session(db, pk)
    store.remove_session(sid)
    with get_db_session() as db:
        assert db.query(ChatAttachment).count() == 0
    assert not store.session_root(sid).exists()


def test_sweep_expired_and_orphans(env):
    from agenticops.chat.attachments import service, store
    from agenticops.models import ChatAttachment, get_db_session
    old = _stage(tmp=env)
    fresh = _stage(tmp=env)
    with get_db_session() as db:
        db.query(ChatAttachment).filter(ChatAttachment.id == old).update(
            {"created_at": datetime.now(timezone.utc) - timedelta(hours=25)})
    orphan = store.staging_dir("0" * 32)
    orphan.mkdir(parents=True)
    ghost_session = store.session_root(str(uuid.uuid4()))
    ghost_session.mkdir(parents=True)
    removed = service.sweep_staged()
    assert removed >= 3
    assert _row(old) is None and not store.staging_dir(old).exists()
    assert _row(fresh) is not None and store.staging_dir(fresh).exists()
    assert not orphan.exists() and not ghost_session.exists()


def test_sweep_rehomes_bound_left_in_staging(env):
    from agenticops.chat.attachments import service, store
    from agenticops.models import ChatAttachment, ChatSession, get_db_session
    pk, sid = _session()
    att_id = _stage(tmp=env)
    with get_db_session() as db:
        service.bind(db, service.check_for_send(db, [att_id], ALICE, ChatUploadSettings()), db.get(ChatSession, pk),
                     None)
        db.query(ChatAttachment).filter(ChatAttachment.id == att_id).update(
            {"created_at": datetime.now(timezone.utc) - timedelta(hours=48)})
    service.sweep_staged()
    assert _row(att_id) is not None
    assert (store.session_root(sid) / att_id / "original").is_file()


def test_maybe_sweep_runs_at_most_hourly(env, monkeypatch):
    from agenticops.chat.attachments import service
    calls = []
    monkeypatch.setattr(service, "sweep_staged", lambda now=None: calls.append(1) or 0)
    service.maybe_sweep()
    service.maybe_sweep()
    assert calls == [1]


def test_submit_processing_runs_in_background(env):
    from agenticops.chat.attachments import service
    att_id = _stage(tmp=env, process=False)
    service.submit_processing(att_id).result(timeout=60)
    assert _row(att_id).status == "ready"


def test_bind_is_compare_and_set(env):
    """Two sends that both passed check_for_send with the same upload: only the first binds it."""
    from types import SimpleNamespace
    from agenticops.chat.attachments import service
    from agenticops.models import ChatSession, get_db_session
    pk1, _ = _session()
    pk2, _ = _session()
    att_id = _stage(tmp=env)
    with get_db_session() as db:
        service.bind(db, service.check_for_send(db, [att_id], ALICE, ChatUploadSettings()), db.get(ChatSession, pk1),
                     None)
    with get_db_session() as db:
        with pytest.raises(service.AttachmentError) as e:
            service.bind(db, [SimpleNamespace(id=att_id)], db.get(ChatSession, pk2), None)   # its stale check
        assert (e.value.status, e.value.code) == (409, "attachment_unavailable")
    assert _row(att_id).session_id == pk1


# ── rebuild, delete with the session, startup sweep (Task 10) ────────────────


def _message(pk, role, content, attachments=None, state=None):
    from agenticops.models import ChatMessage, get_db_session
    with get_db_session() as db:
        msg = ChatMessage(session_id=pk, role=role, content=content, attachments=attachments, dispatch_state=state)
        db.add(msg)
        db.flush()
        return msg.id


def _bound(pk, sid, kind, tmp, message_id=None):
    from agenticops.chat.attachments import service
    from agenticops.models import ChatSession, get_db_session
    att_id = _stage(kind, tmp=tmp)
    with get_db_session() as db:
        service.bind(db, service.check_for_send(db, [att_id], ALICE, ChatUploadSettings()), db.get(ChatSession, pk),
                     message_id)
    service.move_bound([att_id], sid)
    return att_id


def _texts(history):
    return "\n".join(b.get("text", "") for m in history for b in m["content"])


def test_rebuild_excludes_inflight_message(env):
    from agenticops.web.session_manager import _load_history_messages
    pk, sid = _session()
    _message(pk, "user", "first question")
    _message(pk, "assistant", "first answer")
    _message(pk, "user", "IN-FLIGHT question", state="running")
    history = _load_history_messages(sid, 20)
    assert "first question" in _texts(history) and "IN-FLIGHT" not in _texts(history)


def test_rebuild_replays_pdf_text_and_image(env):
    from agenticops.web.session_manager import _load_history_messages
    pk, sid = _session()
    pdf = _bound(pk, sid, "pdf", env)
    png = _bound(pk, sid, "png", env)
    _message(pk, "user", "compare these", attachments=[{"id": pdf, "filename": "sample-pdf.pdf"},
                                                      {"id": png, "filename": "sample-png.png"}])
    _message(pk, "assistant", "they differ")
    history = _load_history_messages(sid, 20)
    user = history[0]
    assert user["role"] == "user" and user["content"][0]["text"] == "compare these"
    assert TOKENS["pdf"] in _texts(history)
    assert sum("image" in b for b in user["content"]) == 1
    assert not any("document" in b for m in history for b in m["content"])


def test_rebuild_tolerates_legacy_attachment_json(env):
    from agenticops.web.session_manager import _load_history_messages
    pk, sid = _session()
    _message(pk, "user", "old upload", attachments=[{"filename": "a.txt", "size": 3, "type": "text"}])
    _message(pk, "assistant", "ok")
    history = _load_history_messages(sid, 20)
    assert history[0]["content"] == [{"text": "old upload"}]


def test_cleared_agent_cache_still_answers_from_attachments(env, monkeypatch):
    from unittest.mock import MagicMock
    from agenticops.web import session_manager
    pk, sid = _session()
    xlsx = _bound(pk, sid, "xlsx", env)
    _message(pk, "user", "what is in the sheet?", attachments=[{"id": xlsx, "filename": "sample-xlsx.xlsx"}])
    _message(pk, "assistant", "metrics")
    agent = MagicMock()
    agent.messages = []
    monkeypatch.setattr(session_manager, "create_main_agent", lambda **kw: agent)
    manager = session_manager.ChatSessionManager()
    assert manager.get_or_create(sid) is agent
    assert TOKENS["xlsx"] in _texts(agent.messages)


def test_delete_session_removes_rows_and_dir(env):
    from fastapi.testclient import TestClient
    from agenticops.chat.attachments import store
    from agenticops.models import ChatAttachment, get_db_session
    from agenticops.web.app import app
    monkeypatch_auth_off(env)
    pk, sid = _session()
    _bound(pk, sid, "docx", env)
    assert store.session_root(sid).is_dir()
    assert TestClient(app).delete(f"/api/chat/sessions/{sid}").status_code == 204
    deadline = __import__("time").monotonic() + 10
    while store.session_root(sid).exists() and __import__("time").monotonic() < deadline:
        __import__("time").sleep(0.05)
    assert not store.session_root(sid).exists()
    with get_db_session() as db:
        assert db.query(ChatAttachment).count() == 0


def monkeypatch_auth_off(env):
    settings.api_auth_enabled = False   # restored by the env fixture's monkeypatch on teardown


def test_delete_session_during_send_leaves_nothing(env, monkeypatch):
    import threading
    import time as _time
    from types import SimpleNamespace
    from fastapi.testclient import TestClient
    import agenticops.web.app as webapp
    from agenticops.chat.attachments import store
    from agenticops.models import ChatAttachment, get_db_session
    monkeypatch_auth_off(env)
    client = TestClient(webapp.app)
    pk, sid = _session()
    att_id = _stage("txt", actor=Actor("web", "anonymous"), tmp=env)

    class _Agent:
        model = SimpleNamespace(config={"model_id": "global.anthropic.claude-opus-5-5"})

        async def stream_async(self, content):
            yield {"data": "ok"}
    monkeypatch.setattr(webapp._chat_sessions, "get_or_create", lambda s, *a: _Agent())
    monkeypatch.setattr(webapp, "_generate_session_title", lambda *_a: None)
    entered, release = threading.Event(), threading.Event()
    real_move = store.move_into_session

    def slow_move(ids, session_uuid):
        entered.set()
        release.wait(10)
        real_move(ids, session_uuid)
    monkeypatch.setattr(store, "move_into_session", slow_move)
    result = {}

    def send():
        result["r"] = client.post(f"/api/chat/sessions/{sid}/messages", json={
            "content": "read it", "client_message_id": str(uuid.uuid4()), "attachment_ids": [att_id]})
    t = threading.Thread(target=send)
    t.start()
    assert entered.wait(10)
    assert client.delete(f"/api/chat/sessions/{sid}").status_code == 204
    release.set()
    t.join(30)
    assert result["r"].status_code == 200
    _time.sleep(0.2)
    assert not store.session_root(sid).exists()
    with get_db_session() as db:
        assert db.query(ChatAttachment).count() == 0


def test_startup_sweep_runs(env, monkeypatch):
    import asyncio
    from agenticops.chat.attachments import service
    calls = []
    monkeypatch.setattr(service, "sweep_staged", lambda now=None: calls.append(1) or 0)
    from agenticops.web.app import _sweep_chat_attachments_at_startup
    asyncio.run(_sweep_chat_attachments_at_startup())
    assert calls == [1]
