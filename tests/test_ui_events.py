"""MVP-2.9.0 N15: what happened in the last 24 hours, for the top bar's band and the map's replay.

One list from the record that already exists (pipeline_events): when an issue was found, when an agent started
and ended a piece of work, what a person decided, what happened to a change — each with its time and the work
item it belongs to. Pipeline internals (a critic's verdict, a gate's count, a notification) are not on it, a
note's text is never sent, and the list says when it was cut.
"""
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from starlette.testclient import TestClient

from agenticops.models import Base, ChangeRequest, CloudAccount, HealthIssue, PipelineEvent, get_session
from agenticops.services import ui_events as ue

NOW = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def db(tmp_path, monkeypatch):
    import agenticops.models as models_mod
    import agenticops.audit.models  # noqa: F401
    from agenticops.config import settings
    monkeypatch.setattr(models_mod, "_engine", None)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/events.db")
    Base.metadata.create_all(models_mod.get_engine())
    yield settings


def _issue(account_id=None):
    s = get_session()
    try:
        i = HealthIssue(title="t", description="d", severity="high", source="test", status="open", resource_id="i-1", account_id=account_id)
        s.add(i); s.commit()
        return i.id
    finally:
        s.close()


def _event(issue_id=None, *, change_id=None, type, actor="system", status="completed", detail=None, minutes_ago=10):
    s = get_session()
    try:
        e = PipelineEvent(health_issue_id=issue_id, change_request_id=change_id, event_type=type, stage="x", status=status,
                          detail=json.dumps(detail) if detail is not None else None, actor=actor,
                          created_at=NOW - timedelta(minutes=minutes_ago))
        s.add(e); s.commit()
        return e.id
    finally:
        s.close()


class TestKind:
    @pytest.mark.parametrize("type, actor, change, want", [
        ("issue_created", "system", None, "signal"),
        ("rca_started", "agent:rca", None, "agent"),
        ("rca_completed", "agent:rca", None, "agent"),
        ("fix_plan_created", "agent:sre", None, "agent"),
        ("fix_plan_updated", "agent:sre", None, "agent"),         # a draft rewritten in place is a plan written, too
        ("execution_completed", "agent:executor", None, "agent"),
        ("agent_run_abandoned", "system", None, "agent"),
        # what a person did is a decision, whatever the event is called …
        ("status_changed", "user:alice", None, "decision"),
        ("rca_started", "user:alice", None, "decision"),          # a person asked for the diagnosis
        ("fix_plan_requested", "web:anonymous", None, "decision"),
        ("change_approved", "user:alice", 3, "decision"),
        ("note_added", "cli:bob", None, "decision"),
        # … and so are the events that record one under another actor's name
        ("rca_human_feedback", "system", None, "decision"),
        ("execution_stop_requested", "system", None, "decision"),
        # a change's own course
        ("change_review_started", "system", 3, "change"),
        ("change_reviewed", "agent:sre", 3, "change"),
        ("execution_completed", "agent:executor", 3, "change"),
        # the pipeline's internals are not on the band
        ("signal_gated", "system", None, None),
        ("notification_sent", "system", None, None),
        ("policy_decision", "policy-engine", None, None),
        ("rca_critic", "system", None, None),
        ("rca_evidence_check", "system", None, None),
        ("status_changed", "agent:sre", None, None),              # the code moving a status: the event beside it says why
        ("something_new", "system", None, None),
    ])
    def test_each_event_is_one_of_four_kinds_or_not_on_the_band(self, type, actor, change, want):
        assert ue.kind_of(type, actor, change) == want


class TestRecent:
    def test_the_events_of_the_window_oldest_first_each_with_its_item(self, db):
        iid = _issue()
        _event(iid, type="issue_created", minutes_ago=23 * 60)
        _event(iid, type="rca_completed", actor="agent:rca", minutes_ago=60)
        _event(iid, type="status_changed", actor="user:alice", detail={"from": "fix_planned", "to": "fix_approved", "reason": "FixPlan #7 approved"}, minutes_ago=5)
        _event(iid, type="issue_created", minutes_ago=25 * 60)                    # before the window
        out = ue.recent_events(hours=24, now=NOW)
        assert [(e["kind"], e["type"], e["item"]) for e in out["events"]] == [
            ("signal", "issue_created", f"I{iid}"), ("agent", "rca_completed", f"I{iid}"), ("decision", "status_changed", f"I{iid}")]
        last = out["events"][-1]
        assert last["at"] == "2026-11-18T11:55:00Z" and last["actor"] == "user:alice" and last["status"] == "completed"
        assert last["detail"] == {"from": "fix_planned", "to": "fix_approved", "reason": "FixPlan #7 approved"}
        assert (out["total"], out["cut"], out["hours"]) == (3, False, 24)
        assert out["from"] == "2026-11-17T12:00:00Z" and out["to"] == "2026-11-18T12:00:00Z"

    def test_a_shorter_window(self, db):
        iid = _issue()
        _event(iid, type="issue_created", minutes_ago=5 * 60)
        _event(iid, type="rca_completed", actor="agent:rca", minutes_ago=30)
        assert [e["type"] for e in ue.recent_events(hours=1, now=NOW)["events"]] == ["rca_completed"]

    def test_what_is_not_on_the_band_is_not_sent_and_not_counted(self, db):
        iid = _issue()
        for t in ("signal_gated", "notification_sent", "rca_critic"):
            _event(iid, type=t)
        _event(iid, type="status_changed", actor="agent:sre", detail={"from": "a", "to": "b"})
        assert ue.recent_events(hours=24, now=NOW) | {"generated_at": None} == {
            "events": [], "total": 0, "cut": False, "hours": 24, "from": "2026-11-17T12:00:00Z", "to": "2026-11-18T12:00:00Z",
            "generated_at": None}

    def test_a_notes_text_is_never_sent_and_a_long_reason_is_cut(self, db):
        iid = _issue()
        _event(iid, type="note_added", actor="user:alice", status="recorded", detail={"content": "the customer called about this", "by": "user:alice"})
        _event(iid, type="status_changed", actor="user:alice", detail={"from": "open", "to": "dismissed", "reason": "x" * 900, "note": "y" * 900,
                                                                       "policy_decision": {"big": "blob"}}, minutes_ago=1)
        note, move = ue.recent_events(hours=24, now=NOW)["events"]
        assert note["type"] == "note_added" and note["detail"] == {}
        assert set(move["detail"]) == {"from", "to", "reason"} and len(move["detail"]["reason"]) == 200

    def test_a_change_s_events_carry_the_change(self, db):
        s = get_session()
        cr = ChangeRequest(title="c", description="d", requested_by="user:bob", status="planned")
        s.add(cr); s.commit(); cid = cr.id; s.close()
        _event(change_id=cid, type="change_review_started")
        _event(change_id=cid, type="change_approved", actor="user:alice", minutes_ago=2)
        assert [(e["kind"], e["item"]) for e in ue.recent_events(hours=24, now=NOW)["events"]] == [("change", f"C{cid}"), ("decision", f"C{cid}")]

    def test_only_the_newest_are_kept_when_there_are_too_many_and_the_answer_says_so(self, db, monkeypatch):
        monkeypatch.setattr(ue, "MAX_EVENTS", 3)
        iid = _issue()
        for n in range(5):
            _event(iid, type="rca_completed", actor="agent:rca", minutes_ago=50 - n * 10)   # 50, 40, 30, 20, 10 minutes ago
        out = ue.recent_events(hours=24, now=NOW)
        assert [e["at"][11:16] for e in out["events"]] == ["11:30", "11:40", "11:50"]     # the newest three, oldest first
        assert (out["total"], out["cut"]) == (5, True)

    def test_the_account_scope(self, db):
        s = get_session()
        a, b = CloudAccount(name="a", provider="aws", is_enabled=True), CloudAccount(name="b", provider="aws", is_enabled=True)
        s.add_all([a, b]); s.commit(); aid, bid = a.id, b.id
        cr = ChangeRequest(title="c", description="d", requested_by="user:bob", status="planned", account_id=bid)
        s.add(cr); s.commit(); cid = cr.id; s.close()
        mine, other, none = _issue(aid), _issue(bid), _issue(None)
        for iid in (mine, other, none):
            _event(iid, type="issue_created")
        _event(change_id=cid, type="change_review_started")
        assert [e["item"] for e in ue.recent_events(hours=24, account_id=aid, now=NOW)["events"]] == [f"I{mine}"]
        assert {e["item"] for e in ue.recent_events(hours=24, account_id=bid, now=NOW)["events"]} == {f"I{other}", f"C{cid}"}
        assert len(ue.recent_events(hours=24, now=NOW)["events"]) == 4

    def test_it_never_loads_more_rows_than_it_answers_with(self, db, monkeypatch):
        """Round-2 review C-M7: every row of the window was loaded and turned into a dict before the cut."""
        from sqlalchemy import event
        import agenticops.models as models_mod
        monkeypatch.setattr(ue, "MAX_EVENTS", 3)
        iid = _issue()
        for n in range(8):
            _event(iid, type="rca_completed", actor="agent:rca", minutes_ago=n + 1)
        _event(iid, type="status_changed", actor="agent:rca", minutes_ago=1)          # the code moving a status: not on the band
        _event(iid, type="status_changed", actor="user:alice", detail={"from": "open", "to": "dismissed"}, minutes_ago=2)
        fetched = []
        engine = models_mod.get_engine()

        def listener(conn, cur, stmt, params, ctx, many):
            if "LIMIT" in stmt.upper():
                fetched.append(stmt)
        event.listen(engine, "before_cursor_execute", listener)
        try:
            out = ue.recent_events(hours=24, now=NOW)
        finally:
            event.remove(engine, "before_cursor_execute", listener)
        assert fetched, "the rows are read with a LIMIT"
        assert (len(out["events"]), out["total"], out["cut"]) == (3, 9, True)         # 8 + the person's move; not the code's
        assert [e["kind"] for e in out["events"]].count("decision") == 1

    def test_it_costs_two_queries_whatever_the_number_of_events(self, db):
        from sqlalchemy import event
        import agenticops.models as models_mod
        iid = _issue()
        for n in range(30):
            _event(iid, type="rca_completed", actor="agent:rca", minutes_ago=n + 1)
        seen = []
        engine = models_mod.get_engine()
        listener = lambda conn, cur, stmt, params, ctx, many: seen.append(stmt)   # noqa: E731
        event.listen(engine, "before_cursor_execute", listener)
        try:
            ue.recent_events(hours=24, now=NOW)
        finally:
            event.remove(engine, "before_cursor_execute", listener)
        assert len([q for q in seen if q.lstrip().upper().startswith("SELECT")]) <= 2


@pytest.fixture
def client(db):
    from agenticops.web.app import app
    from agenticops.web.routers import ui as ui_router
    app.dependency_overrides[ui_router.signed_in_user] = lambda: SimpleNamespace(id=1, email="alice", is_admin=False, permissions=["read"])
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_the_route(client):
    iid = _issue()
    s = get_session()
    s.add(PipelineEvent(health_issue_id=iid, event_type="issue_created", stage="x", status="completed", actor="system",
                        created_at=datetime.now(timezone.utc) - timedelta(minutes=3)))
    s.commit(); s.close()
    body = client.get("/api/ui/events").json()
    assert [(e["kind"], e["item"]) for e in body["events"]] == [("signal", f"I{iid}")] and body["hours"] == 24
    assert body["events"][0]["at"].endswith("Z") and body["generated_at"].endswith("Z")
    assert client.get("/api/ui/events?hours=6").json()["hours"] == 6


@pytest.mark.parametrize("query", ["hours=0", "hours=25", "hours=x", "account_id=0"])
def test_the_route_checks_its_parameters(client, query):
    assert client.get(f"/api/ui/events?{query}").status_code == 422


def test_the_route_needs_a_signed_in_person(db):
    from agenticops.web.app import app
    app.dependency_overrides.clear()
    assert TestClient(app).get("/api/ui/events").status_code == 401
