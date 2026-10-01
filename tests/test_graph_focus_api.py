"""GET /api/graph/focus + node endpoints over GraphQueryService (MVP-2.6.1 Plan A Task 9)."""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from agenticops.config import settings
from agenticops.galaxy.models import GalaxyBuild, ResourceRelation
from agenticops.graph import query_service as qs
from agenticops.graph.api import router
from agenticops.models import (AlertEvent, Base, ChangeRequest, CloudAccount, CloudResource, HealthIssue,
                               get_session)

NOW = datetime.now(timezone.utc)
OBSERVED = (NOW - timedelta(minutes=5)).replace(tzinfo=None)


@pytest.fixture
def db(tmp_path):
    import agenticops.models as models_mod
    models_mod._engine = None
    settings.database_url = f"sqlite:///{tmp_path}/graph_focus.db"
    Base.metadata.create_all(models_mod.get_engine())
    qs.clear_cache()
    s = get_session()
    yield s
    s.close()
    qs.clear_cache()
    models_mod._engine = None


@pytest_asyncio.fixture
async def client():
    app = FastAPI()
    app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


def _res(s, rid, acct, rtype, resource_id):
    s.add(CloudResource(id=rid, account_id=acct, provider="aws", region="us-east-1", resource_type=rtype,
                        resource_id=resource_id, name=resource_id, tags={}, raw_data={}))


def _rel(s, src, dst, rtype, *, prov="rule"):
    s.add(ResourceRelation(build_id=1, account_id=1, src_ref=src, dst_ref=dst, relation_type=rtype,
                           provenance=prov, evidence={"text": "x"}))


def _issue(s, ref, *, issue_type="cpu_spike", acct=1, **kw):
    issue = HealthIssue(resource_id=f"r-{ref}", resource_ref=ref, account_id=acct, severity="high",
                        status="open", source="test", title="t", description="d", issue_type=issue_type, **kw)
    s.add(issue)
    s.flush()
    return issue.id


def _cr(s, targets, acct=1):
    cr = ChangeRequest(title="t", description="d", requested_by="user:a@example.com", account_id=acct,
                       target_resources=targets)
    s.add(cr)
    s.flush()
    return cr.id


@pytest.fixture
def seed(db):
    """acct-a: VPC(1) ⊃ Subnet(2) ⊃ EC2(3); EC2 secured_by SG(4); ELB(5) routes_to EC2; RDS(6) secured_by SG;
    llm EC2 references RDS. acct-b: EC2(7). One published build."""
    db.add_all([CloudAccount(id=1, name="acct-a", provider="aws", credentials={}),
                CloudAccount(id=2, name="acct-b", provider="aws", credentials={})])
    for rid, acct, rtype, name in [(1, 1, "VPC", "vpc-1"), (2, 1, "Subnet", "subnet-1"), (3, 1, "EC2", "i-1"),
                                   (4, 1, "SecurityGroup", "sg-1"), (5, 1, "ELB", "alb"), (6, 1, "RDS", "db-1"),
                                   (7, 2, "EC2", "i-7")]:
        _res(db, rid, acct, rtype, name)
    db.add(GalaxyBuild(id=1, status="completed", trigger="manual", rules_published_at=NOW))
    db.flush()
    _rel(db, 1, 2, "contains")
    _rel(db, 2, 3, "contains")
    _rel(db, 3, 4, "secured_by")
    _rel(db, 5, 3, "routes_to")
    _rel(db, 6, 4, "secured_by")
    _rel(db, 3, 6, "references", prov="llm")
    db.commit()
    return db


def _refs(data):
    return {n["ref"] for n in data["nodes"]}


# ── argument handling ────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("query", ["", "?issue_id=1&resource_id=3", "?resource_id=3&change_request_id=1"])
async def test_exactly_one_subject(seed, client, query):
    resp = await client.get(f"/api/graph/focus{query}")
    assert resp.status_code == 422
    assert resp.json() == {"error": "pass exactly one of issue_id, resource_id, change_request_id"}


@pytest.mark.asyncio
@pytest.mark.parametrize("query", ["issue_id=999", "resource_id=999", "change_request_id=999"])
async def test_missing_subject_is_404(seed, client, query):
    assert (await client.get(f"/api/graph/focus?{query}")).status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("query", ["node_cap=10001", "node_cap=0", "edge_cap=50001", "depth=0", "issue_id=0"])
async def test_out_of_range_params_are_422(seed, client, query):
    sep = "&" if not query.startswith("issue_id") else ""
    base = "" if query.startswith("issue_id") else "resource_id=3"
    assert (await client.get(f"/api/graph/focus?{base}{sep}{query}")).status_code == 422


@pytest.mark.asyncio
async def test_depth_is_clamped_to_max_depth(seed, client, monkeypatch):
    monkeypatch.setattr(settings, "graph_query_max_depth", 1)
    data = (await client.get("/api/graph/focus?resource_id=3&depth=5")).json()
    assert data["depth"] == 1
    assert _refs(data) == {3, 2, 4, 5}


# ── issue subject ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_anchored_issue_graph_blast_and_window(seed, client):
    seed.add(AlertEvent(source="test", external_id="e1", severity="high", title="t", resource_id="alb",
                        account_id="acct-a", received_at=OBSERVED, disposition="noise"))
    iid = _issue(seed, 3, observed_at=OBSERVED, anchor_status="anchored",
                 anchor_candidates={"rule": "resource_id", "candidates": []})
    seed.commit()
    resp = await client.get(f"/api/graph/focus?issue_id={iid}&depth=2")
    assert resp.status_code == 200
    data = resp.json()
    assert data["build_id"] == 1 and data["depth"] == 2 and data["truncated"] is False
    assert data["anchor"] == {"kind": "issue", "id": iid, "refs": [3], "status": "anchored",
                              "rule": "resource_id", "candidates": []}
    assert _refs(data) == {1, 2, 3, 4, 5, 6}                  # compute relations, 2 hops, rule only
    assert all(e["provenance"] == "rule" for e in data["edges"])
    # structural: all rule relations within 2 hops; potential: downstream of EC2 = ELB; observed: ELB signalled
    assert data["blast"] == {"structural": 5, "potential": 1, "observed": 1, "truncated": False}
    assert data["window"] == {"start": (OBSERVED - timedelta(minutes=30)).isoformat(),
                              "end": (OBSERVED + timedelta(minutes=10)).isoformat()}
    anchor = next(n for n in data["nodes"] if n["ref"] == 3)
    assert (anchor["hops"], anchor["health"], anchor["issue_ids"]) == (0, "warning", [iid])


@pytest.mark.asyncio
async def test_issue_relation_set_follows_issue_class(seed, client):
    network = _issue(seed, 4, issue_type="security_exposure")
    database = _issue(seed, 6, issue_type="cpu_spike")          # a database anchor wins over the issue type
    seed.commit()
    assert _refs((await client.get(f"/api/graph/focus?issue_id={network}")).json()) == {4, 3, 6}
    assert _refs((await client.get(f"/api/graph/focus?issue_id={database}")).json()) == {6, 4}


@pytest.mark.asyncio
async def test_include_llm_adds_display_edges_only(seed, client):
    iid = _issue(seed, 3)
    seed.commit()
    data = (await client.get(f"/api/graph/focus?issue_id={iid}&include_llm=true")).json()
    assert _refs(data) == {3, 2, 4, 5, 6}                     # references is display-only, not a compute relation
    llm = [(e["src"], e["dst"], e["relation_type"]) for e in data["edges"] if e["provenance"] == "llm"]
    assert llm == [(3, 6, "references")]
    assert data["blast"] == {"structural": 5, "potential": 1, "observed": 0, "truncated": False}


@pytest.mark.asyncio
async def test_unanchored_issue_returns_empty_graph(seed, client):
    iid = _issue(seed, None, anchor_status="ambiguous",
                 anchor_candidates={"rule": "short_id", "candidates": [{"ref": 3, "account_id": 1,
                                                                        "reason": "short_id"}]})
    seed.commit()
    data = (await client.get(f"/api/graph/focus?issue_id={iid}")).json()
    assert (data["nodes"], data["edges"], data["build_id"]) == ([], [], 1)
    assert data["anchor"]["status"] == "ambiguous" and data["anchor"]["refs"] == []
    assert [c["ref"] for c in data["anchor"]["candidates"]] == [3]
    assert data["blast"] == {"structural": 0, "potential": 0, "observed": 0, "truncated": False}


@pytest.mark.asyncio
async def test_stale_ref_of_another_account_is_dropped(seed, client):
    iid = _issue(seed, 7, acct=1)                               # id 7 now belongs to acct-b
    seed.commit()
    data = (await client.get(f"/api/graph/focus?issue_id={iid}")).json()
    assert data["nodes"] == []
    assert (data["anchor"]["status"], data["anchor"]["rule"], data["anchor"]["refs"]) == \
        ("unanchored", "stale_ref", [])


@pytest.mark.asyncio
async def test_node_cap_truncates_display_not_blast(seed, client):
    iid = _issue(seed, 4, issue_type="security_exposure")
    seed.commit()
    data = (await client.get(f"/api/graph/focus?issue_id={iid}&node_cap=2")).json()
    assert len(data["nodes"]) == 2
    assert (data["truncated"], data["truncated_reason"]) == (True, "node_cap")
    assert data["blast"]["potential"] == 3 and data["blast"]["truncated"] is False


# ── resource and change-request subjects ─────────────────────────────


@pytest.mark.asyncio
async def test_resource_subject(seed, client):
    data = (await client.get("/api/graph/focus?resource_id=3")).json()
    assert data["anchor"] == {"kind": "resource", "id": 3, "refs": [3], "status": "anchored",
                              "rule": None, "candidates": []}
    assert _refs(data) == {3, 2, 4, 5}


@pytest.mark.asyncio
async def test_change_request_unions_resolved_targets(seed, client):
    crid = _cr(seed, [{"resource_id": "i-1", "db_id": 3}, {"resource_id": "db-1", "db_id": 6},
                      {"resource_id": "sg-1", "db_id": 4}, {"resource_id": "ghost", "db_id": None},
                      {"resource_id": "unresolved"}, {"resource_id": "i-1", "db_id": 3}])
    seed.commit()
    data = (await client.get(f"/api/graph/focus?change_request_id={crid}")).json()
    assert data["anchor"]["refs"] == [3, 4, 6] and data["anchor"]["status"] == "anchored"
    # SG 4 is one hop from start 3 but a start itself: it keeps hop 0 in the union
    assert {n["ref"]: n["hops"] for n in data["nodes"]} == {3: 0, 4: 0, 6: 0, 2: 1, 5: 1}
    # structural {1,2,5}, potential {5}: the starts are never counted
    assert data["blast"] == {"structural": 3, "potential": 1, "observed": 0, "truncated": False}
    keys = [(e["src"], e["dst"], e["relation_type"]) for e in data["edges"]]
    assert len(keys) == len(set(keys)) and len(keys) == 4


@pytest.mark.asyncio
async def test_change_request_without_resolved_targets(seed, client):
    crid = _cr(seed, [{"resource_id": "ghost", "db_id": None}])
    seed.commit()
    data = (await client.get(f"/api/graph/focus?change_request_id={crid}")).json()
    assert data["nodes"] == [] and data["anchor"]["status"] == "unanchored"


@pytest.mark.asyncio
async def test_no_published_build(db, client):
    db.add(CloudAccount(id=1, name="acct-a", provider="aws", credentials={}))
    _res(db, 3, 1, "EC2", "i-1")
    db.commit()
    data = (await client.get("/api/graph/focus?resource_id=3")).json()
    assert (data["build_id"], data["nodes"], data["edges"]) == (None, [], [])
    assert data["blast"] == {"structural": 0, "potential": 0, "observed": 0, "truncated": False}


# ── edge time and related links (MVP-2.6.1 Plan E, spec §3.E.3) ───────


@pytest.mark.asyncio
async def test_edges_carry_when_they_were_observed(seed, client):
    seed.query(ResourceRelation).filter_by(src_ref=5, dst_ref=3).update({"observed_at": OBSERVED})
    seed.commit()
    edges = (await client.get("/api/graph/focus?resource_id=3")).json()["edges"]
    at = {(e["src"], e["dst"]): e["observed_at"] for e in edges}
    assert at[(5, 3)] == OBSERVED.isoformat()
    assert all(isinstance(v, str) for v in at.values())


def _signal(s, resource_id, *, issue_id, disposition="merged", at=OBSERVED, n=1):
    for k in range(n):
        s.add(AlertEvent(source="test", external_id=f"{resource_id}-{disposition}-{issue_id}-{k}", severity="high",
                         title="t", resource_id=resource_id, account_id="acct-a", received_at=at,
                         disposition=disposition, health_issue_id=issue_id))


@pytest.mark.asyncio
async def test_related_merged_lists_the_other_resources_merged_in(seed, client):
    iid = _issue(seed, 3, observed_at=OBSERVED)              # resource_id "r-3", anchored on EC2 i-1
    _signal(seed, "db-1", issue_id=iid, n=2)                  # another resource, merged in twice
    _signal(seed, "db-1", issue_id=iid, at=OBSERVED - timedelta(minutes=1))
    _signal(seed, "ghost-1", issue_id=iid)                    # merged, but not in the inventory
    _signal(seed, "r-3", issue_id=iid)                        # the issue's own resource id
    _signal(seed, "i-1", issue_id=iid)                        # another name for the issue's own anchor
    _signal(seed, "alb", issue_id=iid, disposition="promoted")  # not merged
    _signal(seed, "sg-1", issue_id=iid + 1)                   # merged into another issue
    seed.commit()
    related = (await client.get(f"/api/graph/focus?issue_id={iid}")).json()["related"]
    assert related["merged"] == [
        {"resource_id": "db-1", "ref": 6, "type": "RDS", "name": "db-1", "anchor_status": "anchored",
         "signals": 3, "last_at": OBSERVED.isoformat()},
        {"resource_id": "ghost-1", "ref": None, "type": None, "name": None, "anchor_status": "unanchored",
         "signals": 1, "last_at": OBSERVED.isoformat()},
    ]
    assert related["truncated"] is False


@pytest.mark.asyncio
async def test_related_candidates_are_open_issues_two_hops_out_in_the_window(seed, client):
    iid = _issue(seed, 3, observed_at=OBSERVED)
    same = _issue(seed, 3, observed_at=OBSERVED + timedelta(minutes=1))       # the same anchor: 0 hops
    sg = _issue(seed, 4, observed_at=OBSERVED - timedelta(minutes=20))        # 1 hop, in the window
    rds = _issue(seed, 6, observed_at=OBSERVED + timedelta(minutes=5))        # 2 hops (via the SG)
    _issue(seed, 5, observed_at=OBSERVED - timedelta(hours=2))                # before the window
    closed = _issue(seed, 2, observed_at=OBSERVED)
    seed.get(HealthIssue, closed).status = "resolved"                        # not open
    _issue(seed, 7, acct=2, observed_at=OBSERVED)                             # another account's resource
    seed.commit()
    related = (await client.get(f"/api/graph/focus?issue_id={iid}")).json()["related"]
    assert [(c["issue_id"], c["ref"], c["hops"]) for c in related["candidates"]] == [
        (same, 3, 0), (sg, 4, 1), (rds, 6, 2)]
    assert related["candidates"][1] == {"issue_id": sg, "ref": 4, "hops": 1, "severity": "high", "title": "t",
                                        "status": "open",
                                        "signal_at": (OBSERVED - timedelta(minutes=20)).isoformat()}


async def _candidate_ids(client, iid):
    return [c["issue_id"] for c in (await client.get(f"/api/graph/focus?issue_id={iid}")).json()["related"]["candidates"]]


@pytest.mark.asyncio
async def test_a_stale_ref_into_another_account_is_not_a_candidate(seed, client):
    """An acct-b issue whose resource_ref names acct-a's SG (a stale ref, 1 hop out) is not acct-a's neighbor."""
    iid = _issue(seed, 3, observed_at=OBSERVED)
    sg = _issue(seed, 4, observed_at=OBSERVED)
    _issue(seed, 4, acct=2, observed_at=OBSERVED)
    seed.commit()
    assert await _candidate_ids(client, iid) == [sg]


@pytest.mark.asyncio
async def test_an_issue_three_hops_out_is_not_a_candidate(seed, client):
    """Subnet(8) sits in VPC(1): EC2(3) → Subnet(2) → VPC(1) → Subnet(8) is 3 hops, past the structural 2."""
    _res(seed, 8, 1, "Subnet", "subnet-8")
    _rel(seed, 1, 8, "contains")
    iid = _issue(seed, 3, observed_at=OBSERVED)
    vpc = _issue(seed, 1, observed_at=OBSERVED)
    _issue(seed, 8, observed_at=OBSERVED)
    seed.commit()
    assert await _candidate_ids(client, iid) == [vpc]


@pytest.mark.asyncio
async def test_an_issue_after_the_window_is_not_a_candidate(seed, client):
    """The window ends rca_topology_window_after_minutes (10) after the issue's signal; 30 minutes on is outside."""
    iid = _issue(seed, 3, observed_at=OBSERVED)
    sg = _issue(seed, 4, observed_at=OBSERVED + timedelta(minutes=10))
    _issue(seed, 6, observed_at=OBSERVED + timedelta(minutes=30))
    seed.commit()
    assert await _candidate_ids(client, iid) == [sg]


@pytest.mark.asyncio
async def test_related_lists_are_capped_and_say_so(seed, client, monkeypatch):
    from agenticops.graph import api
    monkeypatch.setattr(api, "_RELATED_CAP", 1)
    iid = _issue(seed, 3, observed_at=OBSERVED)
    _issue(seed, 4, observed_at=OBSERVED)
    _issue(seed, 6, observed_at=OBSERVED)
    seed.commit()
    related = (await client.get(f"/api/graph/focus?issue_id={iid}")).json()["related"]
    assert len(related["candidates"]) == 1 and related["truncated"] is True


@pytest.mark.asyncio
async def test_only_an_issue_has_related_links(seed, client):
    _issue(seed, 4, observed_at=OBSERVED)
    crid = _cr(seed, [{"resource_id": "i-1", "db_id": 3}])
    seed.commit()
    for query in ("resource_id=3", f"change_request_id={crid}"):
        data = (await client.get(f"/api/graph/focus?{query}")).json()
        assert data["related"] == {"merged": [], "candidates": [], "truncated": False}


# ── node endpoints ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_node_context(seed, client):
    resp = await client.get("/api/graph/node/3/context")
    assert resp.status_code == 200 and _refs(resp.json()) == {3, 2, 4, 5}
    assert (await client.get("/api/graph/node/999/context")).status_code == 404
    assert (await client.get("/api/graph/node/i-1/context")).status_code == 422


@pytest.mark.asyncio
async def test_node_blast_radius(seed, client):
    data = (await client.get("/api/graph/node/4/blast-radius")).json()
    assert _refs(data) == {4, 3, 6, 5} and data["count"] == 3
    assert (await client.get("/api/graph/node/4/blast-radius?depth=1")).json()["count"] == 2
    assert (await client.get("/api/graph/node/4/blast-radius?depth=4")).status_code == 422
    assert (await client.get("/api/graph/node/999/blast-radius")).status_code == 404


# ── retired IM enrichment ────────────────────────────────────────────


def test_im_alert_carries_no_graph_context():
    from agenticops.im import alert_pipeline
    from agenticops.integrations.alert_processor import AlertProcessResult

    alert_pipeline._cooldown_map.clear()
    with patch.object(alert_pipeline, "process_alert",
                      return_value=AlertProcessResult(action="created", health_issue_id=7)) as proc:
        result = alert_pipeline.handle_alert_message("ALARM: High CPU on i-abc123", "feishu", "c1")
    assert proc.call_args.kwargs["im_origin"] == {"platform": "feishu", "chat_id": "c1"}
    assert result.message == "Alert: ALARM: High CPU on i-abc123\nIssue #7 created. RCA triggered."


def test_webhook_signal_metric_data_has_no_graph_context(monkeypatch):
    from types import SimpleNamespace

    from agenticops.integrations.alert_processor import process_alert
    from agenticops.integrations.base import AlertPayload

    monkeypatch.setattr(settings, "webhook_auto_create_issue", True)
    seen = []

    def fake_gate(sig):
        seen.append(sig)
        return SimpleNamespace(disposition="promoted", signal_id=1, issue_id=7, reason="")

    monkeypatch.setattr("agenticops.services.signal_gate.process_signal", fake_gate)
    alert = AlertPayload(source="generic", external_id="x1", severity="high", title="High CPU",
                         description="d", resource_hint="i-abc123")
    origin = {"platform": "feishu", "chat_id": "c1", "graph_context": {"topology_summary": "old"}}
    assert process_alert(alert, im_origin=origin).health_issue_id == 7
    assert "graph_context" not in seen[0].metric_data      # no longer lifted into the issue
    assert seen[0].im_origin == origin                      # IM metadata passes through untouched


def test_retired_symbols_are_gone():
    import importlib.util

    from agenticops.agents import rca_agent
    from agenticops.im import alert_pipeline
    from agenticops.services import graph_sync_service

    assert importlib.util.find_spec("agenticops.graph.context") is None
    assert not hasattr(rca_agent, "_build_topology_context")
    assert not hasattr(alert_pipeline, "_get_graph_context")
    assert not hasattr(graph_sync_service, "trigger_sync_for_resource")
    assert not hasattr(graph_sync_service, "_sync_for_resource")
