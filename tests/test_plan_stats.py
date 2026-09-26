"""Plans & changes statistics (MVP-2.6.0, Plan B Task 12): services/plan_stats_service + GET /api/plans/stats."""

from datetime import date, datetime, timedelta, timezone

import pytest
from starlette.testclient import TestClient

from agenticops.models import (
    Base, ChangeRequest, CloudAccount, CommandAudit, FixExecution, FixPlan, HealthIssue, RCAResult, get_session,
)


@pytest.fixture
def db(tmp_path, monkeypatch):
    import agenticops.models as models_mod
    import agenticops.audit.models  # noqa: F401
    from agenticops.config import settings
    monkeypatch.setattr(models_mod, "_engine", None)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/stats.db")
    Base.metadata.create_all(models_mod.get_engine())
    s = get_session()
    yield s
    s.close()


def _seed(db):
    from agenticops.audit.models import AuditLog
    now = datetime.now(timezone.utc)
    issue = HealthIssue(title="t", description="d", severity="low", source="t", status="resolved", resource_id="r"); db.add(issue); db.flush()
    rca = RCAResult(health_issue_id=issue.id, root_cause="x", confidence=0.9); db.add(rca); db.flush()
    fp = FixPlan(health_issue_id=issue.id, rca_result_id=rca.id, risk_level="L1", title="fix", summary="s", status="executed",
                 approved_by="agent:auto-pipeline", approved_at=now - timedelta(hours=1), created_at=now - timedelta(hours=2))
    db.add(fp); db.flush()
    db.add(FixExecution(fix_plan_id=fp.id, health_issue_id=issue.id, status="succeeded", executed_by="agent:executor",
                        started_at=now - timedelta(minutes=50), completed_at=now - timedelta(minutes=45), duration_ms=300000))
    cr1 = ChangeRequest(title="tag", description="d", requested_by="user:alice", status="completed", risk_level="L1",
                        effective_change_type="standard", action_type="tag", account_id=None,
                        requested_at=now - timedelta(hours=3), approved_at=now - timedelta(hours=2), approved_by="user:bob",
                        created_at=now - timedelta(hours=3), closed_at=now - timedelta(hours=1))
    cr2 = ChangeRequest(title="sg", description="d", requested_by="user:alice", status="planned", risk_level="L2",
                        effective_change_type="normal", action_type="network", created_at=now - timedelta(minutes=30))
    cr3 = ChangeRequest(title="old", description="d", requested_by="user:carol", status="failed", risk_level="L1",
                        created_at=now - timedelta(days=40), closed_at=now - timedelta(days=40))
    db.add_all([cr1, cr2, cr3]); db.flush()
    cp = FixPlan(plan_kind="change", change_request_id=cr1.id, risk_level="L1", title="cp", summary="s", status="executed",
                 approved_by="user:bob", approved_at=now - timedelta(hours=2), created_at=now - timedelta(hours=3))
    db.add(cp); db.flush()
    db.add(FixExecution(fix_plan_id=cp.id, status="succeeded", executed_by="user:bob", started_at=now - timedelta(hours=1, minutes=50),
                        completed_at=now - timedelta(hours=1), duration_ms=120000))
    db.add(AuditLog(action="change.approved", entity_type="change_request", entity_id=str(cr1.id), actor="user:bob"))
    # change_service.approve echoes every change approval onto its change plan — one decision, two rows
    db.add(AuditLog(action="plan.approved", entity_type="fix_plan", entity_id=str(cp.id), actor="user:bob",
                    details={"plan_kind": "change", "change_request_id": cr1.id}))
    db.add(AuditLog(action="plan.approved", entity_type="fix_plan", entity_id=str(fp.id), actor="agent:auto-pipeline"))
    db.add(AuditLog(action="authz.denied_shadow", entity_type="change_request", entity_id=str(cr1.id), actor="user:alice"))
    db.add(CommandAudit(actor="agent:executor", tool="run_aws_cli", tier="write", command="aws ec2 create-tags", outcome="executed", change_request_id=cr1.id))
    db.add(CommandAudit(actor="cli:m", tool="run_on_host", tier="write", command="systemctl restart x", outcome="refused", reason="change_required"))
    db.commit()


def _created(st):
    return sum(row["created"] for row in st["series"])


def _fix_plan(db, status, **kw):
    """A fix plan with its own HealthIssue and RCAResult (ck_fix_plans_origin needs both)."""
    issue = HealthIssue(title="t", description="d", severity="low", source="t", status="resolved", resource_id="r"); db.add(issue); db.flush()
    rca = RCAResult(health_issue_id=issue.id, root_cause="x", confidence=0.9); db.add(rca); db.flush()
    plan = FixPlan(health_issue_id=issue.id, rca_result_id=rca.id, risk_level="L1", title="fix", summary="s", status=status, **kw)
    db.add(plan); db.flush()
    return plan


def _stats(**kw):
    """plan_stats over the 30 days up to now."""
    from agenticops.services.plan_stats_service import plan_stats
    end = datetime.now(timezone.utc)
    return plan_stats(end - timedelta(days=30), end, **kw)


def _col(st, col):
    """One series column as {bucket: count}, zero rows left out."""
    return {row["bucket"]: row[col] for row in st["series"] if row[col]}


def _day(dt):
    return dt.date().isoformat()


def _approvals(kind):
    from agenticops.services.plan_stats_service import plan_stats
    end = datetime.now(timezone.utc)
    return plan_stats(end - timedelta(days=30), end, kind=kind)["approvals"]


def _user_id(email):
    from agenticops.auth.models import User
    s = get_session()
    try:
        return s.query(User.id).filter_by(email=email).scalar()
    finally:
        s.close()


def _token(email, *, admin):
    """A real session token for a new user (AuthService.create_user returns a detached row — re-read the id)."""
    from agenticops.auth.service import AuthService
    AuthService.create_user(email=email, password="pw-not-a-secret", name=email.split("@")[0], is_admin=admin)
    return AuthService.create_session(_user_id(email))


# ── plan_stats ────────────────────────────────────────────────────────

def test_plan_stats_shape_and_numbers(db):
    from agenticops.services.plan_stats_service import plan_stats
    _seed(db)
    end = datetime.now(timezone.utc); start = end - timedelta(days=30)
    st = plan_stats(start, end, kind="all", bucket="day")
    assert st["totals"]["by_kind_status"]["fix"]["executed"] == 1
    assert st["totals"]["by_kind_status"]["change"]["completed"] == 1 and st["totals"]["by_kind_status"]["change"]["planned"] == 1
    assert "failed" not in st["totals"]["by_kind_status"]["change"]  # cr3 is outside the window
    assert st["totals"]["open"] == 1
    assert st["approvals"]["auto"] == 1 and st["approvals"]["human"] == 1 and st["approvals"]["authz_denied_shadow"] == 1
    assert st["lead_time"]["request_to_approve_p50_s"] == pytest.approx(3600, rel=0.05)
    assert st["outcomes"]["success_rate"] == 1.0 and st["outcomes"]["rollbacks"] == 0
    assert st["breakdown"]["by_actor"]["requesters"][0] == {"actor": "user:alice", "count": 2}
    assert st["breakdown"]["by_risk"]["L1"] >= 2 and st["breakdown"]["by_action_type"]["tag"] == 1
    assert st["commands"]["by_outcome"] == {"executed": 1, "refused": 1} and st["commands"]["by_tool"]["run_on_host"] == 1
    assert any(row["created"] >= 1 for row in st["series"])


def test_kind_filter(db):
    from agenticops.services.plan_stats_service import plan_stats
    _seed(db)
    end = datetime.now(timezone.utc); start = end - timedelta(days=30)
    st = plan_stats(start, end, kind="change")
    assert "fix" not in st["totals"]["by_kind_status"]


def test_series_week_buckets_start_on_monday(db):
    from agenticops.services.plan_stats_service import _bucket_key, plan_stats
    _seed(db)
    end = datetime.now(timezone.utc); start = end - timedelta(days=30)
    st = plan_stats(start, end, kind="all", bucket="week")
    assert st["series"] and all(date.fromisoformat(row["bucket"]).weekday() == 0 for row in st["series"])
    assert _created(st) == 3  # 1 fix plan + 2 change requests; the change plan cp is cr1's child, not a 4th item
    # a Thursday folds into the Monday that starts its ISO week — true whatever weekday the suite runs on
    assert _bucket_key(datetime(2026, 9, 24, 13, 0), "week") == "2026-09-21"
    assert _bucket_key(datetime(2026, 9, 24, 13, 0), "day") == "2026-09-24"


def test_series_created_counts_work_items(db):
    from agenticops.services.plan_stats_service import plan_stats
    _seed(db)
    end = datetime.now(timezone.utc); start = end - timedelta(days=30)
    daily = plan_stats(start, end, kind="all", bucket="day")
    assert _created(daily) == 3
    assert [row["bucket"] for row in daily["series"]] == sorted(row["bucket"] for row in daily["series"])
    # completed: cr1 by its closed_at, fp by its execution's completed_at (fp has no updated_at);
    # cr3 failed 40 days ago, outside the cohort
    assert sum(row["failed"] for row in daily["series"]) == 0
    assert [sum(row["completed"] for row in plan_stats(start, end, kind=k)["series"]) for k in ("all", "fix", "change")] == [2, 1, 1]
    assert _created(plan_stats(start, end, kind="change", bucket="day")) == 2
    assert _created(plan_stats(start, end, kind="fix", bucket="day")) == 1


def test_series_dates_a_fix_plans_completion_by_its_execution(db):
    """PUT /api/fix-plans/{id} re-stamps updated_at on a finished plan: an edit must not move its completion."""
    now = datetime.now(timezone.utc)
    done, edited = now - timedelta(days=5), now - timedelta(days=3)
    fp = _fix_plan(db, "executed", created_at=now - timedelta(days=6), updated_at=edited)
    db.add(FixExecution(fix_plan_id=fp.id, status="succeeded", started_at=done - timedelta(minutes=5), completed_at=done))
    db.commit()
    assert _col(_stats(kind="fix"), "completed") == {_day(done): 1}  # not {_day(edited): 1}


def test_series_falls_back_to_a_fix_plans_updated_at(db):
    """No execution with a completed_at: the plan's updated_at dates it. No date at all: not in the series."""
    now = datetime.now(timezone.utc)
    failed_at = now - timedelta(days=2)
    _fix_plan(db, "failed", created_at=now - timedelta(days=4), updated_at=failed_at)  # failed without running
    _fix_plan(db, "executed", created_at=now - timedelta(days=4))  # no execution, no updated_at
    db.commit()
    st = _stats(kind="fix")
    assert _col(st, "failed") == {_day(failed_at): 1} and _col(st, "completed") == {}


def test_series_takes_the_latest_completed_at_of_any_execution(db):
    """The latest completed_at over ALL the plan's executions, whatever their status; an execution without one is
    ignored, and a plan whose executions all lack one falls back to its updated_at."""
    d = datetime.now(timezone.utc) - timedelta(days=5)
    fp = _fix_plan(db, "failed", created_at=d - timedelta(days=2), updated_at=d + timedelta(days=1))
    db.add_all([FixExecution(fix_plan_id=fp.id, status="failed", completed_at=d - timedelta(days=1)),
                FixExecution(fix_plan_id=fp.id, status="aborted", completed_at=d),  # a cancelled run ends the plan
                FixExecution(fix_plan_id=fp.id, status="running")])  # never recorded an end
    legacy = _fix_plan(db, "executed", created_at=d - timedelta(days=2), updated_at=d + timedelta(days=2))
    db.add(FixExecution(fix_plan_id=legacy.id, status="succeeded"))  # completed_at NULL
    db.commit()
    st = _stats(kind="fix")
    assert _col(st, "failed") == {_day(d): 1}
    assert _col(st, "completed") == {_day(d + timedelta(days=2)): 1}


def test_window_is_utc_whatever_the_caller_passes(db):
    """An aware start/end is converted to UTC and a naive one is taken as UTC: the same instant, the same stats."""
    from agenticops.services.plan_stats_service import plan_stats
    _seed(db)
    end = datetime.now(timezone.utc); start = end - timedelta(hours=4)  # the seeded rows sit 30 min to 3 h back
    utc = plan_stats(start, end)
    assert utc["totals"]["open"] == 1  # the window holds rows, so a shifted one would show
    sgt = timezone(timedelta(hours=8))
    assert plan_stats(start.astimezone(sgt), end.astimezone(sgt)) == utc
    naive = plan_stats(start.replace(tzinfo=None), end.replace(tzinfo=None))
    assert naive["period"]["start"].endswith("+00:00") and naive["period"]["end"].endswith("+00:00")
    assert naive == utc


def test_plan_stats_rejects_an_unknown_kind_or_bucket(db):
    """The router constrains HTTP callers; a direct caller gets an error, not stats labelled with its typo."""
    with pytest.raises(ValueError, match="kind"):
        _stats(kind="bogus")
    with pytest.raises(ValueError, match="bucket"):
        _stats(bucket="month")


@pytest.mark.parametrize(("values", "p", "expected"), [
    ([1, 2], 50, 1),
    ([1, 2, 3, 4], 50, 2),
    ([1, 2, 3, 4, 5, 6], 90, 6),
    (list(range(1, 11)), 90, 9),
    ([5], 50, 5),
    ([], 50, None),
])
def test_pct_is_nearest_rank(values, p, expected):
    from agenticops.services.plan_stats_service import _pct
    assert _pct(values, p) == expected


def test_empty_window_is_sparse(db):
    """The contract Plan C consumes for a window with no rows: no status keys, no buckets, null percentiles."""
    from agenticops.services.plan_stats_service import plan_stats
    _seed(db)
    end = datetime.now(timezone.utc) - timedelta(days=100); start = end - timedelta(days=30)  # before every seeded row
    assert plan_stats(start, end) == {
        "period": {"start": start.isoformat(), "end": end.isoformat(), "bucket": "day"},
        "kind": "all",
        "totals": {"by_kind_status": {}, "open": 0},
        "approvals": {"auto": 0, "human": 0, "rejected": 0, "authz_denied": 0, "authz_denied_shadow": 0},
        "lead_time": {"request_to_approve_p50_s": None, "request_to_approve_p90_s": None,
                      "approve_to_start_p50_s": None, "exec_duration_p50_s": None},
        "outcomes": {"success_rate": None, "rollbacks": 0, "needs_review": 0},
        "breakdown": {"by_actor": {"requesters": [], "approvers": [], "executors": []},
                      "by_risk": {}, "by_change_type": {}, "by_action_type": {}, "by_account": {}},
        "series": [],
        "commands": {"by_outcome": {}, "by_tool": {}},
    }


def test_lead_times_outcomes_and_breakdowns(db):
    t = datetime.now(timezone.utc) - timedelta(days=1)

    def at(minutes):
        return t + timedelta(minutes=minutes)

    acct = CloudAccount(name="dev", provider="aws", is_enabled=True, credentials={}, regions=[]); db.add(acct); db.flush()
    cr_a = ChangeRequest(title="a", description="d", requested_by="user:alice", status="completed", account_id=acct.id,
                         effective_change_type="standard", requested_at=t, created_at=t,
                         approved_at=at(10), approved_by="user:bob", closed_at=at(60))
    cr_b = ChangeRequest(title="b", description="d", requested_by="user:alice", status="rolled_back", account_id=acct.id,
                         requested_change_type="emergency", requested_at=t, created_at=t,
                         approved_at=at(30), approved_by="user:carol", closed_at=at(60))
    cr_c = ChangeRequest(title="c", description="d", requested_by="user:dave", status="needs_review",
                         requested_change_type="emergency", effective_change_type="normal", requested_at=t, created_at=t)
    db.add_all([cr_a, cr_b, cr_c]); db.flush()
    fp = _fix_plan(db, "executed", created_at=t, approved_at=at(20), approved_by="user:bob")
    cp_a = FixPlan(plan_kind="change", change_request_id=cr_a.id, risk_level="L1", title="a", summary="s", status="executed",
                   created_at=at(5), approved_at=at(10), approved_by="user:bob")
    cp_b = FixPlan(plan_kind="change", change_request_id=cr_b.id, risk_level="L1", title="b", summary="s", status="failed",
                   created_at=at(5), approved_at=at(30), approved_by="user:carol")
    db.add_all([cp_a, cp_b]); db.flush()
    db.add_all([
        FixExecution(fix_plan_id=fp.id, status="succeeded", executed_by="agent:executor",
                     started_at=at(22), completed_at=at(23), duration_ms=30000),
        FixExecution(fix_plan_id=cp_a.id, status="succeeded", executed_by="agent:executor",
                     started_at=at(15), completed_at=at(16), duration_ms=60000),
        FixExecution(fix_plan_id=cp_b.id, status="rolled_back", executed_by="user:carol",
                     started_at=at(40), completed_at=at(42), duration_ms=90000),
    ])
    db.commit()
    st = _stats()
    # request → approve: cr_a 600 s, fp 1200 s, cr_b 1800 s (cr_c is not approved); approve → start: fp 120 s,
    # cp_a 300 s, cp_b 600 s; durations 30, 60 and 90 s
    assert st["lead_time"] == {"request_to_approve_p50_s": 1200.0, "request_to_approve_p90_s": 1800.0,
                               "approve_to_start_p50_s": 300.0, "exec_duration_p50_s": 60.0}
    assert st["outcomes"] == {"success_rate": 0.667, "rollbacks": 1, "needs_review": 1}  # 2 succeeded, 1 rolled back
    b = st["breakdown"]
    assert b["by_account"] == {str(acct.id): 2}
    assert b["by_change_type"] == {"standard": 1, "emergency": 1, "normal": 1}  # effective, else requested
    assert b["by_actor"]["approvers"] == [{"actor": "user:bob", "count": 2}, {"actor": "user:carol", "count": 1}]
    assert b["by_actor"]["executors"] == [{"actor": "agent:executor", "count": 2}, {"actor": "user:carol", "count": 1}]


def test_request_to_approve_drops_negative_spans(db):
    """An approval stamped before its request is clock skew or a back-filled stamp, not a lead time — dropped from
    both the change and the fix-plan spans, as approve_to_start already does."""
    t = datetime.now(timezone.utc) - timedelta(hours=6)
    db.add_all([
        ChangeRequest(title="ok", description="d", requested_by="user:alice", status="approved",
                      requested_at=t, created_at=t, approved_at=t + timedelta(minutes=10)),
        ChangeRequest(title="skewed", description="d", requested_by="user:alice", status="approved",
                      requested_at=t, created_at=t, approved_at=t - timedelta(minutes=5)),
    ])
    _fix_plan(db, "approved", created_at=t, approved_at=t - timedelta(minutes=2))
    db.commit()
    lead = _stats()["lead_time"]
    assert (lead["request_to_approve_p50_s"], lead["request_to_approve_p90_s"]) == (600.0, 600.0)


def test_approvals_count_work_items_per_kind(db):
    """One count per decision, under its own kind only: the plan.approved echo of a change approval is not a
    second decision; a subject-less denial is classified by its permission."""
    from agenticops.audit.models import AuditLog
    _seed(db)
    fix, change = _approvals("fix"), _approvals("change")
    assert (fix["auto"], fix["human"], fix["authz_denied_shadow"]) == (1, 0, 0)
    assert (change["auto"], change["human"], change["authz_denied_shadow"]) == (0, 1, 1)

    fp_id = db.query(FixPlan.id).filter_by(plan_kind="fix").scalar()
    # app.py _reject_plan: a fix-plan rejection's details carry no plan_kind
    db.add(AuditLog(action="plan.rejected", entity_type="fix_plan", entity_id=str(fp_id), actor="user:bob",
                    details={"reason": "not now", "risk_level": "L1"}))
    db.commit()
    assert [_approvals(k)["rejected"] for k in ("all", "fix", "change")] == [1, 1, 0]

    for permission in ("change.request", "audit.read"):
        db.add(AuditLog(action="authz.denied", entity_type="system", entity_id="-", actor="user:alice",
                        details={"permission": permission, "reason": "x", "rule": None}))
    db.commit()
    # change.request is a change-side decision; audit.read is no plan or change decision at all
    assert [_approvals(k)["authz_denied"] for k in ("all", "fix", "change")] == [1, 0, 1]


def test_approvals_classify_plan_rows_by_the_plans_kind(db):
    """A denial on a change plan is a change-side denial (never skipped like an echo); a plan row whose plan no
    longer exists — or whose id is not a decimal string — falls back to its details' plan_kind, then 'fix'."""
    from agenticops.audit.models import AuditLog
    _seed(db)
    cp_id = db.query(FixPlan.id).filter_by(plan_kind="change").scalar()
    db.add(AuditLog(action="authz.denied_shadow", entity_type="fix_plan", entity_id=str(cp_id), actor="agent:executor",
                    details={"permission": "plan.execute", "reason": "x", "rule": None}))
    # authz writes "-" for a subject that has no id yet
    db.add(AuditLog(action="authz.denied_shadow", entity_type="fix_plan", entity_id="-", actor="agent:executor",
                    details={"permission": "plan.approve", "reason": "x", "rule": None}))
    db.add(AuditLog(action="plan.approved", entity_type="fix_plan", entity_id="9999", actor="user:carol"))
    db.add(AuditLog(action="plan.approved", entity_type="fix_plan", entity_id="9998", actor="user:carol",
                    details={"plan_kind": "change"}))
    db.commit()
    fix, change = _approvals("fix"), _approvals("change")
    assert (fix["authz_denied_shadow"], change["authz_denied_shadow"]) == (1, 2)
    assert (fix["human"], change["human"]) == (1, 1)  # 9999 is a legacy fix decision; 9998 is a change echo


# ── GET /api/plans/stats ──────────────────────────────────────────────

def test_stats_endpoint(db, monkeypatch):
    from agenticops.config import settings
    from agenticops.web.app import app
    monkeypatch.setattr(settings, "api_auth_enabled", False)
    monkeypatch.setattr(settings, "rbac_enforce", False)
    _seed(db)
    c = TestClient(app)   # bare — no `with`, so the lifespan (schedulers, executor service) never starts
    r = c.get("/api/plans/stats?period=7d&kind=all&bucket=day")
    assert r.status_code == 200 and r.json()["period"]["bucket"] == "day"
    assert c.get("/api/plans/stats?period=1y").status_code == 422


def test_stats_endpoint_is_not_gated_by_the_change_flag(db, monkeypatch):
    """Fix-plan statistics and historical change rows stay readable with change management off."""
    from agenticops.config import settings
    from agenticops.web.app import app
    monkeypatch.setattr(settings, "api_auth_enabled", False)
    monkeypatch.setattr(settings, "rbac_enforce", False)
    monkeypatch.setattr(settings, "change_management_enabled", False)
    _seed(db)
    r = TestClient(app).get("/api/plans/stats?kind=all")
    assert r.status_code == 200 and r.json()["totals"]["by_kind_status"]["change"]["completed"] == 1


def test_stats_endpoint_needs_an_admin_when_auth_on(db, monkeypatch):
    """An audit surface: auth on → the same HARD admin check as /api/audit/stats, independent of rbac_enforce."""
    from agenticops.config import settings
    from agenticops.web.app import app
    user = {"Authorization": f"Bearer {_token('bob@example.com', admin=False)}"}
    admin = {"Authorization": f"Bearer {_token('root@example.com', admin=True)}"}
    monkeypatch.setattr(settings, "api_auth_enabled", True)
    c = TestClient(app)
    assert c.get("/api/plans/stats").status_code == 401
    assert c.get("/api/plans/stats", headers=user).status_code == 403
    assert c.get("/api/plans/stats", headers=admin).status_code == 200
