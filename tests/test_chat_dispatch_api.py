"""One user message = one dispatch (MVP-2.7.0 S5): client_message_id makes a send safe to repeat — a finished one is
replayed, a running one (or a busy session) is refused, and nothing starts a second agent run. A turn runs bound to
the chat's account and starts with its context block; a cut-off reply is recorded as interrupted."""
import json
import uuid
from datetime import datetime, timezone

import pytest
from starlette.testclient import TestClient

from agenticops.models import Base, ChatMessage, ChatSession, CloudAccount, HealthIssue, get_session


@pytest.fixture
def env(tmp_path, monkeypatch):
    import agenticops.models as models_mod
    import agenticops.audit.models  # noqa: F401
    import agenticops.web.app as webapp
    from agenticops.config import settings
    monkeypatch.setattr(models_mod, "_engine", None)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/disp.db")
    Base.metadata.create_all(models_mod.get_engine())
    s = get_session()
    s.add_all([CloudAccount(id=1, name="prod", provider="aws", is_enabled=False, credentials={}),
               CloudAccount(id=2, name="lab", provider="aws", is_enabled=False, credentials={})])
    s.commit(); s.close()
    calls = {"n": 0, "content": None, "bound": "unset"}

    class _Agent:
        async def stream_async(self, content):
            from agenticops.run_context import get_run_context
            calls["n"] += 1
            calls["content"] = content
            calls["bound"] = get_run_context().bound_account_id
            yield {"data": "hello "}
            yield {"data": "world"}

    monkeypatch.setattr(webapp._chat_sessions, "get_or_create", lambda sid: _Agent())
    monkeypatch.setattr(webapp, "_generate_session_title", lambda *_a: None)
    yield TestClient(webapp.app), calls, webapp


def _session(account_id=None, etype=None, eid=None):
    s = get_session()
    try:
        now = datetime.now(timezone.utc)
        row = ChatSession(session_id=str(uuid.uuid4()), name="Chat 2026-10-07 10:00", created_at=now, updated_at=now,
                          last_activity_at=now, context_account_id=account_id, context_entity_type=etype,
                          context_entity_id=eid)
        s.add(row); s.commit()
        return row.session_id, row.id
    finally:
        s.close()


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


def _send(client, sid, cmid=None, content="hi"):
    return client.post(f"/api/chat/sessions/{sid}/messages",
                       json={"content": content, "client_message_id": cmid or str(uuid.uuid4())})


def _users(pk):
    s = get_session()
    try:
        return s.query(ChatMessage).filter_by(session_id=pk, role="user").order_by(ChatMessage.id).all()
    finally:
        s.close()


def test_missing_or_bad_client_id_is_422(env):
    client, calls, _ = env
    sid, _ = _session()
    assert client.post(f"/api/chat/sessions/{sid}/messages", json={"content": "hi"}).status_code == 422
    assert _send(client, sid, cmid="x").status_code == 422
    assert client.post(f"/api/chat/sessions/{sid}/messages", data={"content": "hi"}).status_code == 422
    assert calls["n"] == 0


def test_first_send_streams_accepted_first_and_done_with_ids(env):
    client, calls, _ = env
    sid, pk = _session()
    cmid = str(uuid.uuid4())
    r = _send(client, sid, cmid)
    assert r.status_code == 200
    fs = frames(r.text)
    assert fs[0][0] == "accepted" and fs[0][1]["client_message_id"] == cmid and fs[0][1]["user_message_id"]
    done = [d for e, d in fs if e == "done"][0]
    assert done["terminal_status"] == "completed" and done["user_message_id"] == fs[0][1]["user_message_id"]
    assert done["assistant_message_id"]
    [u] = _users(pk)
    assert (u.client_message_id, u.dispatch_state) == (cmid, "completed")
    assert calls["n"] == 1


def test_repeat_after_completion_replays_without_running(env):
    client, calls, _ = env
    sid, pk = _session()
    cmid = str(uuid.uuid4())
    _send(client, sid, cmid)
    fs = frames(_send(client, sid, cmid).text)
    assert calls["n"] == 1
    assert [e for e, _ in fs] == ["accepted", "text", "done"]
    assert fs[1][1]["token"] == "hello world" and fs[2][1]["replayed"] is True
    assert len(_users(pk)) == 1


def test_second_send_while_running_is_409(env):
    client, calls, webapp = env
    sid, pk = _session()
    cmid = str(uuid.uuid4())
    s = get_session()
    s.add(ChatMessage(session_id=pk, role="user", content="first", client_message_id=cmid, dispatch_state="running"))
    s.commit(); s.close()
    webapp._streaming_sessions.add(sid)
    try:
        r = _send(client, sid)
        assert r.status_code == 409 and r.json()["detail"]["code"] == "session_busy"
        r = _send(client, sid, cmid)
        assert r.status_code == 409 and r.json()["detail"]["code"] == "duplicate_in_flight"
    finally:
        webapp._streaming_sessions.discard(sid)
    assert calls["n"] == 0


def test_a_leftover_running_row_alone_also_means_busy(env):
    client, calls, _ = env
    sid, pk = _session()
    s = get_session()
    s.add(ChatMessage(session_id=pk, role="user", content="x", client_message_id=str(uuid.uuid4()), dispatch_state="accepted"))
    s.commit(); s.close()
    assert _send(client, sid).status_code == 409 and calls["n"] == 0


def test_concurrent_claims_create_one_message(env):
    from agenticops.services import chat_dispatch
    _, _, _ = env
    sid, pk = _session()
    cmid = str(uuid.uuid4())
    a, b = get_session(), get_session()
    try:
        row_a, row_b = a.get(ChatSession, pk), b.get(ChatSession, pk)
        first = chat_dispatch.claim(a, row_a, cmid, "hi", None, busy=False)
        a.commit()
        second = chat_dispatch.claim(b, row_b, cmid, "hi", None, busy=False)
        b.commit()
    finally:
        a.close(); b.close()
    assert first.kind == "new" and second.kind in ("in_flight", "replay")
    assert len(_users(pk)) == 1


def test_disconnect_marks_interrupted(env, monkeypatch):
    client, _, _ = env
    sid, pk = _session()

    async def _gone(self):
        return True
    monkeypatch.setattr("starlette.requests.Request.is_disconnected", _gone)
    _send(client, sid)
    [u] = _users(pk)
    assert u.dispatch_state == "interrupted"
    s = get_session()
    reply = s.query(ChatMessage).filter_by(session_id=pk, role="assistant").one()
    s.close()
    assert reply.dispatch_state == "interrupted"


def test_failure_marks_failed(env, monkeypatch):
    client, _, webapp = env
    sid, pk = _session()

    class _Boom:
        async def stream_async(self, _c):
            yield {"data": "par"}
            raise RuntimeError("kaput")
    monkeypatch.setattr(webapp._chat_sessions, "get_or_create", lambda s: _Boom())
    fs = frames(_send(client, sid).text)
    assert any(e == "error" for e, _ in fs)
    assert _users(pk)[0].dispatch_state == "failed"


def test_startup_sweep_marks_stale_interrupted(env):
    from agenticops.services import chat_dispatch
    _, pk = _session()
    s = get_session()
    for st in ("accepted", "running", "completed"):
        s.add(ChatMessage(session_id=pk, role="user", content=st, client_message_id=str(uuid.uuid4()), dispatch_state=st))
    s.commit(); s.close()
    assert chat_dispatch.interrupt_stale() == 2
    assert sorted(m.dispatch_state for m in _users(pk)) == ["completed", "interrupted", "interrupted"]


def test_turn_runs_with_bound_account(env):
    client, calls, _ = env
    sid, _ = _session(account_id=2)
    _send(client, sid)
    assert calls["bound"] == 2
    sid2, _ = _session()
    _send(client, sid2)
    assert calls["bound"] is None


def test_linked_chat_turn_starts_with_the_context_block(env):
    client, calls, _ = env
    s = get_session()
    i = HealthIssue(title="cpu high", description="d", severity="high", source="manual", status="open",
                    resource_id="i-1", account_id=2)
    s.add(i); s.commit(); iid = i.id; s.close()
    sid, _ = _session(account_id=2, etype="health_issue", eid=iid)
    _send(client, sid, content="what now?")
    assert calls["content"].startswith("This conversation is bound to account lab")
    assert f'<linked_issue ref="I#{iid}">' in calls["content"] and calls["content"].rstrip().endswith("what now?")


def test_first_send_locks_the_context(env):
    client, _, _ = env
    sid, _ = _session(account_id=1)
    assert client.get(f"/api/chat/sessions/{sid}").json()["context"]["scope_locked"] is False
    _send(client, sid)
    assert client.get(f"/api/chat/sessions/{sid}").json()["context"]["scope_locked"] is True


def test_messages_list_shows_dispatch_state(env):
    client, _, _ = env
    sid, _ = _session()
    cmid = str(uuid.uuid4())
    _send(client, sid, cmid)
    msgs = client.get(f"/api/chat/sessions/{sid}/messages").json()["messages"]
    user = next(m for m in msgs if m["role"] == "user")
    assert (user["client_message_id"], user["dispatch_state"]) == (cmid, "completed")


def test_bootstrap_says_context_chat(env):
    from agenticops.web.routers.ui import _features
    assert _features()["context_chat"] is True
