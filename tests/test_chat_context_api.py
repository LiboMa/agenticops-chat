"""A chat's context (MVP-2.7.0 S5): a linked issue or change and the account the chat is bound to — resolved and
checked on the server (a linked object's account is its own), locked at the first sent message."""
from datetime import datetime, timezone

import pytest
from starlette.testclient import TestClient

from agenticops.auth.actor import Actor
from agenticops.models import Base, ChangeRequest, ChatSession, CloudAccount, HealthIssue, get_session

ADMIN = Actor("user", "admin", 1, ("read", "write", "admin"))


@pytest.fixture
def client(tmp_path, monkeypatch):
    import agenticops.models as models_mod
    import agenticops.audit.models  # noqa: F401
    from agenticops.config import settings
    from agenticops.web import deps
    from agenticops.web.app import app
    monkeypatch.setattr(models_mod, "_engine", None)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/ctx.db")
    Base.metadata.create_all(models_mod.get_engine())
    s = get_session()
    s.add_all([CloudAccount(id=1, name="prod", provider="aws", is_enabled=False, credentials={}),
               CloudAccount(id=2, name="lab", provider="aws", is_enabled=False, credentials={})])
    s.commit(); s.close()
    app.dependency_overrides[deps.current_actor] = lambda: ADMIN
    yield TestClient(app)
    app.dependency_overrides.clear()


def _issue(account_id=2, region="ap-southeast-1"):
    s = get_session()
    try:
        i = HealthIssue(title="cpu high", description="d", severity="high", source="manual", status="open",
                        resource_id="i-1", account_id=account_id, metric_data={"region": region} if region else {})
        s.add(i); s.commit()
        return i.id
    finally:
        s.close()


def _change(account_id=1):
    s = get_session()
    try:
        c = ChangeRequest(title="rotate keys", description="d", requested_by="user:admin", status="draft",
                          account_id=account_id)
        s.add(c); s.commit()
        return c.id
    finally:
        s.close()


def _create(client, context):
    return client.post("/api/chat/sessions", json={"context": context} if context is not None else {})


def test_linked_issue_takes_its_own_account_and_region(client):
    iid = _issue()
    r = _create(client, {"primary": {"entity_type": "health_issue", "entity_id": iid}})
    assert r.status_code == 201, r.text
    assert r.json()["context"] == {
        "primary": {"entity_type": "health_issue", "entity_id": iid, "ref": f"I#{iid}", "title": "cpu high"},
        "account_id": 2, "account_name": "lab", "region": "ap-southeast-1", "scope_locked": False}


def test_linked_change_takes_its_account(client):
    cid = _change()
    ctx = _create(client, {"primary": {"entity_type": "change_request", "entity_id": cid}}).json()["context"]
    assert (ctx["primary"]["ref"], ctx["account_id"], ctx["account_name"]) == (f"C#{cid}", 1, "prod")


def test_client_account_that_differs_from_the_object_is_409(client):
    iid = _issue()
    r = _create(client, {"primary": {"entity_type": "health_issue", "entity_id": iid}, "account_id": 1})
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "context_account_mismatch"
    s = get_session(); assert s.query(ChatSession).count() == 0; s.close()


def test_the_same_account_as_the_object_is_fine(client):
    iid = _issue()
    assert _create(client, {"primary": {"entity_type": "health_issue", "entity_id": iid}, "account_id": 2}).status_code == 201


def test_missing_object_is_404(client):
    r = _create(client, {"primary": {"entity_type": "health_issue", "entity_id": 999}})
    assert r.status_code == 404 and r.json()["detail"]["code"] == "context_not_found"


@pytest.mark.parametrize("ctx", [
    {"primary": {"entity_type": "report", "entity_id": 1}},
    {"primary": {"entity_type": "health_issue", "entity_id": 1, "extra": 1}},
    {"primary": None, "account_id": 1, "owner": "x"},
    {"primary": None, "account_id": 0},
    {"primary": None, "region": "r" * 81},
])
def test_bad_context_is_422(client, ctx):
    assert _create(client, ctx).status_code == 422


def test_free_chat_with_an_account(client):
    ctx = _create(client, {"primary": None, "account_id": 1}).json()["context"]
    assert (ctx["primary"], ctx["account_id"], ctx["account_name"]) == (None, 1, "prod")
    r = _create(client, {"primary": None, "account_id": 99})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "unknown_account"


def test_no_context_is_an_unbound_free_chat(client):
    assert _create(client, None).json()["context"] == {
        "primary": None, "account_id": None, "account_name": None, "region": None, "scope_locked": False}


def test_object_without_account_leaves_the_chat_unbound(client):
    iid = _issue(account_id=None, region=None)
    ctx = _create(client, {"primary": {"entity_type": "health_issue", "entity_id": iid}}).json()["context"]
    assert ctx["account_id"] is None and ctx["primary"]["entity_id"] == iid


def test_patch_context_before_lock_is_allowed_after_lock_409(client):
    sid = _create(client, None).json()["session_id"]
    r = client.patch(f"/api/chat/sessions/{sid}", json={"context": {"primary": None, "account_id": 2}})
    assert r.status_code == 200 and r.json()["context"]["account_id"] == 2
    s = get_session()
    s.query(ChatSession).filter_by(session_id=sid).update({"context_locked_at": datetime.now(timezone.utc)})
    s.commit(); s.close()
    r = client.patch(f"/api/chat/sessions/{sid}", json={"context": {"primary": None, "account_id": 1}})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "context_locked"
    assert client.get(f"/api/chat/sessions/{sid}").json()["context"]["scope_locked"] is True


def test_patch_without_context_does_not_touch_it(client):
    sid = _create(client, {"primary": None, "account_id": 2}).json()["session_id"]
    assert client.patch(f"/api/chat/sessions/{sid}", json={"pinned": True}).json()["context"]["account_id"] == 2


def test_list_and_get_carry_the_context(client):
    iid = _issue()
    sid = _create(client, {"primary": {"entity_type": "health_issue", "entity_id": iid}}).json()["session_id"]
    assert client.get(f"/api/chat/sessions/{sid}").json()["context"]["primary"]["ref"] == f"I#{iid}"
    row = next(r for r in client.get("/api/chat/sessions").json() if r["session_id"] == sid)
    assert row["context"]["account_name"] == "lab"
