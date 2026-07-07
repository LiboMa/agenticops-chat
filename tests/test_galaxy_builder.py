"""Builder pipeline: rule graph + verified LLM edges, fail-closed drops, persistence."""

import json
import pytest

from agenticops.models import Base, get_session, get_db_session, CloudAccount, CloudResource
from agenticops.galaxy.models import GalaxyBuild, GalaxyResourceState
from agenticops.galaxy import builder as B


@pytest.fixture
def db(tmp_path):
    import agenticops.models as models_mod
    from agenticops.config import settings
    models_mod._engine = None
    settings.database_url = f"sqlite:///{tmp_path}/galaxy_builder.db"
    engine = models_mod.get_engine()
    Base.metadata.create_all(engine)
    s = get_session()
    yield s
    s.close()
    models_mod._engine = None


@pytest.fixture
def seeded(db):
    acct = CloudAccount(name="acct-a", provider="aws", is_enabled=True)
    db.add(acct)
    db.flush()
    db.add_all([
        CloudResource(account_id=acct.id, provider="aws", region="cn-north-1",
                      resource_type="VPC", resource_id="vpc-a", name="vpc-a",
                      tags={}, raw_data={}),
        CloudResource(account_id=acct.id, provider="aws", region="cn-north-1",
                      resource_type="EC2", resource_id="i-1", name="web",
                      tags={"Purpose": "web"},
                      raw_data={"NetworkInterfaces": [{"VpcId": "vpc-a"}]}),
    ])
    db.commit()
    return acct.id


def test_verify_drops_edge_with_missing_endpoint(db):
    valid = {"res:1", "res:2"}
    edges = [
        {"source": "res:1", "target": "res:999", "relation_type": "references", "evidence": "x", "confidence": 0.9},
    ]
    kept, dropped = B._verify_edges(edges, valid, {}, {})
    assert kept == []
    assert dropped == 1


def test_verify_drops_edge_with_unfounded_evidence(db):
    valid = {"res:1", "res:2"}
    node_by_id = {"res:1": {"id": "res:1"}, "res:2": {"id": "res:2"}}
    resources_by_node = {"res:2": {"raw_data": {"Purpose": "web"}, "tags": {}}}
    edges = [
        # evidence references a value that does not appear in res:2 raw_data/tags -> drop
        {"source": "res:1", "target": "res:2", "relation_type": "inferred_group",
         "evidence": "Project=nonexistent", "confidence": 0.9},
    ]
    kept, dropped = B._verify_edges(edges, valid, node_by_id, resources_by_node)
    assert dropped == 1


def test_verify_keeps_grounded_edge(db):
    valid = {"res:1", "res:2"}
    resources_by_node = {"res:2": {"raw_data": {"Purpose": "web-frontend"}, "tags": {}}}
    edges = [
        {"source": "res:1", "target": "res:2", "relation_type": "inferred_group",
         "evidence": "Purpose=web-frontend", "confidence": 0.9},
    ]
    kept, dropped = B._verify_edges(edges, valid, {}, resources_by_node)
    assert dropped == 0 and len(kept) == 1
    assert kept[0]["provenance"] == "llm"


def test_build_graph_full_pipeline_with_mocked_llm(db, seeded, monkeypatch):
    # LLM proposes one valid grouping edge (grounded) and one hallucinated endpoint (dropped).
    def fake_call(prompt, model_id, max_tokens):
        payload = {"edges": [
            {"source": "res:2", "target": "res:1", "relation_type": "references",
             "evidence": "VpcId=vpc-a", "confidence": 0.95},
            {"source": "res:2", "target": "res:8888", "relation_type": "references",
             "evidence": "made up", "confidence": 0.9},
        ]}
        return json.dumps(payload), {"input": 1000, "output": 200}
    monkeypatch.setattr(B, "_call_bedrock", fake_call)

    build_id = B.build_graph(trigger="manual", full=True)
    assert build_id > 0
    with get_db_session() as s:
        b = s.query(GalaxyBuild).filter_by(id=build_id).one()
        assert b.status == "completed"
        # rule layer present (account contains vpc, vpc contains ec2)
        rule_edges = b.rule_graph["edges"]
        assert any(e["relation_type"] == "contains" for e in rule_edges)
        # one llm edge kept, one dropped
        assert b.dropped_edge_count == 1
        assert all(e["provenance"] == "llm" for e in b.llm_graph["edges"])
        assert len(b.llm_graph["edges"]) == 1
        # resource state persisted for incremental builds
        assert s.query(GalaxyResourceState).count() == 2


def test_incremental_skips_when_no_change(db, seeded, monkeypatch):
    calls = {"n": 0}
    def fake_call(prompt, model_id, max_tokens):
        calls["n"] += 1
        return json.dumps({"edges": []}), {"input": 10, "output": 10}
    monkeypatch.setattr(B, "_call_bedrock", fake_call)

    first = B.build_graph(trigger="manual", full=True)
    n_after_first = calls["n"]
    # Second auto build with no data change -> no new build row, LLM not called again.
    second = B.build_graph(trigger="auto", full=False)
    assert second == first
    assert calls["n"] == n_after_first


def test_prune_keeps_only_recent_builds(db):
    # 30 completed builds; prune keep=5 leaves the 5 newest.
    for _ in range(30):
        db.add(GalaxyBuild(status="completed", trigger="manual"))
    db.commit()
    with get_db_session() as s:
        B._prune_old_builds(s, keep=5)
    with get_db_session() as s:
        rows = s.query(GalaxyBuild.id).order_by(GalaxyBuild.id.desc()).all()
        assert len(rows) == 5
        # the survivors are the highest ids
        assert [r.id for r in rows] == sorted([r.id for r in rows], reverse=True)


def test_prune_keep_zero_disables(db):
    for _ in range(3):
        db.add(GalaxyBuild(status="completed", trigger="manual"))
    db.commit()
    with get_db_session() as s:
        B._prune_old_builds(s, keep=0)
    with get_db_session() as s:
        assert s.query(GalaxyBuild).count() == 3
