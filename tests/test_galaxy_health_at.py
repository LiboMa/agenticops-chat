"""MVP-2.9.0 N15: which resources had an open issue at a moment of the last 24 hours.

No history of a resource's health is stored. What can be worked out truthfully for a past moment T: which issues
were open then — an issue is on record from `detected_at`, and its status at T is the status its first move AFTER
T started from (or today's status when it has not moved since) — and which resources a scan had already stopped
seeing (`absent_since <= T`). What cannot: the severity an issue had then and the resource it was anchored to
then (both are overwritten in place), nor a resource that was gone at T and has come back. The answer says the
first; the page says the rest.
"""
import json
from datetime import datetime, timedelta, timezone

import pytest
from starlette.testclient import TestClient

from agenticops.galaxy.models import GalaxyBuild
from agenticops.models import Base, CloudAccount, CloudResource, HealthIssue, PipelineEvent, get_session


def _iso(ts):
    return ts.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@pytest.fixture
def world(tmp_path, monkeypatch):
    """Five resources of one account and a completed build; `now` is the real clock (the route reads it)."""
    import agenticops.models as models_mod
    from agenticops.config import settings
    from agenticops.web.app import app
    models_mod._engine = None
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/replay.db")
    Base.metadata.create_all(models_mod.get_engine())
    now = datetime.now(timezone.utc)
    s = get_session()
    acct = CloudAccount(name="acct-a", provider="aws", is_enabled=True)
    s.add(acct); s.flush()
    res = []
    for n in range(1, 6):
        r = CloudResource(account_id=acct.id, provider="aws", region="us-east-1", resource_type="EC2", resource_id=f"i-{n}",
                          name=f"web-{n}", tags={}, raw_data={})
        s.add(r); res.append(r)
    s.flush()
    res[3].absent_since = now - timedelta(hours=6)                     # r4: a scan stopped seeing it six hours ago
    s.add(GalaxyBuild(status="completed", trigger="test", started_at=now - timedelta(hours=30), finished_at=now - timedelta(hours=30),
                      rule_graph={"nodes": [], "edges": []}, llm_graph={"edges": []}))
    s.commit()
    ids = {"acct": acct.id, **{f"r{n}": r.id for n, r in enumerate(res, 1)}}
    s.close()
    yield TestClient(app), ids, now
    models_mod._engine = None


def _issue(acct, ref, *, hours_ago, status="open", severity="high", now):
    s = get_session()
    try:
        i = HealthIssue(resource_id=f"x-{ref}", severity=severity, source="manual", account_id=acct, title="t", description="d",
                        status=status, resource_ref=ref, anchor_status="anchored", detected_at=now - timedelta(hours=hours_ago))
        s.add(i); s.commit()
        return i.id
    finally:
        s.close()


def _moved(issue_id, frm, to, *, hours_ago, now):
    s = get_session()
    try:
        s.add(PipelineEvent(health_issue_id=issue_id, event_type="status_changed", stage="status", status="completed",
                            detail=json.dumps({"from": frm, "to": to}), actor="user:alice", created_at=now - timedelta(hours=hours_ago)))
        s.commit()
    finally:
        s.close()


def _at(client, now, hours_ago):
    r = client.get("/api/galaxy/health", params={"at": _iso(now - timedelta(hours=hours_ago))})
    assert r.status_code == 200, r.text
    return r.json()


def test_an_issue_counts_from_when_it_was_detected(world):
    client, ids, now = world
    _issue(ids["acct"], ids["r1"], hours_ago=10, now=now)
    assert _at(client, now, 5)["health"] == {f"res:{ids['r1']}": "warning"}
    assert _at(client, now, 11)["health"] == {}                        # it was not on record yet
    assert client.get("/api/galaxy/health").json()["health"] == {f"res:{ids['r1']}": "warning"}


def test_an_issue_closed_since_then_was_open_then(world):
    client, ids, now = world
    b = _issue(ids["acct"], ids["r2"], hours_ago=10, status="resolved", severity="critical", now=now)
    _moved(b, "fix_executed", "resolved", hours_ago=2, now=now)
    assert _at(client, now, 5)["health"] == {f"res:{ids['r2']}": "critical"}     # resolved two hours ago: open five hours ago
    assert _at(client, now, 1)["health"] == {}
    assert client.get("/api/galaxy/health").json()["health"] == {}


def test_an_issue_dismissed_and_reopened_was_closed_in_between(world):
    client, ids, now = world
    c = _issue(ids["acct"], ids["r3"], hours_ago=10, status="open", now=now)
    _moved(c, "open", "dismissed", hours_ago=8, now=now)
    _moved(c, "dismissed", "open", hours_ago=1, now=now)
    assert _at(client, now, 9)["health"] == {f"res:{ids['r3']}": "warning"}      # before it was dismissed
    assert _at(client, now, 5)["health"] == {}                                    # dismissed then
    assert _at(client, now, 0.5)["health"] == {f"res:{ids['r3']}": "warning"}    # reopened since


def test_several_moves_after_the_moment_do_not_confuse_it(world):
    """What counts is the status the FIRST move after T started from — later moves say nothing about T."""
    client, ids, now = world
    d = _issue(ids["acct"], ids["r1"], hours_ago=10, status="resolved", now=now)
    _moved(d, "open", "investigating", hours_ago=4, now=now)
    _moved(d, "investigating", "root_cause_identified", hours_ago=3, now=now)
    _moved(d, "root_cause_identified", "resolved", hours_ago=2, now=now)
    assert _at(client, now, 5)["health"] == {f"res:{ids['r1']}": "warning"}
    assert _at(client, now, 2.5)["health"] == {f"res:{ids['r1']}": "warning"}
    assert _at(client, now, 1)["health"] == {}


def test_the_worst_of_the_issues_open_then(world):
    client, ids, now = world
    _issue(ids["acct"], ids["r1"], hours_ago=10, severity="low", now=now)
    late = _issue(ids["acct"], ids["r1"], hours_ago=3, severity="critical", now=now)
    assert _at(client, now, 5)["health"] == {f"res:{ids['r1']}": "notice"}        # the critical one came later
    assert _at(client, now, 2)["health"] == {f"res:{ids['r1']}": "critical"}
    assert late


def test_a_resource_gone_then_is_gone_then_and_not_before(world):
    client, ids, now = world
    assert _at(client, now, 5)["absent"] == [f"res:{ids['r4']}"]
    assert _at(client, now, 7)["absent"] == []                                    # a scan still saw it seven hours ago
    assert client.get("/api/galaxy/health").json()["absent"] == [f"res:{ids['r4']}"]


def test_the_answer_says_which_moment_it_is_of(world):
    client, ids, now = world
    asked = _iso(now - timedelta(hours=5))
    body = client.get("/api/galaxy/health", params={"at": asked}).json()
    assert body["as_of"][:19] == asked[:19] and body["as_of"].endswith("Z") and body["build_id"] is not None
    assert "as_of" not in client.get("/api/galaxy/health").json()                # the reading of now is as it was


@pytest.mark.parametrize("at", ["yesterday", "", "2026-13-45T00:00:00Z"])
def test_a_moment_that_is_no_time_is_refused(world, at):
    client, _ids, _now = world
    assert client.get("/api/galaxy/health", params={"at": at}).status_code == 422


def test_only_the_last_day_and_never_the_future(world):
    client, _ids, now = world
    assert client.get("/api/galaxy/health", params={"at": _iso(now + timedelta(minutes=5))}).status_code == 422
    assert client.get("/api/galaxy/health", params={"at": _iso(now - timedelta(hours=25))}).status_code == 422
    assert client.get("/api/galaxy/health", params={"at": _iso(now - timedelta(hours=23, minutes=59))}).status_code == 200


def test_an_issue_of_another_account_does_not_colour_the_resource(world):
    """The live overlay's rule (a stale anchor may point at an id another account's row now uses) holds for the past."""
    client, ids, now = world
    s = get_session()
    other = CloudAccount(name="acct-b", provider="aws", is_enabled=True)
    s.add(other); s.commit(); other_id = other.id; s.close()
    _issue(other_id, ids["r1"], hours_ago=10, now=now)
    assert _at(client, now, 5)["health"] == {}
