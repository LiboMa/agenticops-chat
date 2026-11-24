"""MVP-2.9.0 N21 (the 2.8.0 spec's S4): GET /api/reports searches the whole set on the server — title, summary,
body or number — inside UTC days, and says how many there are; only what the caller may see is listed or counted."""
import inspect
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from starlette.testclient import TestClient

from agenticops.auth.actor import Actor
from agenticops.models import Base, Report, get_session

ALICE = Actor("user", "alice@example.com", 1, ("read", "write"))
BOB = Actor("user", "bob@example.com", 2, ("read", "write"))


@pytest.fixture
def env(tmp_path, monkeypatch):
    import agenticops.audit.models  # noqa: F401
    import agenticops.models as models_mod
    from agenticops.config import settings
    from agenticops.web import deps
    from agenticops.web.app import app
    monkeypatch.setattr(models_mod, "_engine", None)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/reports.db")
    monkeypatch.setattr(settings, "api_auth_enabled", True)
    monkeypatch.setattr(settings, "rbac_enforce", False)
    Base.metadata.create_all(models_mod.get_engine())
    who = {"actor": ALICE}
    app.dependency_overrides[deps.current_actor] = lambda: who["actor"]
    client = TestClient(app)

    def as_(actor):
        who["actor"] = actor
        return client
    yield SimpleNamespace(as_=as_, client=client)
    app.dependency_overrides.pop(deps.current_actor, None)


def _report(title="daily", summary="s", body="all fine", at=None, rtype="daily", **kw):
    s = get_session()
    try:
        r = Report(report_type=rtype, title=title, summary=summary, content_markdown=body,
                   created_at=at or datetime(2026, 11, 7, 9, 3, tzinfo=timezone.utc), **kw)
        s.add(r)
        s.commit()
        return r.id
    finally:
        s.close()


def _day(d, h=12):
    return datetime(2026, 11, d, h, 0, tzinfo=timezone.utc)


def _titles(client, query=""):
    r = client.get(f"/api/reports{query}")
    assert r.status_code == 200, r.text
    return [i["title"] for i in r.json()["items"]]


def test_the_list_is_items_and_totals_newest_first(env):
    for d in (3, 5, 4):
        _report(title=f"day {d}", at=_day(d))
    out = env.client.get("/api/reports").json()
    assert set(out) == {"items", "total", "all_total"}
    assert [i["title"] for i in out["items"]] == ["day 5", "day 4", "day 3"]
    assert (out["total"], out["all_total"]) == (3, 3)
    page = env.client.get("/api/reports?limit=1&offset=1").json()
    assert [i["title"] for i in page["items"]] == ["day 4"] and page["total"] == 3      # the total is not the page's


def test_search_reads_the_title_the_summary_and_the_body(env):
    _report(title="Nginx outage", at=_day(1))
    _report(title="b", summary="the Redis failover", at=_day(2))
    _report(title="c", body="## Findings\n\nkernel 6.1 panics on node-7", at=_day(3))
    _report(title="d", at=_day(4))
    assert _titles(env.client, "?q=nginx") == ["Nginx outage"]          # any case
    assert _titles(env.client, "?q=FAILOVER") == ["b"]
    assert _titles(env.client, "?q=node-7") == ["c"]
    out = env.client.get("/api/reports?q=node-7").json()
    assert (out["total"], out["all_total"]) == (1, 4)                   # «matched 1» and «4 in all» are two numbers


def test_percent_and_underscore_are_characters(env):
    _report(title="cpu at 100% for an hour", at=_day(1))
    _report(title="snake_case names", at=_day(2))
    _report(title="plain", at=_day(3))
    assert _titles(env.client, "?q=%25") == ["cpu at 100% for an hour"]
    assert _titles(env.client, "?q=_") == ["snake_case names"]


def test_a_number_finds_the_report(env):
    first = _report(title="first", at=_day(1))
    _report(title=f"mentions {first} in its title", at=_day(2))
    _report(title="other", at=_day(3))
    _report(title="follow-up", body=f"see R#{first} for the cause", at=_day(4))
    assert _titles(env.client, f"?q=R%23{first}") == ["first"]          # R#<id>: the reference — not a text that cites it
    assert _titles(env.client, f"?q=r{first}") == ["first"]
    # a bare number: that report first, then every text that holds it, newest first
    assert _titles(env.client, f"?q={first}") == ["first", "follow-up", f"mentions {first} in its title"]
    assert _titles(env.client, "?q=R%239999") == []


def test_the_dates_are_whole_utc_days(env):
    _report(title="6th late", at=datetime(2026, 11, 6, 23, 59, 59, tzinfo=timezone.utc))
    _report(title="7th first", at=datetime(2026, 11, 7, 0, 0, 0, tzinfo=timezone.utc))
    _report(title="7th last", at=datetime(2026, 11, 7, 23, 59, 59, tzinfo=timezone.utc))
    _report(title="8th", at=datetime(2026, 11, 8, 0, 0, 0, tzinfo=timezone.utc))
    assert _titles(env.client, "?date_from=2026-11-07&date_to=2026-11-07") == ["7th last", "7th first"]
    assert _titles(env.client, "?date_from=2026-11-07") == ["8th", "7th last", "7th first"]
    assert _titles(env.client, "?date_to=2026-11-06") == ["6th late"]
    assert env.client.get("/api/reports?date_from=2026-11-08&date_to=2026-11-07").json()["total"] == 0
    for bad in ("date_from=yesterday", "date_to=2026-13-01", "date_from=2026-11-07T10:00:00"):
        assert env.client.get(f"/api/reports?{bad}").status_code == 422, bad


def test_the_filters_add_up_and_paging_keeps_them(env):
    for d in (1, 2, 3):
        _report(title=f"inc {d}", body="disk full", rtype="incident", at=_day(d))
    _report(title="daily", body="disk full", at=_day(4))
    q = "?report_type=incident&q=disk&date_from=2026-11-02"
    assert _titles(env.client, q) == ["inc 3", "inc 2"]
    out = env.client.get(f"/api/reports{q}&limit=1&offset=1").json()
    assert ([i["title"] for i in out["items"]], out["total"], out["all_total"]) == (["inc 2"], 2, 4)


def test_only_what_the_caller_may_see_is_listed_or_counted(env):
    _report(title="for everyone", at=_day(1))
    _report(title="alice's own", at=_day(2), visibility="private", owner_user_id=1)
    mine = env.as_(ALICE).get("/api/reports?q=own").json()
    assert ([i["title"] for i in mine["items"]], mine["total"], mine["all_total"]) == (["alice's own"], 1, 2)
    theirs = env.as_(BOB).get("/api/reports?q=own").json()
    assert (theirs["items"], theirs["total"], theirs["all_total"]) == ([], 0, 1)


def test_a_report_carries_its_coverage(env):
    cov = {"accounts": ["prod"], "regions": ["us-east-1"], "completeness": "partial",
           "partial": {"truncated": 1, "offloaded": 0, "failed": 0}, "read_at": "2026-11-07T09:03:00Z"}
    with_cov = _report(title="with", at=_day(2), coverage=cov)
    without = _report(title="without", at=_day(1))
    items = {i["id"]: i for i in env.client.get("/api/reports").json()["items"]}
    assert items[with_cov]["coverage"] == cov and items[without]["coverage"] is None
    assert env.client.get(f"/api/reports/{with_cov}").json()["coverage"] == cov


@pytest.mark.parametrize("query", ["limit=0", "offset=-1", "q=" + "x" * 201])
def test_what_cannot_be_read_is_refused(env, query):
    assert env.client.get(f"/api/reports?{query}").status_code == 422


def test_the_handler_is_a_plain_function():
    from agenticops.web import app as app_mod
    assert not inspect.iscoroutinefunction(app_mod.api_list_reports)
