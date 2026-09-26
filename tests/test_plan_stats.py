"""Plans & changes statistics (MVP-2.6.0, Plan B Task 12): services/plan_stats_service + GET /api/plans/stats."""

from datetime import date, datetime, timedelta, timezone

import pytest
from starlette.testclient import TestClient

from agenticops.models import Base, ChangeRequest, CommandAudit, FixExecution, FixPlan, HealthIssue, RCAResult, get_session


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
    # completed: cr1 (by closed_at); cr3 failed 40 days ago, outside the cohort; fp has no updated_at yet
    assert sum(row["completed"] for row in daily["series"]) == 1 and sum(row["failed"] for row in daily["series"]) == 0
    assert _created(plan_stats(start, end, kind="change", bucket="day")) == 2
    assert _created(plan_stats(start, end, kind="fix", bucket="day")) == 1
    # a fix plan completes at its updated_at
    db.query(FixPlan).filter_by(plan_kind="fix").update({"updated_at": end - timedelta(minutes=45)})
    db.commit()
    assert [sum(row["completed"] for row in plan_stats(start, end, kind=k)["series"]) for k in ("all", "fix", "change")] == [2, 1, 1]


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
