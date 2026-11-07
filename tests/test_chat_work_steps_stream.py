"""The chat work log (2026-11-07): each tool step streams and stores where it sits in the reply text (text_offset /
text_end), a redacted one-line summary of its input (the tool_input frame), its duration and a redacted result
preview. An enhanced_task (Claude Code) is ONE step: its inner tools are not steps, its text stays with it."""
import asyncio
import json
import uuid
from datetime import datetime, timezone

import pytest
from starlette.testclient import TestClient

from agenticops.models import Base, ChatMessage, ChatSession, get_session


@pytest.fixture
def env(tmp_path, monkeypatch):
    import agenticops.models as models_mod
    import agenticops.audit.models  # noqa: F401
    import agenticops.web.app as webapp
    from agenticops.config import settings
    monkeypatch.setattr(models_mod, "_engine", None)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/steps.db")
    Base.metadata.create_all(models_mod.get_engine())
    monkeypatch.setattr(webapp, "_generate_session_title", lambda *_a: None)
    yield TestClient(webapp.app), webapp


def _session():
    s = get_session()
    try:
        now = datetime.now(timezone.utc)
        row = ChatSession(session_id=str(uuid.uuid4()), name="Chat 2026-11-07 10:00", created_at=now, updated_at=now,
                          last_activity_at=now)
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


def _send(client, sid):
    return client.post(f"/api/chat/sessions/{sid}/messages",
                       json={"content": "hi", "client_message_id": str(uuid.uuid4())})


def _reply(pk):
    s = get_session()
    try:
        return s.query(ChatMessage).filter_by(session_id=pk, role="assistant").one()
    finally:
        s.close()


def _stream(data):
    return {"type": "tool_stream", "tool_stream_event": {"tool_use": {"toolUseId": "t5"}, "data": data}}


def test_offsets_summary_duration_and_preview_are_streamed_and_stored(env, monkeypatch):
    client, webapp = env
    sid, pk = _session()

    class _A:
        async def stream_async(self, _c):
            yield {"data": "Let me check. "}                                   # 14 chars
            yield {"current_tool_use": {"toolUseId": "t1", "name": "run_kubectl", "input": ""}}
            yield {"current_tool_use": {"toolUseId": "t1", "name": "run_kubectl", "input": "{\"comm"}}
            yield {"message": {"role": "assistant", "content": [
                {"text": "Let me check. "},
                {"toolUse": {"toolUseId": "t1", "name": "run_kubectl",
                             "input": {"command": "kubectl get ns --token=abcdef123456"}}}]}}
            yield {"message": {"role": "user", "content": [{"toolResult": {
                "toolUseId": "t1", "status": "success", "content": [{"text": "default\nkube-system"}]}}]}}
            yield {"data": "Two namespaces."}
    monkeypatch.setattr(webapp._chat_sessions, "get_or_create", lambda s: _A())
    fs = frames(_send(client, sid).text)
    start = next(d for e, d in fs if e == "tool_start")
    inp = next(d for e, d in fs if e == "tool_input")
    end = next(d for e, d in fs if e == "tool_end")
    assert start["text_offset"] == 14
    assert inp == {"call_id": "t1", "summary": "kubectl get ns --token=[REDACTED-SECRET]"}
    assert end["text_end"] == 14 and end["result_preview"] == "default kube-system" and end["duration_ms"] >= 0
    reply = _reply(pk)
    tc = reply.tool_calls[0]
    assert (tc["text_offset"], tc["text_end"], tc["summary"], tc["result_preview"]) == (
        14, 14, "kubectl get ns --token=[REDACTED-SECRET]", "default kube-system")
    assert isinstance(tc["duration_ms"], int)
    assert "abcdef123456" not in json.dumps(reply.tool_calls)
    assert reply.content == "Let me check. Two namespaces."


def test_a_tool_with_no_result_ends_unknown_at_its_start(env, monkeypatch):
    client, webapp = env
    sid, pk = _session()

    class _A:
        async def stream_async(self, _c):
            yield {"data": "abc"}
            yield {"current_tool_use": {"toolUseId": "t9", "name": "sre_query", "input": ""}}
            yield {"data": "def"}
    monkeypatch.setattr(webapp._chat_sessions, "get_or_create", lambda s: _A())
    fs = frames(_send(client, sid).text)
    end = next(d for e, d in fs if e == "tool_end")
    assert end["outcome"] == "unknown" and end["text_end"] == 3 and end["result_preview"] == ""
    tc = _reply(pk).tool_calls[0]
    assert (tc["outcome"], tc["text_offset"], tc["text_end"], tc["result_preview"]) == ("unknown", 3, 3, "")
    assert isinstance(tc["duration_ms"], int)


def test_enhanced_inner_tools_are_not_steps(env, monkeypatch):
    client, webapp = env
    sid, pk = _session()

    class _A:
        async def stream_async(self, _c):
            yield {"current_tool_use": {"toolUseId": "t5", "name": "enhanced_task", "input": ""}}
            yield _stream({"kind": "tool_start", "tool_name": "Read"})
            yield _stream({"kind": "text", "text": "inner"})
            yield _stream({"kind": "tool_end", "tool_name": "Read"})
            yield {"message": {"role": "user", "content": [{"toolResult": {
                "toolUseId": "t5", "status": "success", "content": [{"text": "done"}]}}]}}
            yield {"data": "Final"}
    monkeypatch.setattr(webapp._chat_sessions, "get_or_create", lambda s: _A())
    fs = frames(_send(client, sid).text)
    assert not [d for e, d in fs if e in ("tool_start", "tool_end") and d.get("name") == "Read"]
    assert [d["token"] for e, d in fs if e == "text"] == ["inner", "Final"]
    reply = _reply(pk)
    assert [t["name"] for t in reply.tool_calls] == ["enhanced_task"]
    assert (reply.tool_calls[0]["text_offset"], reply.tool_calls[0]["text_end"]) == (0, len("inner"))
    assert reply.content == "innerFinal"


def test_a_step_is_timed_from_when_it_runs_not_from_when_the_model_began_writing_it(env, monkeypatch):
    # a batch of calls: the model writes them all (here: 0.4 s), then they run; each step's duration and its place on
    # the turn's clock (started_ms) start when its input is complete
    client, webapp = env
    sid, pk = _session()

    class _A:
        async def stream_async(self, _c):
            yield {"current_tool_use": {"toolUseId": "t1", "name": "list_health_issues", "input": ""}}
            await asyncio.sleep(0.4)
            yield {"message": {"role": "assistant", "content": [
                {"toolUse": {"toolUseId": "t1", "name": "list_health_issues", "input": {"severity": "high"}}}]}}
            yield {"message": {"role": "user", "content": [{"toolResult": {
                "toolUseId": "t1", "status": "success", "content": [{"text": "[]"}]}}]}}
            yield {"data": "none"}
    monkeypatch.setattr(webapp._chat_sessions, "get_or_create", lambda s: _A())
    fs = frames(_send(client, sid).text)
    end = next(d for e, d in fs if e == "tool_end")
    assert end["duration_ms"] < 300
    tc = _reply(pk).tool_calls[0]
    assert tc["duration_ms"] < 300 and isinstance(tc["started_ms"], int) and tc["started_ms"] >= 300


def test_offsets_count_utf16_units_like_the_browser(env, monkeypatch):
    # an emoji outside the BMP is one Python code point but two UTF-16 units (String.slice in the browser)
    client, webapp = env
    sid, pk = _session()

    class _A:
        async def stream_async(self, _c):
            yield {"data": "🔍 Found 🔴 api down. Checking logs:"}
            yield {"current_tool_use": {"toolUseId": "t1", "name": "sre_query", "input": ""}}
            yield {"message": {"role": "user", "content": [{"toolResult": {
                "toolUseId": "t1", "status": "success", "content": [{"text": "ok"}]}}]}}
            yield {"data": "Root cause: x"}
    monkeypatch.setattr(webapp._chat_sessions, "get_or_create", lambda s: _A())
    frames(_send(client, sid).text)
    tc = _reply(pk).tool_calls[0]
    narration = "🔍 Found 🔴 api down. Checking logs:"
    assert tc["text_offset"] == len(narration.encode("utf-16-le")) // 2 == tc["text_end"]
