"""Galaxy end-to-end (API surface, Bedrock mocked): seed -> rebuild -> status
-> overview -> drill-down expand -> provenance + health overlay + incremental."""

import json
import pytest
from starlette.testclient import TestClient

from agenticops.models import Base, get_session, get_db_session, CloudAccount, CloudResource, HealthIssue
from agenticops.galaxy import builder as B
from agenticops.web.app import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    import agenticops.models as models_mod
    from agenticops.config import settings
    models_mod._engine = None
    settings.database_url = f"sqlite:///{tmp_path}/galaxy_e2e.db"
    engine = models_mod.get_engine()
    Base.metadata.create_all(engine)

    # LLM proposes a grounded inferred_group edge between the two payments resources.
    def fake_call(prompt, model_id, max_tokens):
        return json.dumps({"edges": [
            {"source": "res:2", "target": "res:3", "relation_type": "inferred_group",
             "evidence": "name shares prefix payments", "confidence": 0.8},
            {"source": "res:2", "target": "res:9999", "relation_type": "references",
             "evidence": "hallucinated", "confidence": 0.9},
        ]}), {"input": 500, "output": 120}
    monkeypatch.setattr(B, "_call_bedrock", fake_call)

    s = get_session()
    acct = CloudAccount(name="prod", provider="aws", is_enabled=True)
    s.add(acct); s.flush()
    s.add_all([
        CloudResource(account_id=acct.id, provider="aws", region="cn-north-1",
                      resource_type="VPC", resource_id="vpc-a", name="vpc-a",
                      tags={"Project": "payments"}, raw_data={}),
        CloudResource(account_id=acct.id, provider="aws", region="cn-north-1",
                      resource_type="EC2", resource_id="i-1", name="payments-api",
                      tags={"Project": "payments"},
                      raw_data={"NetworkInterfaces": [{"VpcId": "vpc-a"}], "Purpose": "payments"}),
        CloudResource(account_id=acct.id, provider="aws", region="cn-north-1",
                      resource_type="RDS", resource_id="db-1", name="payments-db",
                      tags={"Project": "payments"},
                      raw_data={"VpcId": "vpc-a", "Purpose": "payments"}),
    ])
    s.add(HealthIssue(resource_id="i-1", severity="critical", source="manual",
                      title="api down", description="d", status="open"))
    s.commit(); s.close()
    yield TestClient(app)
    models_mod._engine = None


def test_full_galaxy_flow(client):
    # 1. First build
    r = client.post("/api/galaxy/rebuild", params={"full": True})
    assert r.status_code == 202
    bid = r.json()["build_id"]

    # 2. Status reflects completion + cost + drop count
    st = client.get("/api/galaxy/status").json()["build"]
    assert st["status"] == "completed"
    assert st["dropped_edge_count"] == 1        # hallucinated endpoint dropped
    assert st["cost_usd"] >= 0

    # 3. Overview: account + payments group, health rolled up to critical
    ov = client.get("/api/galaxy/overview").json()
    grp = next(n for n in ov["nodes"] if n["id"] == "grp:1:project:payments")
    assert grp["health"] == "critical"
    assert grp["resource_count"] == 3

    # 4. Drill down into the group
    ex = client.get("/api/galaxy/expand", params={"group": "grp:1:project:payments"}).json()
    node_ids = {n["id"] for n in ex["nodes"]}
    assert {"res:1", "res:2", "res:3"} <= node_ids
    # 5. Provenance: at least one llm dashed edge survived verification, rest are rule
    provs = {e["provenance"] for e in ex["edges"]}
    assert "llm" in provs
    assert any(e["relation_type"] == "inferred_group" and e["provenance"] == "llm" for e in ex["edges"])
    # 6. Health overlay on the EC2
    ec2 = next(n for n in ex["nodes"] if n["id"] == "res:2")
    assert ec2["health"] == "critical"

    # 7. Incremental: no change -> same build id, no new build
    r2 = client.post("/api/galaxy/rebuild", params={"full": False})
    assert r2.json()["build_id"] == bid
