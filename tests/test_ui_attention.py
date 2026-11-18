"""GET /api/ui/attention (MVP-2.7.0 S3): one row per work item that waits on a person, for this actor — the same
rules as the issue and change pages (services/work_phases), strict policy for who is expected to act."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import event
from starlette.testclient import TestClient

from agenticops.auth.actor import Actor
from agenticops.models import (Base, ChangeRequest, FixExecution, FixPlan, HealthIssue, PipelineEvent, RCAResult,
                               get_session)
from agenticops.services import attention as att
from agenticops.services import work_phases as wp

ADMIN = Actor("user", "root", 3, ("read", "write", "admin"))
ALICE = Actor("user", "alice", 1, ("read", "write"))
BOB = Actor("user", "bob", 2, ("read", "write"))
READER = Actor("user", "rita", 4, ("read",))
NOW = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)
PHASES = json.loads((Path(__file__).parent / "fixtures" / "work_item_phase_cases.json").read_text())


@pytest.fixture
def db(tmp_path, monkeypatch):
    import agenticops.models as models_mod
    import agenticops.audit.models  # noqa: F401
    from agenticops.config import settings
    monkeypatch.setattr(models_mod, "_engine", None)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/att.db")
    monkeypatch.setattr(settings, "change_management_enabled", True)
    monkeypatch.setattr(settings, "executor_enabled", True)
    monkeypatch.setattr(settings, "auto_fix_enabled", True)
    monkeypatch.setattr(settings, "rbac_enforce", False)
    monkeypatch.setattr(settings, "rca_min_confidence_for_autofix", 0.6)
    Base.metadata.create_all(models_mod.get_engine())
    yield settings


def _issue(status, *, plan=None, rca=0.9, run=None, account_id=None, title="t"):
    s = get_session()
    try:
        issue = HealthIssue(title=title, description="d", severity="low", source="test", status=status,
                            resource_id="i-1", account_id=account_id)
        s.add(issue); s.flush()
        r = None
        if rca is not None:
            r = RCAResult(health_issue_id=issue.id, root_cause="x", confidence=rca, critic_verdict="supported")
            s.add(r); s.flush()
        pid = None
        if plan is not None:
            p = FixPlan(health_issue_id=issue.id, rca_result_id=r.id if r else None, risk_level="L1", title="p",
                        summary="s", status=plan, approved_at=NOW - timedelta(minutes=5) if plan == "approved" else None)
            s.add(p); s.flush(); pid = p.id
        if run is not None:
            s.add(FixExecution(fix_plan_id=pid, health_issue_id=issue.id, status=run[0], verification_status=run[1],
                               created_at=NOW - timedelta(minutes=1)))
        s.commit()
        return issue.id, pid
    finally:
        s.close()


def _change(status, requested_by="user:alice"):
    s = get_session()
    try:
        cr = ChangeRequest(source="web", title="Tag web", description="d", status=status, requested_by=requested_by,
                           risk_level="L1")
        s.add(cr); s.flush()
        if status in ("planned", "approved", "needs_review"):
            s.add(FixPlan(plan_kind="change", change_request_id=cr.id, risk_level="L1", title="p", summary="s",
                          status={"planned": "pending_approval", "approved": "approved", "needs_review": "executed"}[status]))
        s.commit()
        return cr.id
    finally:
        s.close()


def _items(actor, **kw):
    return att.attention_page(actor, now=NOW, **kw)["items"]


def _row(actor, rid):
    return next((i for i in _items(actor) if i["id"] == rid), None)


def test_every_human_sub_has_a_row_mapping():
    for c in PHASES["issue"]:
        e = c["expect"]
        if e["waitingFor"] in wp.HUMAN and e["primary"]:
            assert e["sub"] in att.ISSUE_ROWS, c["name"]
    for c in PHASES["change"]:
        e = c["expect"]
        if e["waitingFor"] in wp.HUMAN and e["primary"]:
            assert e["sub"] in att.CHANGE_ROWS, c["name"]


def test_a_pending_plan_is_an_approval_row_to_its_plan_page(db):
    iid, pid = _issue("fix_planned", plan="pending_approval")
    row = _row(ADMIN, f"I{iid}")
    assert row["reason"] == "approval_required" and row["route"] == f"/app/plans/{pid}"
    assert row["entity"]["entity_type"] == "fix_plan" and row["entity"]["entity_id"] == pid
    assert row["available_actions"][0]["action"] == "approve"
    assert row["available_actions"][0]["effect"] == "approve_and_queue_execution"
    assert row["ref"] == f"I#{iid}"


def test_a_reader_is_not_expected_to_approve(db):
    iid, _ = _issue("fix_planned", plan="pending_approval")
    assert _row(READER, f"I{iid}") is None


def test_requester_never_sees_own_change_approval(db):
    cid = _change("planned", requested_by="user:alice")
    assert _row(ALICE, f"C{cid}") is None
    row = _row(BOB, f"C{cid}")
    assert row["reason"] == "approval_required" and row["route"] == f"/app/changes/{cid}#plan"


def test_clarification_belongs_to_the_requester_or_admins_when_none(db):
    cid = _change("needs_clarification", requested_by="user:alice")
    assert _row(ALICE, f"C{cid}")["reason"] == "clarification_required"
    assert _row(BOB, f"C{cid}") is None and _row(ADMIN, f"C{cid}") is None
    agent_cid = _change("needs_clarification", requested_by="agent:main")
    assert _row(ADMIN, f"C{agent_cid}") is not None and _row(BOB, f"C{agent_cid}") is None


def test_acceptance_failed_run_and_low_confidence_rows(db):
    acc, _ = _issue("fix_executed", plan="executed", run=("succeeded", "pending_acceptance"))
    failed, _ = _issue("root_cause_identified", plan="failed", run=("failed", None))
    low, _ = _issue("root_cause_identified", rca=0.3)
    high, _ = _issue("root_cause_identified", rca=0.9)
    rows = {i["id"]: i for i in _items(ADMIN)}
    assert (rows[f"I{acc}"]["reason"], rows[f"I{acc}"]["reason_detail"]) == ("verification_required", "acceptance")
    assert rows[f"I{acc}"]["route"].endswith("#accept")
    assert rows[f"I{failed}"]["reason"] == "execution_failed"
    assert (rows[f"I{low}"]["reason"], rows[f"I{low}"]["reason_detail"]) == ("review_required", "rca_gate")
    assert f"I{high}" not in rows   # gate passed: waits on the SRE agent


def test_approved_but_not_started_respects_the_grace_and_the_auto_run(db):
    iid, pid = _issue("fix_approved", plan="approved")   # approved 5 min before NOW, no run, no event
    assert _row(ADMIN, f"I{iid}")["reason"] == "execution_not_started"
    s = get_session()
    s.query(FixPlan).filter_by(id=pid).update({"approved_at": NOW - timedelta(seconds=10)})
    s.commit(); s.close()
    assert _row(ADMIN, f"I{iid}") is None   # inside the 30 s grace: the page says "checking"
    s = get_session()
    s.query(FixPlan).filter_by(id=pid).update({"approved_at": NOW - timedelta(minutes=5)})
    s.add(PipelineEvent(health_issue_id=iid, event_type="execution_started", stage="execution", status="started",
                        detail=json.dumps({"plan_id": pid}), created_at=NOW - timedelta(minutes=2)))
    s.commit(); s.close()
    assert _row(ADMIN, f"I{iid}") is None   # its auto-run is under way


def test_auto_fix_off_shows_not_started_after_grace(db):
    db.auto_fix_enabled = False
    iid, _ = _issue("fix_approved", plan="approved")
    assert _row(ADMIN, f"I{iid}")["reason"] == "execution_not_started"
    iid2, _ = _issue("fix_planned", plan="pending_approval")
    assert _row(ADMIN, f"I{iid2}")["available_actions"][0]["effect"] == "approve_only"


def test_executor_off_keeps_the_row_with_the_action_refused(db):
    db.executor_enabled = False
    cid = _change("approved", requested_by="user:alice")
    act = _row(BOB, f"C{cid}")["available_actions"][0]
    assert (act["action"], act["allowed"], act["reason_code"]) == ("execute", False, "executor_disabled")


def test_terminal_items_drop_out_and_one_row_per_work_item(db):
    _issue("resolved", plan="executed")
    _change("completed")
    iid, _ = _issue("fix_planned", plan="pending_approval")
    rows = _items(ADMIN)
    assert [r["id"] for r in rows] == [f"I{iid}"]


def test_account_filter_total_and_cursor(db):
    for n in range(3):
        _issue("fix_planned", plan="pending_approval", account_id=7)
    _issue("fix_planned", plan="pending_approval", account_id=8)
    page = att.attention_page(ADMIN, now=NOW, account_id=7, limit=2)
    assert page["total"] == 3 and len(page["items"]) == 2 and page["next_cursor"] == "2"
    rest = att.attention_page(ADMIN, now=NOW, account_id=7, limit=2, offset=2)
    assert len(rest["items"]) == 1 and rest["next_cursor"] is None


def test_change_management_off_hides_change_rows(db):
    db.change_management_enabled = False
    _change("planned", requested_by="user:alice")
    assert all(i["id"].startswith("I") for i in _items(BOB))


def test_no_audit_row_and_a_bounded_number_of_queries(db):
    for _ in range(10):
        _issue("fix_planned", plan="pending_approval")
        _issue("fix_approved", plan="approved")
        _change("planned")
    import agenticops.models as models_mod
    count = {"n": 0}
    def on_exec(*_a, **_k):
        count["n"] += 1
    with patch("agenticops.auth.authz._audit_denial") as audit:
        event.listen(models_mod.get_engine(), "before_cursor_execute", on_exec)
        try:
            att.attention_page(READER, now=NOW)
        finally:
            event.remove(models_mod.get_engine(), "before_cursor_execute", on_exec)
    audit.assert_not_called()
    assert count["n"] <= 10, count


def test_the_endpoint_shape_and_validation(db):
    from agenticops.web import deps
    from agenticops.web.app import app
    from agenticops.web.routers import ui as ui_router
    _issue("fix_planned", plan="pending_approval")
    app.dependency_overrides[deps.current_actor] = lambda: ADMIN
    app.dependency_overrides[ui_router.signed_in_user] = lambda: SimpleNamespace(id=3)
    try:
        c = TestClient(app)
        body = c.get("/api/ui/attention").json()
        assert set(body) == {"items", "total", "next_cursor", "generated_at", "counts"} and body["total"] == 1
        assert c.get("/api/ui/attention?limit=0").status_code == 422
        assert c.get("/api/ui/attention?cursor=abc").status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_auto_fix_off_hands_a_passing_rca_to_you(db):
    """Final review I4: with auto-fix off nothing asks the SRE agent for a plan, so a passing RCA waits on a person —
    worded as passing the gate, not as a human confirmation."""
    db.auto_fix_enabled = False
    iid, _ = _issue("root_cause_identified", rca=0.9)
    row = _row(ADMIN, f"I{iid}")
    assert (row["reason"], row["reason_detail"], row["route"]) == ("review_required", "rca_ready", f"/app/issues/{iid}#plan")
    db.auto_fix_enabled = True
    assert _row(ADMIN, f"I{iid}") is None


def test_a_not_started_plan_row_counts_toward_the_fix_plans_tab(db):
    """Deferred minor M3: the row's object is the approved plan (route stays on the issue's run card)."""
    iid, pid = _issue("fix_approved", plan="approved")
    row = _row(ADMIN, f"I{iid}")
    assert row["reason"] == "execution_not_started"
    assert (row["entity"]["entity_type"], row["entity"]["entity_id"]) == ("fix_plan", pid)
    assert row["route"] == f"/app/issues/{iid}#run"


# ── MVP-2.8.0 S2: the workbench's fields, filters, sort and counts ──────────────────────────────────────────────

def _anchor(iid, *, name="web-01", rtype="EC2", region="us-west-2", resource_id="i-abc"):
    from agenticops.models import CloudResource
    s = get_session()
    try:
        r = CloudResource(account_id=1, provider="aws", region=region, resource_type=rtype, resource_id=resource_id,
                          name=name, raw_data={})
        s.add(r); s.flush()
        s.query(HealthIssue).filter_by(id=iid).update({"resource_ref": r.id, "severity": "high", "account_id": 1})
        s.commit()
        return r.id
    finally:
        s.close()


def test_a_row_carries_severity_resource_region_and_who_it_waits_on(db):
    iid, _ = _issue("fix_planned", plan="pending_approval")
    ref = _anchor(iid)
    row = _row(ADMIN, f"I{iid}")
    assert row["severity"] == "high" and row["risk_level"] is None
    assert row["resource"] == {"ref": ref, "name": "web-01", "type": "EC2", "resource_id": "i-abc"}
    assert row["region"] == "us-west-2"
    assert row["waiting_on"] == "approver"
    cid = _change("planned", requested_by="user:alice")
    crow = _row(BOB, f"C{cid}")
    assert crow["risk_level"] == "L1" and crow["severity"] is None and crow["waiting_on"] == "approver"


def test_reason_filter_keeps_the_counts_of_every_reason(db):
    appr, _ = _issue("fix_planned", plan="pending_approval")
    acc, _ = _issue("fix_executed", plan="executed", run=("succeeded", "pending_acceptance"))
    page = att.attention_page(ADMIN, now=NOW, reason=["approval_required"])
    assert [i["id"] for i in page["items"]] == [f"I{appr}"] and page["total"] == 1
    assert page["counts"] == {"approval_required": 1, "verification_required": 1}


def test_search_by_ref_number_or_resource_name(db):
    iid, _ = _issue("fix_planned", plan="pending_approval", title="Disk full")
    other, _ = _issue("fix_planned", plan="pending_approval", title="Other")
    _anchor(iid, name="db-primary", resource_id="i-9f")
    for q in (f"I#{iid}", str(iid), "db-primary", "disk", "I-9F"):
        ids = [i["id"] for i in att.attention_page(ADMIN, now=NOW, q=q)["items"]]
        assert f"I{iid}" in ids and f"I{other}" not in ids, q


def test_waiting_longest_comes_first_by_default(db):
    newer, p1 = _issue("fix_planned", plan="pending_approval")
    older, p2 = _issue("fix_planned", plan="pending_approval")
    s = get_session()
    s.query(FixPlan).filter_by(id=p1).update({"updated_at": NOW - timedelta(minutes=5)})
    s.query(FixPlan).filter_by(id=p2).update({"updated_at": NOW - timedelta(hours=3)})
    s.commit(); s.close()
    assert [i["id"] for i in _items(ADMIN)][:2] == [f"I{older}", f"I{newer}"]
    assert [i["id"] for i in _items(ADMIN, sort="newest")][:2] == [f"I{newer}", f"I{older}"]


def test_issue_waits_gives_every_issue_its_phase_and_since(db):
    approved, pid = _issue("fix_approved", plan="approved")   # waits on the executor: not a human row
    s = get_session()
    try:
        issue = s.query(HealthIssue).filter_by(id=approved).one()
        waits = att.issue_waits(s, [issue], now=NOW)
    finally:
        s.close()
    w = waits[approved]
    assert w.phase.sub in ("notQueued", "executing") and w.since is not None


def test_waiting_since_is_never_before_the_issue_entered_its_present_status(db):
    """MVP-2.9.0: a reopened issue has not waited since its old diagnosis — it was dismissed in between. «Since» is
    never earlier than the issue's last status move (NewUI's «经过» page said «44 days» a minute after a reopen)."""
    iid, _ = _issue("open")
    other, _ = _issue("open")
    s = get_session()
    try:
        for rca in s.query(RCAResult).all():
            rca.created_at = NOW - timedelta(days=44)
        s.add(PipelineEvent(health_issue_id=iid, event_type="status_changed", stage="issue", status="completed",
                            detail=json.dumps({"from": "open", "to": "dismissed", "reason": "noise"}), actor="user:alice",
                            created_at=NOW - timedelta(days=3)))
        s.add(PipelineEvent(health_issue_id=iid, event_type="status_changed", stage="issue", status="completed",
                            detail=json.dumps({"from": "dismissed", "to": "open", "reason": "reopened"}), actor="user:alice",
                            created_at=NOW - timedelta(minutes=2)))
        s.add(PipelineEvent(health_issue_id=iid, event_type="note_added", stage="note", status="recorded",
                            detail=json.dumps({"content": "x"}), actor="user:alice", created_at=NOW - timedelta(minutes=1)))
        s.commit()
        waits = att.issue_waits(s, s.query(HealthIssue).order_by(HealthIssue.id).all(), now=NOW)
    finally:
        s.close()
    assert waits[iid].since == NOW - timedelta(minutes=2)       # the reopen — not the note after it, not the old RCA
    assert waits[other].since == NOW - timedelta(days=44)        # no move on record: as before


def test_the_endpoint_takes_reason_q_and_sort_and_refuses_an_unknown_reason(db):
    from agenticops.web import deps
    from agenticops.web.app import app
    from agenticops.web.routers import ui as ui_router
    _issue("fix_planned", plan="pending_approval")
    app.dependency_overrides[deps.current_actor] = lambda: ADMIN
    app.dependency_overrides[ui_router.signed_in_user] = lambda: SimpleNamespace(id=3)
    try:
        c = TestClient(app)
        assert c.get("/api/ui/attention?reason=approval_required&q=t&sort=severity").status_code == 200
        assert c.get("/api/ui/attention?reason=nope").status_code == 422
        assert c.get("/api/ui/attention?sort=random").status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_a_stale_resource_ref_of_another_account_shows_no_resource(db):
    """SQLite does not enforce ON DELETE SET NULL: a ref may point at a row another account now uses (health_overlay)."""
    iid, _ = _issue("fix_planned", plan="pending_approval")
    _anchor(iid)
    s = get_session()
    s.query(HealthIssue).filter_by(id=iid).update({"account_id": 2})
    s.commit(); s.close()
    row = _row(ADMIN, f"I{iid}")
    assert row["resource"] is None and row["region"] is None


def test_the_you_steps_need_the_write_flag(db):
    """S2 review: a «you» row (a verdict on a low-confidence RCA, a new plan after a failed run) is something a
    viewer cannot do — its workbench, top-bar count and Cases «mine» never list it."""
    low, _ = _issue("root_cause_identified", rca=0.3)
    failed, _ = _issue("root_cause_identified", plan="failed", run=("failed", None))
    assert {f"I{low}", f"I{failed}"} <= {i["id"] for i in _items(ADMIN)}
    assert _items(READER) == []
    viewer = Actor("user", "vera", 5, ("read",), read_only=True)
    page = att.attention_page(viewer, now=NOW)
    assert page["items"] == [] and page["total"] == 0 and page["counts"] == {}
    assert att.issue_rows(viewer, now=NOW) == []


# ── «在等我» (MVP-2.8.0): the to-do items grouped by the decision they need ──────────────────────────────────

DECISIONS = json.loads((Path(__file__).parent / "fixtures" / "attention_decision_groups.json").read_text())


def test_every_reason_has_a_decision_group():
    assert att.DECISION_GROUPS == tuple(DECISIONS["groups"])
    assert att.DECISION_OF == DECISIONS["reasons"]
    assert set(att.DECISION_OF) == att.REASONS


def test_decision_sort_groups_then_longest_wait(db):
    s = get_session()
    acc, _ = _issue("fix_executed", plan="executed", run=("succeeded", "pending_acceptance"))
    failed, _ = _issue("root_cause_identified", plan="failed", run=("failed", None))
    low, _ = _issue("root_cause_identified", rca=0.3)
    new_ap, p_new = _issue("fix_planned", plan="pending_approval")
    old_ap, p_old = _issue("fix_planned", plan="pending_approval")
    s.query(FixPlan).filter_by(id=p_new).update({"updated_at": NOW - timedelta(minutes=5)})
    s.query(FixPlan).filter_by(id=p_old).update({"updated_at": NOW - timedelta(hours=3)})
    s.commit(); s.close()
    clar = _change("needs_clarification", requested_by="user:root")
    rows = _items(ADMIN, sort="decision", limit=50)
    order = [i["id"] for i in rows]
    assert order.index(f"I{old_ap}") < order.index(f"I{new_ap}")          # approval: the longest wait first
    groups = [att.DECISION_OF[i["reason"]] for i in rows]
    assert groups == sorted(groups, key=att.DECISION_GROUPS.index)           # approval < acceptance < failed < confirm
    assert {f"I{acc}", f"I{failed}", f"I{low}", f"C{clar}"} <= set(order)


def test_decision_pages_only_append_to_the_last_group(db):
    for _ in range(3):
        _issue("fix_planned", plan="pending_approval")
    _issue("fix_executed", plan="executed", run=("succeeded", "pending_acceptance"))
    _issue("root_cause_identified", plan="failed", run=("failed", None))
    _issue("root_cause_identified", rca=0.3)
    every = _items(ADMIN, sort="decision", limit=50)
    pages, cursor = [], 0
    while True:
        page = att.attention_page(ADMIN, now=NOW, sort="decision", limit=2, offset=cursor)
        pages.append(page["items"])
        if page["next_cursor"] is None:
            break
        cursor = int(page["next_cursor"])
    assert [i["id"] for p in pages for i in p] == [i["id"] for i in every]
    rank = lambda i: att.DECISION_GROUPS.index(att.DECISION_OF[i["reason"]])
    for before, after in zip(pages, pages[1:]):
        assert rank(after[0]) >= rank(before[-1])


def test_the_endpoint_takes_sort_decision(db):
    from agenticops.web import deps
    from agenticops.web.app import app
    from agenticops.web.routers import ui as ui_router
    _issue("fix_planned", plan="pending_approval")
    app.dependency_overrides[deps.current_actor] = lambda: ADMIN
    app.dependency_overrides[ui_router.signed_in_user] = lambda: SimpleNamespace(id=3)
    try:
        c = TestClient(app)
        assert c.get("/api/ui/attention?sort=decision").status_code == 200
        assert c.get("/api/ui/attention?sort=x").status_code == 422
    finally:
        app.dependency_overrides.clear()


# ── NewUI (MVP-2.9.0): every row the queue can carry has a brief ─────────────────────────────────────────────

BRIEFS = json.loads((Path(__file__).parent / "fixtures" / "attention_brief_kinds.json").read_text())
_LISTED = {(r["kind"], r["reason"], r["reason_detail"]) for r in BRIEFS["rows"]}


def test_one_item_by_its_exact_id(db):
    """MVP-2.9.0: NewUI's «经过» page asks whether ONE item is on this actor's list (`item=I12`). The search (`q`)
    cannot answer that: it also matches titles, resources, and I#1 when asked for I#10's digits."""
    ids = [_issue("fix_planned", plan="pending_approval", title=f"issue {n}")[0] for n in range(12)]
    first, tenth = ids[0], ids[9]
    page = att.attention_page(ADMIN, now=NOW, item=f"I{first}")
    assert [i["id"] for i in page["items"]] == [f"I{first}"] and page["total"] == 1
    assert page["counts"] == {"approval_required": 1}
    assert [i["id"] for i in att.attention_page(ADMIN, now=NOW, item=f"I{tenth}")["items"]] == [f"I{tenth}"]
    cid = _change("planned", requested_by="user:alice")
    assert [i["id"] for i in att.attention_page(ADMIN, now=NOW, item=f"C{cid}")["items"]] == [f"C{cid}"]
    assert att.attention_page(ADMIN, now=NOW, item="I9999")["items"] == []        # not on the list: no row
    assert att.attention_page(READER, now=NOW, item=f"I{first}")["items"] == []   # nor one that waits on somebody else


def test_the_endpoint_takes_item_and_refuses_a_malformed_one(db):
    from agenticops.web import deps
    from agenticops.web.app import app
    from agenticops.web.routers import ui as ui_router
    _issue("fix_planned", plan="pending_approval")
    iid, _ = _issue("fix_planned", plan="pending_approval")      # the second one: without the filter, limit=1 gives the first
    app.dependency_overrides[deps.current_actor] = lambda: ADMIN
    app.dependency_overrides[ui_router.signed_in_user] = lambda: SimpleNamespace(id=3)
    try:
        c = TestClient(app)
        r = c.get(f"/api/ui/attention?item=I{iid}&limit=1")
        assert r.status_code == 200 and [i["id"] for i in r.json()["items"]] == [f"I{iid}"]
        for bad in ("12", "X12", "I0", "I1;drop", "I#1"):
            assert c.get("/api/ui/attention", params={"item": bad}).status_code == 422, bad
    finally:
        app.dependency_overrides.clear()


def _kind(item) -> str:
    """The work item behind a row, as NewUI reads it (newui/lib/briefKind.itemKind)."""
    return "change" if item["entity"]["entity_type"] == "change_request" else "issue"


def _emittable_rows() -> set:
    """Every (work item, reason, reason_detail) the rows can carry: the two tables, plus each detail _issue_items /
    _change_items assigns by hand — read from their source, so a new one cannot slip past this table."""
    import inspect
    import re
    rows = {("issue", r, d) for r, d, _a in att.ISSUE_ROWS.values()}
    rows |= {("change", r, d) for r, d, _a in att.CHANGE_ROWS.values()}
    for kind, fn, table in (("issue", att._issue_items, att.ISSUE_ROWS), ("change", att._change_items, att.CHANGE_ROWS)):
        src = inspect.getsource(fn)
        by_hand = re.findall(r'if phase\.sub == "(\w+)"[^\n]*:\n\s+detail = "(\w+)"', src)
        assert len(by_hand) == len(re.findall(r'\bdetail = ', src)), "a detail is assigned in a shape this test cannot read"
        rows |= {(kind, table[sub][0], detail) for sub, detail in by_hand}
    return rows


def test_every_row_the_queue_can_carry_is_listed_with_a_brief():
    assert _emittable_rows() == _LISTED
    assert len(BRIEFS["rows"]) == len(_LISTED)                                   # no row listed twice
    assert {r["brief"] for r in BRIEFS["rows"]} == set(BRIEFS["briefs"])         # every brief is used, none unknown
    assert len(BRIEFS["briefs"]) == len(set(BRIEFS["briefs"]))


def test_real_rows_are_in_the_brief_table(db):
    """Issues and changes side by side: what the endpoint returns maps into the table by the client's own rule."""
    _issue("fix_planned", plan="pending_approval")
    _issue("root_cause_identified", rca=0.3)
    _issue("root_cause_identified", rca=None)
    _issue("fix_executed", plan="executed", run=("succeeded", "pending_acceptance"))
    _change("draft")
    _change("planned", requested_by="user:bob")
    _change("needs_clarification")
    items = _items(ALICE, limit=100)
    seen = {(_kind(i), i["reason"], i["reason_detail"]) for i in items}
    assert seen <= _LISTED
    assert {("issue", "approval_required", None), ("issue", "review_required", "rca_gate"),
            ("issue", "review_required", "rca_missing"), ("issue", "verification_required", "acceptance"),
            ("change", "review_required", "change_draft"), ("change", "approval_required", None),
            ("change", "clarification_required", None)} <= seen


def test_a_run_a_person_stopped_comes_back_saying_so(db):
    """MVP-2.9.0 N9: the issue returns as «execution failed», and the row says a person stopped it — the brief then
    reads «you stopped this run», not «the run failed»."""
    issue_id, pid = _issue("root_cause_identified", plan="failed", run=("rolled_back", "failed"))
    assert _row(ALICE, f"I{issue_id}")["reason_detail"] == "run_failed"
    s = get_session()
    s.query(FixExecution).filter_by(fix_plan_id=pid).update({"stop_requested_at": NOW, "stop_requested_by": "user:alice"})
    s.commit(); s.close()
    row = _row(ALICE, f"I{issue_id}")
    assert (row["reason"], row["reason_detail"]) == ("execution_failed", "run_stopped")


# ── a diagnosis that stopped waits on a person (MVP-2.9.0 N11) ───────────────

def _rca_events(issue_id, *events):
    """(event_type, status, minutes before NOW) rows on the issue's timeline."""
    s = get_session()
    try:
        for event_type, status, ago in events:
            s.add(PipelineEvent(health_issue_id=issue_id, event_type=event_type, stage="rca", status=status,
                                created_at=NOW - timedelta(minutes=ago)))
        s.commit()
    finally:
        s.close()


@pytest.fixture
def no_claims():
    from agenticops.services import agent_runs
    agent_runs.clear()
    yield agent_runs
    agent_runs.clear()


def test_an_issue_whose_diagnosis_ended_without_a_result_waits_on_a_person(db, no_claims):
    """Until N11 it «waited on the RCA agent» for good: nothing was on it, and it was in nobody's queue."""
    stopped, _ = _issue("investigating", rca=None)
    _rca_events(stopped, ("rca_started", "started", 50), ("rca_completed", "failed", 35))
    row = _row(ALICE, f"I{stopped}")
    assert (row["reason"], row["reason_detail"], row["waiting_on"]) == ("review_required", "rca_stopped", "you")
    assert row["occurred_at"] == "2026-10-06T11:25:00Z"                         # it has waited since the diagnosis ended (35 min ago)
    assert row["available_actions"][0]["action"] == "rerun_rca" and row["route"] == f"/app/issues/{stopped}#diagnose"
    assert _row(READER, f"I{stopped}") is None                                  # a read-only account is not handed it


def test_the_other_issues_waiting_for_a_diagnosis_stay_where_they_were(db, no_claims):
    never, _ = _issue("open", rca=None)                                         # never diagnosed: not this rule's
    under_way, _ = _issue("investigating", rca=None)
    _rca_events(under_way, ("rca_completed", "failed", 40), ("rca_started", "started", 5))     # a newer one has started
    open_stopped, _ = _issue("open", rca=None)
    _rca_events(open_stopped, ("rca_completed", "failed", 20))
    ack_stopped, _ = _issue("acknowledged", rca=None)
    _rca_events(ack_stopped, ("rca_started", "started", 30), ("rca_completed", "failed", 15))
    got = {i["id"] for i in _items(ALICE)}
    assert got == {f"I{open_stopped}", f"I{ack_stopped}"}


def test_an_agent_on_the_issue_means_it_is_not_waiting_on_a_person(db, no_claims):
    iid, _ = _issue("investigating", rca=None)
    _rca_events(iid, ("rca_started", "started", 50), ("rca_completed", "failed", 35))
    run = no_claims.begin("rca", iid, "user:bob", now=NOW - timedelta(minutes=2))
    assert _row(ALICE, f"I{iid}") is None                                       # somebody asked again: it is being diagnosed
    no_claims.end(run)
    assert _row(ALICE, f"I{iid}") is not None


def test_a_claim_past_its_time_limit_does_not_hide_the_issue(db, no_claims, monkeypatch):
    """The watchdog gave up and said so on the timeline; the thread may still be alive. The claim is kept (the live
    page shows it as overdue) but the issue is handed to a person all the same."""
    monkeypatch.setattr(db, "rca_timeout_seconds", 900)
    iid, _ = _issue("investigating", rca=None)
    _rca_events(iid, ("rca_started", "started", 40), ("rca_completed", "failed", 25))
    no_claims.begin("rca", iid, no_claims.PIPELINE, now=NOW - timedelta(minutes=40))
    assert _row(ALICE, f"I{iid}")["reason_detail"] == "rca_stopped"


def test_the_stopped_rows_keep_the_queue_inside_its_query_bound(db, no_claims):
    for _ in range(10):
        iid, _ = _issue("investigating", rca=None)
        _rca_events(iid, ("rca_started", "started", 50), ("rca_completed", "failed", 35))
        _issue("open", rca=None)
        _issue("fix_planned", plan="pending_approval")
    import agenticops.models as models_mod
    count = {"n": 0}
    def on_exec(*_a, **_k):
        count["n"] += 1
    event.listen(models_mod.get_engine(), "before_cursor_execute", on_exec)
    try:
        page = att.attention_page(ALICE, now=NOW)
    finally:
        event.remove(models_mod.get_engine(), "before_cursor_execute", on_exec)
    assert sum(1 for i in page["items"] if i["reason_detail"] == "rca_stopped") == 10
    assert count["n"] <= 12, count


def test_the_issue_as_the_api_shows_it_says_its_diagnosis_stopped(db, no_claims):
    from agenticops.web import deps
    from agenticops.web.app import app
    stopped, _ = _issue("investigating", rca=None)
    _rca_events(stopped, ("rca_started", "started", 50), ("rca_completed", "failed", 35))
    running, _ = _issue("investigating", rca=None)
    s = get_session()        # the route reads the real clock: a diagnosis that began a minute ago is under way
    s.add(PipelineEvent(health_issue_id=running, event_type="rca_started", stage="rca", status="started",
                        created_at=datetime.now(timezone.utc) - timedelta(minutes=1)))
    s.commit(); s.close()
    app.dependency_overrides[deps.current_actor] = lambda: ALICE
    try:
        c = TestClient(app)
        one = c.get(f"/api/health-issues/{stopped}").json()
        assert (one["rca_stopped"], one["waiting_on"]) == (True, "you")
        other = c.get(f"/api/health-issues/{running}").json()
        assert (other["rca_stopped"], other["waiting_on"]) == (False, "rca_agent")
        rows = {r["id"]: r for r in c.get("/api/health-issues").json()["items"]}
        assert rows[stopped]["rca_stopped"] is True and rows[running]["rca_stopped"] is False
    finally:
        app.dependency_overrides.clear()


def test_a_diagnosis_that_started_and_never_ended_waits_on_a_person_once_its_limit_has_passed(db, no_claims, monkeypatch):
    """A run that died with its process leaves a start and no end. Measured on a copy of the local database: one
    issue had been «being diagnosed» for 79 days."""
    monkeypatch.setattr(db, "rca_timeout_seconds", 900)
    orphan, _ = _issue("investigating", rca=None)
    _rca_events(orphan, ("rca_started", "started", 60 * 24 * 79))
    young, _ = _issue("investigating", rca=None)
    _rca_events(young, ("rca_started", "started", 10))                          # inside its limit: under way
    assert {i["id"] for i in _items(ALICE)} == {f"I{orphan}"}
    row = _row(ALICE, f"I{orphan}")
    assert row["reason_detail"] == "rca_stopped"
    assert row["occurred_at"] == (NOW - timedelta(minutes=60 * 24 * 79) + timedelta(seconds=900)).isoformat().replace("+00:00", "Z")


def test_an_issue_reopened_after_its_diagnosis_is_not_a_stopped_diagnosis(db, no_claims):
    reopened, _ = _issue("open", rca=0.9)
    _rca_events(reopened, ("rca_started", "started", 60 * 24 * 40), ("rca_completed", "completed", 60 * 24 * 40 - 3))
    s = get_session()
    s.add(PipelineEvent(health_issue_id=reopened, event_type="status_changed", stage="issue", status="completed",
                        created_at=NOW - timedelta(hours=3)))                    # dismissed … and opened again 3 h ago
    s.commit(); s.close()
    assert _row(ALICE, f"I{reopened}") is None
    with_failure, _ = _issue("investigating", rca=None)
    _rca_events(with_failure, ("rca_started", "started", 50), ("rca_completed", "failed", 35))
    s = get_session()
    s.add(PipelineEvent(health_issue_id=with_failure, event_type="status_changed", stage="issue", status="completed",
                        created_at=NOW - timedelta(minutes=49)))                 # open → investigating as the diagnosis began
    s.commit(); s.close()
    assert _row(ALICE, f"I{with_failure}")["reason_detail"] == "rca_stopped"


# ── MVP-2.9.0 N14: an issue an agent is working on is not waiting on a person ─────────────────────────────────────
# N11 said so for one row (a diagnosis that stopped). It holds for every row: after «request changes» the plan
# agent is redoing the plan — until N14 the item sat in the person's queue as «the plan was sent back» for as long
# as that took, counted and with nothing to do; the same for «diagnose again» and «get a new plan».

def _sent_back(by="user:alice"):
    iid, pid = _issue("fix_planned", plan="rejected")
    s = get_session()
    try:
        plan = s.get(FixPlan, pid)
        plan.rejected_by, plan.rejection_reason, plan.rejected_at = by, "restart only the web tier", NOW - timedelta(minutes=10)
        s.commit()
    finally:
        s.close()
    return iid


def test_a_plan_being_redone_is_not_in_anyones_queue(db, no_claims):
    iid = _sent_back()
    assert _row(ALICE, f"I{iid}")["reason_detail"] == "plan_rejected"           # nobody is on it: a person decides what next
    run = no_claims.begin("sre", iid, "user:alice", now=NOW - timedelta(minutes=1))
    assert _row(ALICE, f"I{iid}") is None and _row(ADMIN, f"I{iid}") is None    # the plan agent is on it
    assert att.attention_page(ALICE, now=NOW)["total"] == 0                     # … and it does not count
    no_claims.end(run)
    assert _row(ALICE, f"I{iid}")["reason_detail"] == "plan_rejected"           # it ended without a new plan: back to a person


def test_who_it_waits_on_names_the_agent_that_is_on_it(db, no_claims):
    iid = _sent_back()
    no_claims.begin("sre", iid, "user:alice", now=NOW - timedelta(minutes=1))
    s = get_session()
    try:
        w = att.issue_waits(s, [s.get(HealthIssue, iid)], now=NOW)[iid]
    finally:
        s.close()
    assert (w.phase.sub, w.phase.waiting_for, w.phase.primary) == ("agentAtWork", "sre_agent", None)
    assert w.since == NOW - timedelta(minutes=1)                                # since the agent started


def test_every_kind_of_row_leaves_while_an_agent_is_on_its_issue(db, no_claims):
    approval, _ = _issue("fix_planned", plan="pending_approval")
    confirm, _ = _issue("root_cause_identified", rca=0.4)                       # below the gate: a person confirms
    failed, _ = _issue("root_cause_identified", plan="failed", run=("failed", "failed"))
    assert {i["id"] for i in _items(ALICE)} == {f"I{approval}", f"I{confirm}", f"I{failed}"}
    no_claims.begin("rca", approval, "user:bob", now=NOW)                       # its diagnosis is being redone: not the moment to approve
    no_claims.begin("rca", confirm, "user:bob", now=NOW)
    no_claims.begin("sre", failed, "user:bob", now=NOW)
    assert _items(ALICE) == []


def test_a_claim_past_its_limit_hides_nothing(db, no_claims, monkeypatch):
    monkeypatch.setattr(db, "rca_timeout_seconds", 900)
    iid = _sent_back()
    no_claims.begin("sre", iid, "user:alice", now=NOW - timedelta(minutes=16))
    assert _row(ALICE, f"I{iid}")["reason_detail"] == "plan_rejected"


def test_an_issue_that_waits_on_no_person_keeps_its_own_answer(db, no_claims):
    """The rule replaces only a PERSON's turn: an issue that is executing still says «the executor», whatever claim
    is on it."""
    iid, _ = _issue("fix_executing", plan="executing", run=("running", None))
    no_claims.begin("rca", iid, "user:bob", now=NOW)
    s = get_session()
    try:
        w = att.issue_waits(s, [s.get(HealthIssue, iid)], now=NOW)[iid]
    finally:
        s.close()
    assert w.phase.waiting_for == "executor"


def test_the_issue_list_says_the_agent_too(db, no_claims):
    from starlette.testclient import TestClient
    from agenticops.web import deps
    from agenticops.web.app import app
    iid = _sent_back()
    app.dependency_overrides[deps.current_actor] = lambda: ALICE
    try:
        client = TestClient(app)
        assert client.get(f"/api/health-issues/{iid}").json()["waiting_on"] == "you"
        no_claims.begin("sre", iid, "user:alice")
        assert client.get(f"/api/health-issues/{iid}").json()["waiting_on"] == "sre_agent"
        rows = client.get("/api/health-issues").json()["items"]
        assert next(r for r in rows if r["id"] == iid)["waiting_on"] == "sre_agent"
    finally:
        app.dependency_overrides.clear()
