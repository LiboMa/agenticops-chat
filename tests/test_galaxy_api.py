"""Galaxy API contract: rebuild mutex, status shape, overview/expand + health overlay."""

import json
import pytest
from starlette.testclient import TestClient

from agenticops.models import Base, get_session, get_db_session, CloudAccount, CloudResource, HealthIssue
from agenticops.galaxy.models import GalaxyBuild
from agenticops.galaxy import builder as B
from agenticops.web.app import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    import agenticops.models as models_mod
    from agenticops.config import settings
    models_mod._engine = None
    settings.database_url = f"sqlite:///{tmp_path}/galaxy_api.db"
    engine = models_mod.get_engine()
    Base.metadata.create_all(engine)

    def fake_call(prompt, model_id, max_tokens):
        return json.dumps({"edges": []}), {"input": 10, "output": 10}
    monkeypatch.setattr(B, "_call_bedrock", fake_call)

    s = get_session()
    acct = CloudAccount(name="acct-a", provider="aws", is_enabled=True)
    s.add(acct); s.flush()
    s.add_all([
        CloudResource(account_id=acct.id, provider="aws", region="cn-north-1",
                      resource_type="VPC", resource_id="vpc-a", name="vpc-a",
                      tags={"Project": "demo"}, raw_data={}),
        CloudResource(account_id=acct.id, provider="aws", region="cn-north-1",
                      resource_type="EC2", resource_id="i-1", name="web",
                      tags={"Project": "demo"}, raw_data={"NetworkInterfaces": [{"VpcId": "vpc-a"}]}),
    ])
    s.add(HealthIssue(resource_id="i-1", severity="critical", source="manual", account_id=acct.id,
                      title="down", description="d", status="open"))
    s.commit(); s.close()
    yield TestClient(app)
    models_mod._engine = None


def test_status_empty_then_rebuild(client):
    r = client.get("/api/galaxy/status")
    assert r.status_code == 200
    assert r.json()["build"] is None

    r = client.post("/api/galaxy/rebuild", params={"full": True})
    assert r.status_code == 202
    bid = r.json()["build_id"]
    assert bid > 0

    r = client.get("/api/galaxy/status")
    body = r.json()["build"]
    assert body["status"] == "completed"
    assert body["node_count"] >= 3  # account + vpc + ec2 (+ group)


def test_rebuild_conflict_when_running(client):
    with get_db_session() as s:
        s.add(GalaxyBuild(status="running", trigger="manual"))
    r = client.post("/api/galaxy/rebuild")
    assert r.status_code == 409


def test_overview_has_account_and_group_nodes(client):
    client.post("/api/galaxy/rebuild", params={"full": True})
    r = client.get("/api/galaxy/overview")
    assert r.status_code == 200
    kinds = {n["kind"] for n in r.json()["nodes"]}
    assert "account" in kinds and "group" in kinds


def test_expand_group_health_and_provenance(client):
    client.post("/api/galaxy/rebuild", params={"full": True})
    r = client.get("/api/galaxy/expand", params={"group": "grp:1:project:demo"})
    assert r.status_code == 200
    body = r.json()
    node_ids = {n["id"] for n in body["nodes"]}
    assert "res:2" in node_ids  # the EC2
    ec2 = next(n for n in body["nodes"] if n["id"] == "res:2")
    assert ec2["health"] == "critical"  # from the open critical HealthIssue on i-1
    assert body["truncated"] is False
    assert all("provenance" in e for e in body["edges"])


def test_graph_full_payload(client):
    client.post("/api/galaxy/rebuild", params={"full": True})
    r = client.get("/api/galaxy/graph")
    assert r.status_code == 200
    body = r.json()
    assert body["build_id"] is not None
    kinds = {n["kind"] for n in body["nodes"]}
    assert {"account", "group", "resource"} <= kinds
    # slim edge keys (s/t/r/p), health overlay on the EC2
    assert all({"s", "t", "r", "p"} <= set(e) for e in body["edges"])
    ec2 = next(n for n in body["nodes"] if n["id"] == "res:2")
    assert ec2["health"] == "critical"


# ── MVP-2.6.1: rebuild is a normal build; reads follow finish time ──


def test_rebuild_is_a_normal_llm_build(client, monkeypatch):
    seen = {}

    def fake_build(trigger, full, llm):
        seen.update(trigger=trigger, full=full, llm=llm)
        return 7

    monkeypatch.setattr(B, "build_graph", fake_build)
    r = client.post("/api/galaxy/rebuild", params={"full": True})
    assert r.status_code == 202 and r.json()["build_id"] == 7
    assert seen == {"trigger": "manual", "full": True, "llm": True}


def test_reads_follow_finish_time_and_status_prefers_a_running_build(client):
    from datetime import datetime, timedelta

    t = datetime(2026, 9, 28, 8)
    empty = {"nodes": [], "edges": []}
    with get_db_session() as s:
        # A normal build opened first but finished after the rule-only refresh opened during its LLM phase.
        normal = GalaxyBuild(status="completed", trigger="manual", started_at=t,
                             finished_at=t + timedelta(minutes=5), rule_graph=empty, llm_graph={"edges": []})
        s.add(normal)
        s.flush()
        refresh = GalaxyBuild(status="completed", trigger="k8s-discovery", started_at=t + timedelta(minutes=1),
                              finished_at=t + timedelta(minutes=1), rule_graph=empty, llm_graph={"edges": []})
        s.add(refresh)
        s.flush()
        normal_id, refresh_id = normal.id, refresh.id
    assert refresh_id > normal_id
    assert client.get("/api/galaxy/graph").json()["build_id"] == normal_id
    assert client.get("/api/galaxy/status").json()["build"]["id"] == normal_id
    with get_db_session() as s:
        running = GalaxyBuild(status="running", trigger="auto", started_at=t + timedelta(minutes=6))
        s.add(running)
        s.flush()
        running_id = running.id
        s.add(GalaxyBuild(status="completed", trigger="rca-recollect", started_at=t + timedelta(minutes=7),
                          finished_at=t + timedelta(minutes=7), rule_graph=empty, llm_graph={"edges": []}))
    assert client.get("/api/galaxy/status").json()["build"]["id"] == running_id


# ── four-value health overlay (MVP-2.6.1) ────────────────────────────


def _health_cases():
    """acct-a VPC (res:1): an open low issue, a resolved and a dismissed critical one → notice.
    acct-a Subnet (res:3, Project=demo): no issue → unknown.
    acct-b EC2 (res:4): absent; an acct-a issue's stale ref points at it → must not colour."""
    from datetime import datetime

    with get_db_session() as s:
        a = s.query(CloudAccount).filter_by(name="acct-a").one()
        b = CloudAccount(name="acct-b", provider="aws", is_enabled=True)
        s.add(b); s.flush()
        s.add_all([
            CloudResource(account_id=a.id, provider="aws", region="cn-north-1", resource_type="Subnet",
                          resource_id="subnet-a", name="subnet-a", tags={"Project": "demo"},
                          raw_data={"VpcId": "vpc-a"}),
            CloudResource(account_id=b.id, provider="aws", region="cn-north-1", resource_type="EC2",
                          resource_id="i-9", name="gone", tags={}, raw_data={},
                          absent_since=datetime(2026, 9, 28)),
        ])
        s.flush()

        def issue(ref, resource_id, severity, status="open"):
            s.add(HealthIssue(resource_id=resource_id, resource_ref=ref, account_id=a.id,
                              anchor_status="anchored", severity=severity, source="manual", title="t",
                              description="d", status=status))

        issue(1, "vpc-a", "low")
        issue(1, "vpc-a", "critical", "resolved")
        issue(1, "vpc-a", "critical", "dismissed")
        issue(4, "i-9", "critical")  # stale: res:4 belongs to acct-b now


def test_graph_health_is_four_valued_and_follows_the_anchor(client):
    _health_cases()
    client.post("/api/galaxy/rebuild", params={"full": True})
    nodes = {n["id"]: n for n in client.get("/api/galaxy/graph").json()["nodes"]}
    assert nodes["res:2"]["health"] == "critical"  # the fixture's i-1 issue, anchored after the build
    assert nodes["res:1"]["health"] == "notice"    # low counts; resolved / dismissed do not
    assert nodes["res:3"]["health"] == "unknown"   # no issue is not "healthy"
    assert nodes["res:4"]["health"] == "unknown"   # another account's issue behind a stale ref
    assert (nodes["res:4"]["absent"], nodes["res:1"]["absent"]) == (True, False)
    assert {"health", "absent"}.isdisjoint(nodes["acct:1"])


def test_overview_and_expand_use_four_values(client):
    _health_cases()
    client.post("/api/galaxy/rebuild", params={"full": True})
    ov = {n["id"]: n for n in client.get("/api/galaxy/overview").json()["nodes"]}
    assert (ov["acct:1"]["health"], ov["acct:1"]["open_issues"]) == ("critical", 2)
    assert (ov["acct:2"]["health"], ov["acct:2"]["open_issues"]) == ("unknown", 0)
    worst = client.get("/api/galaxy/expand", params={"group": "grp:1:project:demo", "health": "worst"}).json()
    assert [n["id"] for n in worst["nodes"]] == ["res:2", "res:1"]  # worst first, unknown left out
    every = client.get("/api/galaxy/expand", params={"group": "grp:1:project:demo"}).json()
    assert [n["health"] for n in every["nodes"]] == ["critical", "notice", "unknown"]
