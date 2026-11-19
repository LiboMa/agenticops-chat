"""MVP-2.9.0 N22 (the 2.8.0 spec's S5): GET /api/chat/sessions is `{items, total, next_cursor}` — the view, the
search and the order are the server's (pinned first BEFORE the cut), and each row says what is going on in it."""
import inspect
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from starlette.testclient import TestClient

from agenticops.auth.actor import Actor
from agenticops.models import Base, ChangeRequest, ChatMessage, ChatSession, CloudAccount, HealthIssue, get_session

ALICE = Actor("user", "alice@example.com", 1, ("read", "write"))
BOB = Actor("user", "bob@example.com", 2, ("read", "write"))
T0 = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def env(tmp_path, monkeypatch):
    import agenticops.audit.models  # noqa: F401
    import agenticops.models as models_mod
    from agenticops.config import settings
    from agenticops.web import app as app_mod
    from agenticops.web import deps
    monkeypatch.setattr(models_mod, "_engine", None)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/sessions.db")
    monkeypatch.setattr(settings, "api_auth_enabled", True)
    monkeypatch.setattr(settings, "rbac_enforce", False)
    monkeypatch.setattr(app_mod, "_streaming_sessions", set())
    monkeypatch.setattr(app_mod, "_claimed_dispatches", {})
    Base.metadata.create_all(models_mod.get_engine())
    who = {"actor": ALICE}
    app_mod.app.dependency_overrides[deps.current_actor] = lambda: who["actor"]
    client = TestClient(app_mod.app)

    def as_(actor):
        who["actor"] = actor
        return client
    yield SimpleNamespace(client=client, as_=as_, app=app_mod)
    app_mod.app.dependency_overrides.pop(deps.current_actor, None)


def _session(name="s", minutes=0, **kw):
    s = get_session()
    try:
        at = T0 + timedelta(minutes=minutes)
        row = ChatSession(session_id=str(uuid.uuid4()), name=name, created_at=at, updated_at=at, last_activity_at=at, **kw)
        s.add(row)
        s.commit()
        return SimpleNamespace(pk=row.id, sid=row.session_id)
    finally:
        s.close()


def _message(pk, role="user", **kw):
    s = get_session()
    try:
        s.add(ChatMessage(session_id=pk, role=role, content=kw.pop("content", "x"), **kw))
        s.commit()
    finally:
        s.close()


def _names(client, query=""):
    r = client.get(f"/api/chat/sessions{query}")
    assert r.status_code == 200, r.text
    return [i["name"] for i in r.json()["items"]]


def test_the_list_is_items_a_total_and_a_cursor(env):
    for n in range(3):
        _session(f"s{n}", minutes=n)
    out = env.client.get("/api/chat/sessions").json()
    assert set(out) == {"items", "total", "all_total", "next_cursor"}
    assert ([i["name"] for i in out["items"]], out["total"], out["all_total"], out["next_cursor"]) == (["s2", "s1", "s0"], 3, 3, None)
    assert {"activity", "waiting_on_you", "message_count", "context"} <= set(out["items"][0])


def test_a_pinned_session_is_first_however_old_also_beyond_the_first_page(env):
    """The defect: the newest 50 were cut first and sorted after — an older pinned session vanished."""
    _session("old and pinned", minutes=-500, pinned=True)
    for n in range(60):
        _session(f"s{n:02d}", minutes=n)
    out = env.client.get("/api/chat/sessions?limit=50").json()
    assert out["items"][0]["name"] == "old and pinned" and out["items"][1]["name"] == "s59"
    assert (len(out["items"]), out["total"]) == (50, 61)


def test_the_cursor_walks_the_whole_list_without_a_gap_or_a_repeat(env):
    for n in range(7):
        _session(f"s{n}", minutes=n, pinned=(n == 2))
    seen, cursor, pages = [], None, 0
    while True:
        out = env.client.get(f"/api/chat/sessions?limit=3{'&cursor=' + cursor if cursor else ''}").json()
        seen += [i["name"] for i in out["items"]]
        pages += 1
        assert out["total"] == 7
        cursor = out["next_cursor"]
        if cursor is None:
            break
    assert seen == ["s2", "s6", "s5", "s4", "s3", "s1", "s0"] and pages == 3
    for bad in ("abc", "-1", "1.5"):
        assert env.client.get(f"/api/chat/sessions?cursor={bad}").status_code == 422, bad


def test_the_three_views(env):
    _session("plain", minutes=1)
    _session("star", minutes=2, starred=True)
    _session("gone", minutes=3, archived=True)
    _session("gone star", minutes=4, archived=True, starred=True)
    assert _names(env.client) == ["star", "plain"]                              # all = not archived
    assert _names(env.client, "?view=all") == ["star", "plain"]
    assert _names(env.client, "?view=starred") == ["star"]
    assert _names(env.client, "?view=archived") == ["gone star", "gone"]        # the archive is found again here
    assert env.client.get("/api/chat/sessions?view=archived").json()["total"] == 2
    assert env.client.get("/api/chat/sessions?view=deleted").status_code == 422


def test_search_reads_the_name_the_linked_object_and_the_account(env):
    s = get_session()
    s.add_all([CloudAccount(id=1, name="prod-eu", provider="aws"),
               HealthIssue(id=12, resource_id="i-1", severity="high", source="t", title="Nginx 5xx storm", description="",
                           status="open", issue_type="other"),
               ChangeRequest(id=3, title="Rotate the TLS certificate", description="", requested_by="user:a", status="draft"),
               ChangeRequest(id=12, title="Resize the pool", description="", requested_by="user:a", status="draft")])
    s.commit()
    s.close()
    _session("Morning check", minutes=1)
    _session("about the issue", minutes=2, context_entity_type="health_issue", context_entity_id=12, context_account_id=1)
    _session("about the change", minutes=3, context_entity_type="change_request", context_entity_id=3)
    _session("100% cpu", minutes=4)
    _session("about change twelve", minutes=0, context_entity_type="change_request", context_entity_id=12)
    assert _names(env.client, "?q=MORNING") == ["Morning check"]                # the name, any case
    assert _names(env.client, "?q=nginx") == ["about the issue"]                # the linked issue's title
    assert _names(env.client, "?q=certificate") == ["about the change"]         # the linked change's title
    assert _names(env.client, "?q=prod-eu") == ["about the issue"]              # the account's name
    assert _names(env.client, "?q=I%2312") == ["about the issue"]               # the reference: issue 12, not change 12
    assert _names(env.client, "?q=c3") == ["about the change"]
    assert _names(env.client, "?q=C%2312") == ["about change twelve"]
    assert _names(env.client, "?q=12") == ["about the issue", "about change twelve"]   # a bare number: either kind
    assert _names(env.client, "?q=%25") == ["100% cpu"]                         # % is a character
    out = env.client.get("/api/chat/sessions?q=about").json()
    assert (out["total"], out["all_total"], len(out["items"])) == (3, 5, 3)     # «3 match · 5 in all»


def test_search_stays_inside_the_view(env):
    _session("report draft", minutes=1)
    _session("report old", minutes=2, archived=True)
    assert _names(env.client, "?q=report") == ["report draft"]
    assert _names(env.client, "?q=report&view=archived") == ["report old"]
    _session("another", minutes=3)
    out = env.client.get("/api/chat/sessions?q=report").json()
    assert (out["total"], out["all_total"]) == (1, 2)                           # all_total: this view, without the search
    assert env.client.get("/api/chat/sessions?q=zzz&view=archived").json()["all_total"] == 1


def test_a_row_says_what_is_going_on_in_it(env):
    quiet = _session("quiet", minutes=1)
    _message(quiet.pk, dispatch_state="completed")
    _message(quiet.pk, role="assistant", tool_calls=[{"name": "t", "outcome": "ok"}])
    live = _session("live", minutes=2)
    _message(live.pk, dispatch_state="running")
    cut = _session("cut off", minutes=3)
    _message(cut.pk, dispatch_state="interrupted")
    dead = _session("left open", minutes=4)
    _message(dead.pk, dispatch_state="running")                 # nothing in this process runs it
    tool = _session("tool failed", minutes=5)
    _message(tool.pk, dispatch_state="completed")
    _message(tool.pk, role="assistant", tool_calls=[{"name": "a", "outcome": "ok"}, {"name": "b", "outcome": "error"}])
    healed = _session("failed then fine", minutes=6)
    _message(healed.pk, dispatch_state="failed")
    _message(healed.pk, role="assistant", content="", dispatch_state="failed")
    _message(healed.pk, dispatch_state="completed")
    _message(healed.pk, role="assistant", tool_calls=[{"name": "a", "outcome": "ok"}])
    both = _session("failed send after a failed tool", minutes=7)
    _message(both.pk, dispatch_state="completed")
    _message(both.pk, role="assistant", tool_calls=[{"name": "b", "outcome": "error"}])
    _message(both.pk, dispatch_state="failed")
    empty = _session("no message yet", minutes=8)
    env.app._streaming_sessions.add(live.sid)
    got = {i["name"]: i["activity"] for i in env.client.get("/api/chat/sessions").json()["items"]}
    assert got == {"quiet": None, "live": "generating", "cut off": "failed", "left open": "failed",
                   "tool failed": "tool_failed", "failed then fine": None,
                   "failed send after a failed tool": "failed", "no message yet": None}
    assert empty.pk


def test_a_session_about_an_item_that_waits_on_me_says_so(env, monkeypatch):
    calls = []

    def fake_items(actor, **kw):
        calls.append(actor.key)
        return [{"id": "I12"}, {"id": "C3"}]
    monkeypatch.setattr("agenticops.services.attention.attention_items", fake_items)
    _session("free", minutes=1)
    assert env.client.get("/api/chat/sessions").json()["items"][0]["waiting_on_you"] is False
    assert calls == []                                          # nothing is linked: the to-do list is not read
    _session("mine", minutes=2, context_entity_type="health_issue", context_entity_id=12)
    _session("also mine", minutes=3, context_entity_type="change_request", context_entity_id=3)
    _session("someone else's", minutes=4, context_entity_type="health_issue", context_entity_id=99)
    got = {i["name"]: i["waiting_on_you"] for i in env.client.get("/api/chat/sessions").json()["items"]}
    assert got == {"free": False, "mine": True, "also mine": True, "someone else's": False}
    assert calls == [ALICE.key]


def test_only_what_the_caller_may_see_is_listed_or_counted(env):
    _session("everyone's", minutes=1)
    _session("alice's", minutes=2, owner_user_id=1, visibility="private")
    mine = env.as_(ALICE).get("/api/chat/sessions").json()
    assert ([i["name"] for i in mine["items"]], mine["total"]) == (["alice's", "everyone's"], 2)
    theirs = env.as_(BOB).get("/api/chat/sessions").json()
    assert ([i["name"] for i in theirs["items"]], theirs["total"]) == (["everyone's"], 1)
    assert env.as_(BOB).get("/api/chat/sessions?q=alice").json()["total"] == 0


def test_the_counts_and_the_context_are_still_there(env):
    s = get_session()
    s.add(HealthIssue(id=12, resource_id="i-1", severity="high", source="t", title="Nginx 5xx", description="",
                      status="open", issue_type="other"))
    s.commit()
    s.close()
    row = _session("with two", minutes=1, context_entity_type="health_issue", context_entity_id=12)
    _message(row.pk)
    _message(row.pk, role="assistant")
    item = env.client.get("/api/chat/sessions").json()["items"][0]
    assert item["message_count"] == 2 and item["context"]["primary"]["ref"] == "I#12"


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "q=" + "x" * 201])
def test_what_cannot_be_read_is_refused(env, query):
    assert env.client.get(f"/api/chat/sessions?{query}").status_code == 422


def test_the_handler_is_a_plain_function():
    from agenticops.web import app as app_mod
    assert not inspect.iscoroutinefunction(app_mod.api_list_chat_sessions)
