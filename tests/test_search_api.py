"""GET /api/search (MVP-2.9.0 N18): what was typed is matched literally, a number finds the thing with that number,
and the answer has an order (the command bar of NewUI lists what this returns)."""

from datetime import datetime, timedelta, timezone

import pytest
from starlette.testclient import TestClient

from agenticops.models import Base, ChangeRequest, CloudAccount, CloudResource, FixPlan, HealthIssue, RCAResult, get_session

T0 = datetime(2026, 11, 1, 8, 0, tzinfo=timezone.utc)


@pytest.fixture
def client(tmp_path, monkeypatch):
    import agenticops.models as models_mod
    import agenticops.audit.models  # noqa: F401
    from agenticops.config import settings
    from agenticops.web.app import app
    monkeypatch.setattr(models_mod, "_engine", None)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/search.db")
    monkeypatch.setattr(settings, "change_management_enabled", True)
    monkeypatch.setattr(settings, "api_auth_enabled", False)
    Base.metadata.create_all(models_mod.get_engine())
    s = get_session()
    s.add(CloudAccount(name="dev", provider="aws", is_enabled=True, credentials={}, regions=["us-east-1"]))
    s.commit(); s.close()
    yield TestClient(app)


def _issue(title, *, minutes=0, description="d"):
    s = get_session()
    try:
        row = HealthIssue(account_id=1, title=title, description=description, severity="low", source="test", status="open",
                          resource_id="i-0abc", detected_at=T0 + timedelta(minutes=minutes))
        s.add(row); s.commit()
        return row.id
    finally:
        s.close()


def _change(title, *, minutes=0):
    s = get_session()
    try:
        row = ChangeRequest(title=title, description="d", source="web", requested_by="user:alice", status="draft",
                            created_at=T0 + timedelta(minutes=minutes))
        s.add(row); s.commit()
        return row.id
    finally:
        s.close()


def _resource(name, resource_id):
    s = get_session()
    try:
        row = CloudResource(account_id=1, provider="aws", region="us-east-1", resource_type="EC2", resource_id=resource_id, name=name)
        s.add(row); s.commit()
        return row.id
    finally:
        s.close()


def _found(client, q, group, **params):
    r = client.get("/api/search", params={"q": q, **params})
    assert r.status_code == 200, r.text
    return [x["id"] for x in r.json()["results"].get(group, [])]


def test_a_wildcard_typed_into_the_search_is_a_character(client):
    plain = _issue("Disk usage high")
    percent = _issue("CPU at 100% for an hour")
    under = _issue("Queue web_tier is backing up")
    assert _found(client, "100%", "issues") == [percent]
    assert _found(client, "%", "issues") == [percent]              # used to match every issue
    assert _found(client, "_", "issues") == [under]                # used to match every issue
    assert _found(client, "disk", "issues") == [plain]
    assert _found(client, "DISK", "issues") == [plain]


def test_the_same_holds_for_every_group(client):
    _change("Scale out"); pc = _change("Raise the limit by 50%")
    _resource("web", "i-0aaa"); under = _resource("db_main", "i-0bbb")
    assert _found(client, "%", "change_requests") == [pc]
    assert _found(client, "_", "resources") == [under]


def test_the_newest_comes_first_and_the_cut_keeps_the_newest(client):
    ids = [_issue(f"SSH open to the world #{k}", minutes=k) for k in range(8)]
    assert _found(client, "ssh open", "issues") == ids[::-1][:5]                 # 5 by default: the five newest
    assert _found(client, "ssh open", "issues", limit=3) == ids[::-1][:3]
    changes = [_change(f"Rotate keys {k}", minutes=k) for k in range(3)]
    assert _found(client, "rotate", "change_requests") == changes[::-1]


def test_a_number_finds_the_thing_with_that_number_first(client):
    target = _issue("Completely unrelated title", minutes=-60)                      # the oldest, and no number in it
    # newer issues whose TITLES hold that number: by date alone they would come first
    others = [_issue(f"Volume {target} of 9 is full ({k})", minutes=k) for k in range(3)]
    assert _found(client, str(target), "issues") == [target, *others[::-1]]          # the item with that number, then the newest
    for q in (f"I#{target}", f"i{target}", f"I{target}"):
        assert _found(client, q, "issues")[0] == target, q
    change = _change("No digits here", minutes=-60)
    newer = _change(f"Rotate key {change} of 5", minutes=5)
    assert _found(client, str(change), "change_requests") == [change, newer]
    for q in (f"C#{change}", f"c{change}"):
        assert _found(client, q, "change_requests")[0] == change, q
    # a reference of one kind is not a number of another: «C#n» finds no issue by its id
    assert target not in _found(client, f"C#{target}", "issues")


def test_r_number_finds_a_resource_by_its_inventory_number(client):
    a = _resource("web", "i-0aaa"); b = _resource("db", "i-0bbb")
    assert _found(client, f"R#{b}", "resources") == [b]
    assert _found(client, f"r{a}", "resources") == [a]
    assert _found(client, "i-0bbb", "resources") == [b]                              # the native id still matches as text


def test_groups_and_limits_are_as_before(client):
    _issue("alpha"); _change("alpha change"); _resource("alpha-host", "i-0ccc")
    body = client.get("/api/search", params={"q": "alpha"}).json()
    assert body["query"] == "alpha"
    assert set(body["results"]) == {"issues", "fix_plans", "change_requests", "reports", "resources"}
    assert set(client.get("/api/search", params={"q": "alpha", "types": "issues"}).json()["results"]) == {"issues"}
    assert client.get("/api/search", params={"q": "alpha", "limit": 11}).status_code == 422
    assert client.get("/api/search", params={"q": ""}).status_code == 422


def test_the_route_is_a_plain_function():
    """One process (CLAUDE.md): a handler that reads the database must not be `async def` — it would hold the event
    loop, and every chat stream with it."""
    import inspect
    from agenticops.web.routers.search import api_search
    assert not inspect.iscoroutinefunction(api_search)


def test_a_limit_below_one_is_refused(client):
    """MVP-2.9.0 N27 (review): `limit=-1` passed validation, and SQLite reads LIMIT -1 as «no limit» — every match
    of every group came back in one answer."""
    for _ in range(12):
        _issue("alpha everywhere")
    for bad in (-1, 0):
        assert client.get("/api/search", params={"q": "alpha", "limit": bad}).status_code == 422
    assert len(client.get("/api/search", params={"q": "alpha", "limit": 1}).json()["results"]["issues"]) == 1
