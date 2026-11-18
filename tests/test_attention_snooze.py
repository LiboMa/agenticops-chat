"""MVP-2.9.0 N14: «later» — a person puts one of their waiting items at the end of its group for a while.

It changes nothing about the item: it still waits on them, still counts, and is still on the list — only its place,
only for them, only for the time the setting gives, and only as long as it waits for the SAME thing (a plan that
was snoozed and then replaced by a new plan is a new matter and is back in its place at once).
"""
from datetime import timedelta

import pytest
from starlette.testclient import TestClient

from agenticops.models import AttentionSnooze, FixPlan, get_session
from agenticops.services import attention as att
from agenticops.services import attention_snooze as snz
from tests.test_ui_attention import ALICE, BOB, NOW, _change, _issue, db  # noqa: F401  (db is a fixture)


def _page(actor, user_id, **kw):
    return att.attention_page(actor, now=kw.pop("now", NOW), snooze_user_id=user_id, **kw)


def _ids(page):
    return [i["id"] for i in page["items"]]


def _rows():
    s = get_session()
    try:
        return [(r.user_id, r.item) for r in s.query(AttentionSnooze).order_by(AttentionSnooze.id)]
    finally:
        s.close()


class TestSituation:
    def test_it_is_the_reason_the_entity_and_its_version(self):
        item = {"reason": "approval_required", "reason_detail": None,
                "entity": {"entity_type": "fix_plan", "entity_id": 7, "content_version": 2}}
        assert snz.situation(item) == "approval_required||fix_plan:7|2"
        item = {"reason": "review_required", "reason_detail": "rca_gate",
                "entity": {"entity_type": "health_issue", "entity_id": 12, "content_version": None}}
        assert snz.situation(item) == "review_required|rca_gate|health_issue:12|"


class TestSnooze:
    def test_a_waiting_item_is_snoozed_for_the_configured_time(self, db, monkeypatch):
        monkeypatch.setattr(db, "attention_snooze_minutes", 60)
        iid, _ = _issue("fix_planned", plan="pending_approval")
        got = snz.snooze(1, ALICE, f"I{iid}", now=NOW)
        assert got == {"item": f"I{iid}", "snoozed_until": "2026-10-06T13:00:00Z"}
        row = _page(ALICE, 1)["items"][0]
        assert row["id"] == f"I{iid}" and row["snoozed_until"] == "2026-10-06T13:00:00Z"

    def test_an_item_that_does_not_wait_on_the_person_cannot_be_snoozed(self, db):
        iid, _ = _issue("investigating")
        assert snz.snooze(1, ALICE, f"I{iid}", now=NOW) is None
        assert snz.snooze(1, ALICE, "I99999", now=NOW) is None
        assert _rows() == []

    def test_it_is_only_for_the_person_who_snoozed(self, db):
        iid, _ = _issue("fix_planned", plan="pending_approval")
        snz.snooze(1, ALICE, f"I{iid}", now=NOW)
        assert _page(BOB, 2)["items"][0]["snoozed_until"] is None
        assert _page(ALICE, None)["items"][0]["snoozed_until"] is None      # no user known: nothing is marked

    def test_it_ends_by_itself(self, db, monkeypatch):
        monkeypatch.setattr(db, "attention_snooze_minutes", 60)
        iid, _ = _issue("fix_planned", plan="pending_approval")
        snz.snooze(1, ALICE, f"I{iid}", now=NOW)
        assert _page(ALICE, 1, now=NOW + timedelta(minutes=59))["items"][0]["snoozed_until"] is not None
        assert _page(ALICE, 1, now=NOW + timedelta(minutes=60))["items"][0]["snoozed_until"] is None

    def test_it_ends_when_the_item_waits_for_something_else(self, db):
        """The snooze was of «approve plan #1 v1». The plan is replaced: the new one is back in its place."""
        iid, pid = _issue("fix_planned", plan="pending_approval")
        snz.snooze(1, ALICE, f"I{iid}", now=NOW)
        s = get_session()
        old = s.get(FixPlan, pid); old.status = "rejected"; old.rejected_by = "agent:policy"
        s.add(FixPlan(health_issue_id=iid, rca_result_id=old.rca_result_id, risk_level="L1", title="p2", summary="s",
                      status="pending_approval"))
        s.commit(); s.close()
        row = _page(ALICE, 1)["items"][0]
        assert row["reason"] == "approval_required" and row["entity"]["entity_id"] != pid and row["snoozed_until"] is None

    def test_snoozing_again_starts_the_time_again_and_keeps_one_row(self, db, monkeypatch):
        monkeypatch.setattr(db, "attention_snooze_minutes", 60)
        iid, _ = _issue("fix_planned", plan="pending_approval")
        snz.snooze(1, ALICE, f"I{iid}", now=NOW)
        got = snz.snooze(1, ALICE, f"I{iid}", now=NOW + timedelta(minutes=30))
        assert got["snoozed_until"] == "2026-10-06T13:30:00Z" and _rows() == [(1, f"I{iid}")]

    def test_taking_it_back(self, db):
        iid, _ = _issue("fix_planned", plan="pending_approval")
        snz.snooze(1, ALICE, f"I{iid}", now=NOW)
        assert snz.unsnooze(1, f"I{iid}") is True and snz.unsnooze(1, f"I{iid}") is False
        assert _page(ALICE, 1)["items"][0]["snoozed_until"] is None and _rows() == []

    def test_rows_that_ended_are_swept_when_the_person_snoozes_next(self, db, monkeypatch):
        monkeypatch.setattr(db, "attention_snooze_minutes", 60)
        a, _ = _issue("fix_planned", plan="pending_approval")
        b, _ = _issue("fix_planned", plan="pending_approval")
        snz.snooze(1, ALICE, f"I{a}", now=NOW)
        snz.snooze(2, BOB, f"I{a}", now=NOW)
        snz.snooze(1, ALICE, f"I{b}", now=NOW + timedelta(hours=2))
        assert _rows() == [(2, f"I{a}"), (1, f"I{b}")]                      # hers that ended is gone; his is his to sweep

    def test_a_change_can_be_snoozed_too(self, db):
        cid = _change("planned", requested_by="user:bob")
        got = snz.snooze(1, ALICE, f"C{cid}", now=NOW)
        assert got is not None and _page(ALICE, 1)["items"][0]["snoozed_until"] == got["snoozed_until"]


class TestOrder:
    def _three(self):
        return [f"I{_issue('fix_planned', plan='pending_approval')[0]}" for _ in range(3)]

    def test_a_snoozed_item_goes_to_the_end_of_its_severity_only_when_asked(self, db):
        a, b, c = self._three()
        snz.snooze(1, ALICE, a, now=NOW)
        plain = _ids(_page(ALICE, 1, sort="severity"))
        assert _ids(_page(ALICE, 1, sort="severity", snoozed_last=True)) == [x for x in plain if x != a] + [a]
        assert _ids(att.attention_page(ALICE, now=NOW, sort="severity")) == plain   # the classic list: its order is untouched

    def test_it_stays_inside_its_own_severity(self, db):
        a, b, c = self._three()
        s = get_session()
        from agenticops.models import HealthIssue
        s.get(HealthIssue, int(a[1:])).severity = "critical"
        s.commit(); s.close()
        snz.snooze(1, ALICE, a, now=NOW)
        order = _ids(_page(ALICE, 1, sort="severity", snoozed_last=True))
        assert order[0] == a and set(order[1:]) == {b, c}                   # still ahead of every lower severity

    def test_the_counts_do_not_change(self, db):
        a, b, c = self._three()
        before = _page(ALICE, 1)
        snz.snooze(1, ALICE, a, now=NOW)
        after = _page(ALICE, 1, snoozed_last=True)
        assert (after["total"], after["counts"]) == (before["total"], before["counts"])

    def test_marking_costs_one_query(self, db):
        from sqlalchemy import event
        import agenticops.models as models_mod
        self._three()
        snz.snooze(1, ALICE, "I1", now=NOW)
        seen = []
        engine = models_mod.get_engine()
        listener = lambda conn, cur, stmt, params, ctx, many: seen.append(stmt)   # noqa: E731
        event.listen(engine, "before_cursor_execute", listener)
        try:
            att.attention_page(ALICE, now=NOW)
            base = len(seen); seen.clear()
            _page(ALICE, 1)
        finally:
            event.remove(engine, "before_cursor_execute", listener)
        assert len(seen) == base + 1


# ── the routes ────────────────────────────────────────────────────────────────

@pytest.fixture
def client(db):
    from types import SimpleNamespace
    from agenticops.web import deps
    from agenticops.web.app import app
    from agenticops.web.routers import ui as ui_router
    who = {"actor": ALICE, "user": SimpleNamespace(id=1, email="alice", is_admin=False, permissions=["read", "write"])}
    app.dependency_overrides[deps.current_actor] = lambda: who["actor"]
    app.dependency_overrides[ui_router.signed_in_user] = lambda: who["user"]
    c = TestClient(app)
    c.who = who
    yield c
    app.dependency_overrides.clear()


def test_the_route_snoozes_and_the_page_carries_it(client):
    iid, _ = _issue("fix_planned", plan="pending_approval")
    r = client.post("/api/ui/attention/snooze", json={"item": f"I{iid}"})
    assert r.status_code == 200 and r.json()["item"] == f"I{iid}" and r.json()["snoozed_until"].endswith("Z")
    page = client.get("/api/ui/attention?sort=severity&snoozed=last").json()
    assert page["items"][0]["snoozed_until"] == r.json()["snoozed_until"]


def test_an_item_that_is_not_on_the_persons_list_is_409(client):
    iid, _ = _issue("investigating")
    r = client.post("/api/ui/attention/snooze", json={"item": f"I{iid}"})
    assert r.status_code == 409 and r.json()["code"] == "not_waiting"


@pytest.mark.parametrize("body", [{}, {"item": "X1"}, {"item": "I0"}, {"item": "I12; drop"}, {"item": 12}])
def test_the_item_is_an_issue_or_a_change_ref(client, body):
    assert client.post("/api/ui/attention/snooze", json=body).status_code == 422


def test_delete_takes_it_back_and_is_idempotent(client):
    iid, _ = _issue("fix_planned", plan="pending_approval")
    client.post("/api/ui/attention/snooze", json={"item": f"I{iid}"})
    assert client.delete(f"/api/ui/attention/snooze?item=I{iid}").status_code == 204
    assert client.delete(f"/api/ui/attention/snooze?item=I{iid}").status_code == 204
    assert client.get("/api/ui/attention").json()["items"][0]["snoozed_until"] is None
    assert client.delete("/api/ui/attention/snooze?item=nope").status_code == 422


def test_another_persons_snooze_is_not_mine(client):
    from types import SimpleNamespace
    iid, _ = _issue("fix_planned", plan="pending_approval")
    client.post("/api/ui/attention/snooze", json={"item": f"I{iid}"})
    client.who["actor"], client.who["user"] = BOB, SimpleNamespace(id=2, email="bob", is_admin=False, permissions=["read", "write"])
    assert client.get("/api/ui/attention").json()["items"][0]["snoozed_until"] is None
    assert client.delete(f"/api/ui/attention/snooze?item=I{iid}").status_code == 204       # his: nothing to take back
    client.who["actor"], client.who["user"] = ALICE, SimpleNamespace(id=1, email="alice", is_admin=False, permissions=["read", "write"])
    assert client.get("/api/ui/attention").json()["items"][0]["snoozed_until"] is not None  # hers is still there


def test_the_order_parameter_is_checked(client):
    assert client.get("/api/ui/attention?snoozed=first").status_code == 422
