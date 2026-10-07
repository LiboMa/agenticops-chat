"""GET /api/resources (MVP-2.7.0 S4): stable paging, and each row says its open issues and health — the Galaxy
definition (graph/query_service.health_overlay); a resource with no open issue is `unknown`, never healthy."""
from datetime import datetime, timezone

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


def _res(rid, rtype="EC2", account=ACCT):
    s = get_session()
    try:
        r = CloudResource(account_id=account, provider="aws", region="us-east-1", resource_type=rtype,
                          resource_id=rid, name=rid, tags={}, raw_data={}, status="running", scanned_at=T0)
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
