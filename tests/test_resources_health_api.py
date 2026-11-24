"""GET /api/resources (MVP-2.7.0 S4): stable paging, and each row says its open issues and health — the Galaxy
definition (graph/query_service.health_overlay); a resource with no open issue is `unknown`, never healthy.
MVP-2.9.0 N24 (the 2.8.0 spec's S7): every row also says WHY — `health_reason` — and when it was last observed."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import event
from starlette.testclient import TestClient

from agenticops.models import Base, CloudAccount, CloudResource, HealthIssue, get_session

T0 = datetime(2026, 10, 7, 9, 0, tzinfo=timezone.utc)
ACCT, OTHER = 1, 2


@pytest.fixture
def client(tmp_path, monkeypatch):
    import agenticops.models as models_mod
    import agenticops.audit.models  # noqa: F401
    from agenticops.config import settings
    from agenticops.web.app import app
    monkeypatch.setattr(models_mod, "_engine", None)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/res.db")
    Base.metadata.create_all(models_mod.get_engine())
    s = get_session()
    s.add_all([CloudAccount(id=ACCT, name="global", provider="aws", is_enabled=True, credentials={}),
               CloudAccount(id=OTHER, name="cn", provider="aws", is_enabled=True, credentials={})])
    s.commit(); s.close()
    yield TestClient(app)


def _res(rid, rtype="EC2", account=ACCT, scanned_at=T0, absent_since=None):
    s = get_session()
    try:
        r = CloudResource(account_id=account, provider="aws", region="us-east-1", resource_type=rtype,
                          resource_id=rid, name=rid, tags={}, raw_data={}, status="running", scanned_at=scanned_at,
                          absent_since=absent_since)
        s.add(r); s.commit()
        return r.id
    finally:
        s.close()


def _issue(ref, severity="high", status="open", account=ACCT):
    s = get_session()
    try:
        s.add(HealthIssue(title="t", description="d", severity=severity, source="manual", status=status,
                          resource_id="x", resource_ref=ref, account_id=account, detected_at=T0))
        s.commit()
    finally:
        s.close()


def _row(client, pk):
    return next(r for r in client.get("/api/resources").json()["items"] if r["id"] == pk)


def test_a_resource_without_open_issues_is_unknown_not_healthy(client):
    row = _row(client, _res("i-1"))
    assert (row["open_issues"], row["health"]) == (0, "unknown")


def test_open_anchored_issues_count_and_set_health(client):
    pk = _res("i-1")
    _issue(pk, "high"); _issue(pk, "critical")
    row = _row(client, pk)
    assert (row["open_issues"], row["health"]) == (2, "critical")


def test_dismissed_and_resolved_issues_do_not_count(client):
    pk = _res("i-1")
    _issue(pk, status="dismissed"); _issue(pk, status="resolved")
    assert (_row(client, pk)["open_issues"], _row(client, pk)["health"]) == (0, "unknown")


def test_another_accounts_issue_does_not_count(client):
    pk = _res("i-1")
    _issue(pk, account=OTHER)
    assert _row(client, pk)["open_issues"] == 0


def test_pages_are_stable(client):
    ids = {_res(f"i-{n}", rtype="EC2" if n % 2 else "RDS") for n in range(7)}
    seen = []
    for page in range(3):
        seen += [r["id"] for r in client.get(f"/api/resources?limit=3&offset={page * 3}").json()["items"]]
    assert sorted(seen) == sorted(ids)


def test_list_is_a_bounded_number_of_queries(client):
    import agenticops.models as models_mod
    for n in range(20):
        _issue(_res(f"i-{n}"))
    count = {"n": 0}
    def on_exec(*_a, **_k):
        count["n"] += 1
    event.listen(models_mod.get_engine(), "before_cursor_execute", on_exec)
    try:
        assert len(client.get("/api/resources").json()["items"]) == 20
    finally:
        event.remove(models_mod.get_engine(), "before_cursor_execute", on_exec)
    assert count["n"] <= 5, count


# ── why (MVP-2.9.0 N24) ───────────────────────────────────────────────────────────────────────────────────────

NOW = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)
TWO_HOURS = timedelta(minutes=120)


def _why(**kw):
    from agenticops.services.inventory import health_reason
    args = {"open_issues": 0, "absent_since": None, "scanned_at": NOW - timedelta(minutes=5), "now": NOW, "stale_after": TWO_HOURS}
    return health_reason(**{**args, **kw})


def test_the_reason_of_a_rows_health():
    assert _why() == "no_open_issue"                                         # seen lately, nothing known: not «healthy»
    assert _why(open_issues=2) == "open_issue"
    assert _why(scanned_at=None) == "never_observed"
    assert _why(scanned_at=NOW - timedelta(minutes=121)) == "stale"
    assert _why(scanned_at=NOW - TWO_HOURS) == "no_open_issue"                # exactly at the limit is not past it
    assert _why(absent_since=NOW - timedelta(days=1)) == "absent"


def test_which_reason_wins():
    gone = NOW - timedelta(days=1)
    assert _why(open_issues=1, absent_since=gone, scanned_at=None) == "open_issue"      # the issue is why it is not unknown
    assert _why(absent_since=gone, scanned_at=None) == "absent"                           # gone says more than «never seen»
    assert _why(absent_since=gone, scanned_at=NOW - timedelta(days=9)) == "absent"
    assert _why(open_issues=1, scanned_at=NOW - timedelta(days=9)) == "open_issue"


def test_a_time_without_a_zone_is_utc():
    assert _why(scanned_at=(NOW - timedelta(minutes=30)).replace(tzinfo=None)) == "no_open_issue"
    assert _why(scanned_at=(NOW - timedelta(minutes=130)).replace(tzinfo=None)) == "stale"


def test_each_row_says_why_and_when_it_was_last_observed(client, monkeypatch):
    from agenticops.config import settings
    monkeypatch.setattr(settings, "resource_scan_interval_minutes", 60)       # stale = not seen for over 2 hours
    now = datetime.now(timezone.utc)
    fresh = _res("i-fresh", scanned_at=now - timedelta(minutes=10))
    old = _res("i-old", scanned_at=now - timedelta(minutes=125))
    never = _res("i-never", scanned_at=None)
    sick = _res("i-sick", scanned_at=now - timedelta(days=3))
    gone = _res("i-gone", scanned_at=now - timedelta(days=3), absent_since=now - timedelta(days=2))
    _issue(sick, "high")
    rows = {r["id"]: r for r in client.get("/api/resources?include_absent=true").json()["items"]}
    assert {pk: rows[pk]["health_reason"] for pk in (fresh, old, never, sick, gone)} == {
        fresh: "no_open_issue", old: "stale", never: "never_observed", sick: "open_issue", gone: "absent"}
    assert rows[never]["observed_at"] is None
    assert rows[fresh]["observed_at"] == rows[fresh]["scanned_at"] and rows[fresh]["observed_at"] is not None
    assert (rows[sick]["health"], rows[old]["health"]) == ("warning", "unknown")       # the health values are unchanged
    assert gone not in {r["id"] for r in client.get("/api/resources").json()["items"]}     # absent rows are still opt-in


def test_stale_follows_the_scan_interval_setting(client, monkeypatch):
    from agenticops.config import settings
    pk = _res("i-1", scanned_at=datetime.now(timezone.utc) - timedelta(minutes=125))
    monkeypatch.setattr(settings, "resource_scan_interval_minutes", 60)
    assert _row(client, pk)["health_reason"] == "stale"
    monkeypatch.setattr(settings, "resource_scan_interval_minutes", 120)      # 2 × 120 min: 125 minutes is in time
    assert _row(client, pk)["health_reason"] == "no_open_issue"
