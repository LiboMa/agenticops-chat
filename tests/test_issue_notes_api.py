"""Append-only notes on an issue (MVP-2.7.0 S4): stored in the request's own transaction as the session actor, shown in
the timeline, gated by issue.note; GET /api/health-issues/{id} says whether you may add one."""
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from agenticops.auth.actor import Actor
from agenticops.models import Base, HealthIssue, PipelineEvent, get_session

WRITER = Actor("user", "alice", 1, ("read", "write"))
READER = Actor("user", "rita", 2, ("read",))


@pytest.fixture
def client(tmp_path, monkeypatch):
    import agenticops.models as models_mod
    import agenticops.audit.models  # noqa: F401
    from agenticops.config import settings
    from agenticops.web.app import app
    monkeypatch.setattr(models_mod, "_engine", None)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/notes.db")
    Base.metadata.create_all(models_mod.get_engine())
    yield TestClient(app)
    app.dependency_overrides.clear()


def _as(actor):
    from agenticops.web import deps
    from agenticops.web.app import app
    app.dependency_overrides[deps.current_actor] = lambda: actor


def _issue(status="open"):
    s = get_session()
    try:
        i = HealthIssue(title="t", description="d", severity="high", source="manual", status=status, resource_id="r")
        s.add(i); s.commit()
        return i.id
    finally:
        s.close()


def _notes(iid):
    s = get_session()
    try:
        return s.query(PipelineEvent).filter_by(health_issue_id=iid, event_type="note_added").all()
    finally:
        s.close()


def test_a_note_is_recorded_as_the_session_actor(client):
    iid = _issue(); _as(WRITER)
    r = client.post(f"/api/health-issues/{iid}/notes", json={"content": "  checked the LB  "})
    assert r.status_code == 201, r.text
    body = r.json()
    assert (body["health_issue_id"], body["content"], body["actor"]) == (iid, "checked the LB", "user:alice")
    assert body["event_id"] and body["created_at"]
    timeline = client.get(f"/api/health-issues/{iid}/timeline").json()
    note = [e for e in timeline if e["event_type"] == "note_added"]
    assert len(note) == 1 and note[0]["actor"] == "user:alice" and note[0]["detail"]["content"] == "checked the LB"


def test_the_body_cannot_claim_an_author(client):
    iid = _issue(); _as(WRITER)
    assert client.post(f"/api/health-issues/{iid}/notes", json={"content": "x", "actor": "user:mallory"}).status_code == 422
    assert _notes(iid) == []


@pytest.mark.parametrize("content", ["", "   ", "a" * 8001, "bad\x00byte", "bell\x07"])
def test_bad_content_is_refused(client, content):
    iid = _issue(); _as(WRITER)
    assert client.post(f"/api/health-issues/{iid}/notes", json={"content": content}).status_code == 422
    assert _notes(iid) == []


def test_text_is_kept_as_written(client):
    iid = _issue(); _as(WRITER)
    text = "line one\n\tindented <script>alert(1)</script> — 中文"
    assert client.post(f"/api/health-issues/{iid}/notes", json={"content": text}).json()["content"] == text


def test_missing_issue_is_404(client):
    _as(WRITER)
    assert client.post("/api/health-issues/999/notes", json={"content": "x"}).status_code == 404


def test_a_reader_is_refused_under_enforce_and_audited_in_shadow(client):
    from agenticops.audit.models import AuditLog
    from agenticops.config import settings
    iid = _issue(); _as(READER)
    with patch.object(settings, "rbac_enforce", True):
        assert client.post(f"/api/health-issues/{iid}/notes", json={"content": "x"}).status_code == 403
    assert _notes(iid) == []
    with patch.object(settings, "rbac_enforce", False):
        assert client.post(f"/api/health-issues/{iid}/notes", json={"content": "x"}).status_code == 201
    s = get_session()
    assert s.query(AuditLog).filter_by(action="authz.denied_shadow").count() >= 1
    s.close()


def test_the_detail_says_whether_you_may_note(client):
    from agenticops.config import settings
    iid = _issue(); _as(WRITER)
    acts = client.get(f"/api/health-issues/{iid}").json()["available_actions"]
    assert {"action": "note", "allowed": True, "reason_code": None, "effect": "update"} in acts
    _as(READER)
    with patch.object(settings, "rbac_enforce", True):
        note = next(a for a in client.get(f"/api/health-issues/{iid}").json()["available_actions"] if a["action"] == "note")
    assert (note["allowed"], note["reason_code"]) == (False, "forbidden")


def test_a_note_does_not_move_the_issue(client):
    iid = _issue(status="fix_planned"); _as(WRITER)
    client.post(f"/api/health-issues/{iid}/notes", json={"content": "x"})
    s = get_session()
    assert s.get(HealthIssue, iid).status == "fix_planned"
    s.close()
