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
        assert set(body) == {"items", "total", "next_cursor", "generated_at"} and body["total"] == 1
        assert c.get("/api/ui/attention?limit=0").status_code == 422
        assert c.get("/api/ui/attention?cursor=abc").status_code == 422
    finally:
        app.dependency_overrides.clear()
