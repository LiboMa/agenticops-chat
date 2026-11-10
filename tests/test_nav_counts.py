"""The sidebar's numbers in one request (MVP-2.8.0, owner 2026-11-10: direction A) — GET /api/ui/nav-counts.

- `attention.total` is the to-do total from the same source as /api/ui/attention (services/attention), so the
  sidebar, the top bar and the «在等我» tab can never disagree; `critical` counts the critical issues among them.
- Only the attention number follows the account scope (the Security / Schedules / Skills pages are not scoped).
- A viewer can act on nothing: no numbers at all, and the other counts are not even queried.
- A count that fails is null, never 0 (a sidebar must not say «nothing waiting» because a query broke)."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from starlette.testclient import TestClient

from agenticops.auth.actor import Actor
from agenticops.models import Base, FixPlan, HealthIssue, RCAResult, get_session
from agenticops.services import attention as att

ADMIN = Actor("user", "root", 3, ("read", "write", "admin"))
ALICE = Actor("user", "alice", 1, ("read", "write"))
READER = Actor("user", "rita", 4, ("read",), read_only=True)
NOW = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def db(tmp_path, monkeypatch):
    import agenticops.audit.models  # noqa: F401
    import agenticops.models as models_mod
    import agenticops.scheduler.scheduler  # noqa: F401  (schedules tables)
    from agenticops.config import settings
    monkeypatch.setattr(models_mod, "_engine", None)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/nav.db")
    monkeypatch.setattr(settings, "change_management_enabled", True)
    monkeypatch.setattr(settings, "executor_enabled", True)
    monkeypatch.setattr(settings, "auto_fix_enabled", True)
    monkeypatch.setattr(settings, "rbac_enforce", False)
    Base.metadata.create_all(models_mod.get_engine())
    import agenticops.skills.loader as loader
    monkeypatch.setattr(loader, "discover_skills", lambda *a, **k: [])
    yield settings


def _waiting(severity="low", account_id=None):
    """An issue whose fix plan waits for approval — a to-do row for an admin."""
    s = get_session()
    try:
        i = HealthIssue(title="t", description="d", severity=severity, source="test", status="fix_planned",
                        resource_id="i-1", account_id=account_id)
        s.add(i); s.flush()
        r = RCAResult(health_issue_id=i.id, root_cause="x", confidence=0.9, critic_verdict="supported")
        s.add(r); s.flush()
        s.add(FixPlan(health_issue_id=i.id, rca_result_id=r.id, plan_kind="fix", risk_level="L1", title="p",
                      summary="s", status="pending_approval"))
        s.commit()
        return i.id
    finally:
        s.close()


def _finding(severity, status="open", detected_by="security_poll"):
    s = get_session()
    try:
        s.add(HealthIssue(title="f", description="d", severity=severity, source=detected_by, detected_by=detected_by,
                          status=status, resource_id="sg-1"))
        s.commit()
    finally:
        s.close()


def _schedule(name, runs):
    from agenticops.scheduler.scheduler import Schedule, ScheduleExecution
    s = get_session()
    try:
        sch = Schedule(name=name, pipeline_name="p", cron_expression="0 * * * *")
        s.add(sch); s.flush()
        for i, status in enumerate(runs):
            s.add(ScheduleExecution(schedule_id=sch.id, status=status, started_at=NOW - timedelta(hours=len(runs) - i)))
        s.commit()
    finally:
        s.close()


def _counts(actor, **kw):
    from agenticops.services.nav_counts import nav_counts
    return nav_counts(actor, now=NOW, **kw)


def test_the_attention_number_is_the_attention_total(db):
    _waiting(account_id=1)
    _waiting(account_id=2)
    for actor in (ADMIN, ALICE, READER):
        for acct in (None, 1):
            want = att.attention_page(actor, account_id=acct, now=NOW)["total"]
            got = _counts(actor, account_id=acct)["attention"]["total"]
            assert got == want, (actor.key, acct)
    assert _counts(ADMIN)["attention"]["total"] == 2


def test_critical_is_critical_issues_only(db):
    _waiting("critical")
    _waiting("high")
    from agenticops.models import ChangeRequest
    s = get_session()
    try:
        cr = ChangeRequest(source="web", title="c", description="d", status="planned", requested_by="user:alice",
                           risk_level="L3")
        s.add(cr); s.flush()
        s.add(FixPlan(plan_kind="change", change_request_id=cr.id, risk_level="L3", title="p", summary="s",
                      status="pending_approval"))
        s.commit()
    finally:
        s.close()
    c = _counts(ADMIN)["attention"]
    assert c["total"] == 3 and c["critical"] == 1


def test_a_read_only_actor_gets_no_numbers(db, monkeypatch):
    _waiting()
    _finding("critical")
    from agenticops.services import security_service
    monkeypatch.setattr(security_service, "open_high_findings",
                        lambda: (_ for _ in ()).throw(AssertionError("a viewer's counts are never queried")))
    c = _counts(READER)
    assert c["read_only"] is True and c["attention"] == {"total": 0, "critical": 0}
    assert (c["security_high"], c["schedules_failed"], c["skill_drafts"]) == (None, None, None)


def test_only_the_attention_number_follows_the_account(db):
    _waiting(account_id=1)
    _waiting(account_id=2)
    _finding("high")
    _schedule("s", ["failed"])
    one, every = _counts(ADMIN, account_id=1), _counts(ADMIN)
    assert (one["attention"]["total"], every["attention"]["total"]) == (1, 2)
    assert one["security_high"] == every["security_high"] == 1
    assert one["schedules_failed"] == every["schedules_failed"] == 1


def test_security_high_counts_open_high_and_critical_findings(db):
    _finding("high")
    _finding("critical")
    _finding("medium")
    _finding("critical", status="resolved")
    _finding("high", status="dismissed")
    _finding("critical", detected_by="cloudwatch")          # an ops issue, not a security finding
    assert _counts(ADMIN)["security_high"] == 2


def test_schedules_failed_reads_the_newest_run(db):
    _schedule("recovered", ["failed", "completed"])
    _schedule("broke", ["completed", "failed"])
    _schedule("never", [])
    assert _counts(ADMIN)["schedules_failed"] == 1


def test_skill_drafts_counts_drafts(db, monkeypatch):
    import agenticops.skills.loader as loader
    monkeypatch.setattr(loader, "discover_skills", lambda *a, **k: [SimpleNamespace(is_draft=True),
                                                                     SimpleNamespace(is_draft=True),
                                                                     SimpleNamespace(is_draft=False)])
    assert _counts(ADMIN)["skill_drafts"] == 2


def test_a_failing_count_is_null_not_zero(db, monkeypatch):
    _waiting()
    from agenticops.services import security_service
    monkeypatch.setattr(security_service, "open_high_findings", lambda: 1 / 0)
    c = _counts(ADMIN)
    assert c["security_high"] is None and c["attention"]["total"] == 1 and c["schedules_failed"] == 0


def test_the_endpoint_shape_and_plain_def(db):
    import inspect
    from agenticops.web import deps
    from agenticops.web.app import app
    from agenticops.web.routers import ui as ui_router
    _waiting()
    app.dependency_overrides[deps.current_actor] = lambda: ADMIN
    app.dependency_overrides[ui_router.signed_in_user] = lambda: SimpleNamespace(id=3)
    try:
        r = TestClient(app).get("/api/ui/nav-counts")
        assert r.status_code == 200, r.text
        body = r.json()
        assert set(body) == {"read_only", "attention", "security_high", "schedules_failed", "skill_drafts", "generated_at"}
        assert body["attention"]["total"] == 1
        assert TestClient(app).get("/api/ui/nav-counts?account_id=0").status_code == 422
    finally:
        app.dependency_overrides.clear()
    ep = [r.endpoint for r in ui_router.router.routes if getattr(r, "path", "") == "/api/ui/nav-counts"]
    assert len(ep) == 1 and not inspect.iscoroutinefunction(ep[0])
