"""GET /api/health-issues filters on the server for the Cases queue (MVP-2.7.0 S4): scope, status and severity lists,
search by title / resource / I#n, server-side sort — so the queue never filters a 50-row page in the browser."""
from datetime import datetime, timedelta, timezone

import pytest
from starlette.testclient import TestClient

from agenticops.models import Base, HealthIssue, get_session

T0 = datetime(2026, 10, 7, 9, 0, tzinfo=timezone.utc)


@pytest.fixture
def client(tmp_path, monkeypatch):
    import agenticops.models as models_mod
    import agenticops.audit.models  # noqa: F401
    from agenticops.config import settings
    from agenticops.web.app import app
    monkeypatch.setattr(models_mod, "_engine", None)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/hil.db")
    Base.metadata.create_all(models_mod.get_engine())
    yield TestClient(app)


def _issue(title, *, severity="high", status="open", source="manual", resource_id="i-1", minutes=0,
           metric_data=None, occurrences=1):
    s = get_session()
    try:
        i = HealthIssue(title=title, description="d", severity=severity, source=source, status=status,
                        resource_id=resource_id, detected_at=T0 + timedelta(minutes=minutes),
                        metric_data=metric_data or {}, occurrence_count=occurrences)
        s.add(i); s.commit()
        return i.id
    finally:
        s.close()


def _ids(client, qs):
    r = client.get(f"/api/health-issues{qs}")
    assert r.status_code == 200, r.text
    return [row["id"] for row in r.json()["items"]]


def test_scope_splits_ops_and_security(client):
    sec = _issue("sg open", source="security_poll")
    ops = _issue("cpu high", source="manual")
    assert _ids(client, "?scope=security") == [sec]
    assert _ids(client, "?scope=ops") == [ops]
    assert sorted(_ids(client, "")) == sorted([sec, ops])


def test_status_and_severity_take_comma_lists_and_refuse_typos(client):
    a = _issue("a", status="open")
    b = _issue("b", status="investigating")
    _issue("c", status="resolved")
    lo = _issue("d", severity="low")
    assert sorted(_ids(client, "?status=open,investigating")) == sorted([a, b, lo])
    assert _ids(client, "?severity=low") == [lo]
    assert client.get("/api/health-issues?status=opne").status_code == 422
    assert client.get("/api/health-issues?severity=hgh").status_code == 422


def test_q_matches_title_resource_and_issue_ref(client):
    a = _issue("nginx down", resource_id="i-0abc")
    b = _issue("disk full", resource_id="vol-9")
    assert _ids(client, "?q=nginx") == [a]
    assert _ids(client, "?q=i-0ab") == [a]
    assert _ids(client, f"?q=I%23{b}") == [b]
    assert b in _ids(client, f"?q={b}")
    assert _ids(client, "?q=50%25_") == []        # LIKE wildcards are literal


def test_sort_orders(client):
    old = _issue("old", severity="low", minutes=0)
    new = _issue("new", severity="medium", minutes=10)
    crit = _issue("crit", severity="critical", minutes=5)
    assert _ids(client, "") == [new, crit, old]
    assert _ids(client, "?sort=oldest") == [old, crit, new]
    assert _ids(client, "?sort=severity") == [crit, new, old]
    assert client.get("/api/health-issues?sort=random").status_code == 422


def test_rows_keep_the_full_issue_shape(client):
    _issue("x", metric_data={"resource_type": "EKS", "region": "ap-southeast-1"}, occurrences=4)
    row = client.get("/api/health-issues").json()["items"][0]
    assert row["occurrence_count"] == 4 and row["metric_data"]["resource_type"] == "EKS"
    assert {"account_name", "anchor_status", "resource_ref"} <= set(row)


def test_limit_caps_at_the_max_list_limit(client):
    from agenticops.config import settings
    assert client.get(f"/api/health-issues?limit={settings.max_list_limit + 1}").status_code == 422
    assert client.get("/api/health-issues?limit=0").status_code == 422


# ── MVP-2.8.0 S2: {items, total}, who each issue waits on and since when, quick views and their counts ─────────

def _plan(issue_id, status, *, minutes_ago=30):
    from agenticops.models import FixPlan, RCAResult
    s = get_session()
    try:
        r = RCAResult(health_issue_id=issue_id, root_cause="x", confidence=0.9, critic_verdict="supported")
        s.add(r); s.flush()
        p = FixPlan(health_issue_id=issue_id, rca_result_id=r.id, risk_level="L1", title="p", summary="s", status=status)
        s.add(p); s.flush()
        p.updated_at = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
        s.commit()
    finally:
        s.close()


def test_the_list_is_items_and_total(client):
    for n in range(3):
        _issue(f"i{n}")
    body = client.get("/api/health-issues?limit=2").json()
    assert set(body) == {"items", "total"} and body["total"] == 3 and len(body["items"]) == 2


def test_each_row_says_who_it_waits_on_and_since_when(client):
    waiting = _issue("needs approval", status="fix_planned")
    _plan(waiting, "pending_approval")
    row = next(r for r in client.get("/api/health-issues").json()["items"] if r["id"] == waiting)
    assert row["waiting_on"] == "approver" and row["waiting_since"]


def test_views_mine_failed_and_long_wait(client, monkeypatch):
    from agenticops.config import settings
    monkeypatch.setattr(settings, "attention_long_wait_hours", 24)
    fresh = _issue("fresh approval", status="fix_planned")
    _plan(fresh, "pending_approval", minutes_ago=30)
    stale = _issue("old approval", status="fix_planned")
    _plan(stale, "pending_approval", minutes_ago=60 * 30)
    _issue("nobody waits", status="investigating")
    assert sorted(_ids(client, "?view=mine")) == sorted([fresh, stale])
    assert _ids(client, "?view=long_wait") == [stale]
    assert _ids(client, "?view=failed") == []
    assert client.get("/api/health-issues?view=everything").status_code == 422


def test_view_counts_match_each_views_total(client):
    a = _issue("approval", status="fix_planned")
    _plan(a, "pending_approval")
    _issue("open", status="open")
    _issue("sec", source="security_poll")
    counts = client.get("/api/health-issues/view-counts?scope=all").json()
    assert set(counts) == {"all", "mine", "failed", "long_wait"}
    for view in ("all", "mine", "failed", "long_wait"):
        total = client.get(f"/api/health-issues?scope=all&view={view}").json()["total"]
        assert counts[view] == total, view
    assert client.get("/api/health-issues/view-counts?scope=ops").json()["all"] == 2


def test_the_count_and_list_handlers_are_plain_def():
    import inspect
    from agenticops.web import app as webapp
    assert not inspect.iscoroutinefunction(webapp.api_list_health_issues)
    assert not inspect.iscoroutinefunction(webapp.api_health_issue_view_counts)
