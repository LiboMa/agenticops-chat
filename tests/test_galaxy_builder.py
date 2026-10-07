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


def test_evidence_grounding_prose_tolerant_but_failclosed():
    # Natural-language evidence citing a REAL term ('payments') grounds...
    res = {"raw_data": {"Purpose": "payments"}, "tags": {"Project": "payments"}}
    assert B._evidence_grounded("name shares prefix payments", [res]) is True
    # ...but a fabricated term or pure stopwords do NOT (fail-closed preserved).
    assert B._evidence_grounded("these belong to billing", [res]) is False
    assert B._evidence_grounded("shares prefix with same", [res]) is False
    assert B._evidence_grounded("Project=nonexistent", [res]) is False


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


# ── MVP-2.6.1: K8s rows in the build (spec §3.A.3 ③⑥) ──


def _k8s_row(account_id, kind, name, namespace=None, **raw):
    from agenticops.galaxy.rules import K8S_KIND_TYPES, k8s_resource_id

    body = {"cluster": "shop-eks", "namespace": namespace, "labels": {}}
    body.update(raw)
    return CloudResource(account_id=account_id, provider="kubernetes", region="us-east-1",
                         resource_type=K8S_KIND_TYPES[kind], name=name, tags={}, raw_data=body,
                         resource_id=k8s_resource_id("shop-eks", kind, name, namespace))


def test_k8s_rows_are_rule_derived_and_never_reach_the_llm(db, seeded, monkeypatch):
    ns = _k8s_row(seeded, "Namespace", "shop")
    dep = _k8s_row(seeded, "Deployment", "checkout", "shop", template_labels={"app": "checkout"})
    db.add_all([ns, dep])
    db.commit()
    ns_id, dep_id = ns.id, dep.id
    prompts = []

    def fake_call(prompt, model_id, max_tokens):
        prompts.append(prompt)
        # Grounded ("checkout" is in the Deployment's raw_data), yet it must be dropped: K8s is rule-only.
        return json.dumps({"edges": [{"source": "res:2", "target": f"res:{dep_id}", "relation_type": "references",
                                      "evidence": "app=checkout", "confidence": 0.9}]}), {"input": 1, "output": 1}

    monkeypatch.setattr(B, "_call_bedrock", fake_call)
    bid = B.build_graph(trigger="manual", full=True)
    with get_db_session() as s:
        b = s.query(GalaxyBuild).filter_by(id=bid).one()
        assert b.status == "completed"
        assert any((e["source"], e["target"], e["relation_type"]) == (f"res:{ns_id}", f"res:{dep_id}", "contains")
                   for e in b.rule_graph["edges"])
        assert b.llm_graph["edges"] == [] and b.dropped_edge_count == 1
    assert prompts and not any("K8s_" in p or "shop-eks" in p for p in prompts)


def test_build_passes_type_families_so_eks_duplicate_rows_are_one_cluster(db, seeded, monkeypatch):
    db.add_all([
        CloudResource(account_id=seeded, provider="aws", region="us-east-1", resource_type="EKS",
                      resource_id="shop-eks", name="shop-eks", tags={}, raw_data={}),
        CloudResource(account_id=seeded, provider="aws", region="us-east-1", resource_type="EKS_Cluster",
                      resource_id="arn:aws:eks:us-east-1:111122223333:cluster/shop-eks", name="shop-eks",
                      tags={}, raw_data={}),
    ])
    ns = _k8s_row(seeded, "Namespace", "shop")
    db.add(ns)
    db.commit()
    ns_id = ns.id
    monkeypatch.setattr(B, "_call_bedrock", lambda p, m, t: (json.dumps({"edges": []}), {"input": 1, "output": 1}))
    bid = B.build_graph(trigger="manual", full=True)
    with get_db_session() as s:
        edges = s.query(GalaxyBuild).filter_by(id=bid).one().rule_graph["edges"]
    parents = [e["source"] for e in edges if e["target"] == f"res:{ns_id}" and e["relation_type"] == "contains"]
    assert len(parents) == 1 and parents[0].startswith("res:")


def test_unresolved_refs_are_written_back_only_when_they_change(db, seeded):
    from agenticops.galaxy import rules

    dep = _k8s_row(seeded, "Deployment", "checkout", "shop", refs={"configmap": ["app-config"]})
    db.add(dep)
    db.commit()
    dep_id = dep.id

    def write_back():
        with get_db_session() as s:
            resources = B._load_resources(s)
        graph = rules.derive_rule_graph(resources)
        with get_db_session() as s:
            return B._write_unresolved_refs(s, resources, graph["unresolved_refs"])

    assert write_back() == 1
    with get_db_session() as s:
        raw = s.get(CloudResource, dep_id).raw_data
    assert raw["unresolved_refs"] == [{"kind": "ConfigMap", "name": "app-config"}]
    assert raw["refs"] == {"configmap": ["app-config"]}          # the rest of raw_data is untouched
    assert write_back() == 0                                       # unchanged → no write
    with get_db_session() as s:
        s.add(_k8s_row(seeded, "ConfigMap", "app-config", "shop", keys=["LOG_LEVEL"], data_sha256="ab"))
    assert write_back() == 1
    with get_db_session() as s:
        assert s.get(CloudResource, dep_id).raw_data["unresolved_refs"] == []


def test_load_resources_carries_scan_and_absence_times(db, seeded):
    from datetime import datetime

    row = db.query(CloudResource).filter_by(resource_id="i-1").one()
    row.scanned_at, row.absent_since = datetime(2026, 9, 27, 8), datetime(2026, 9, 28, 8)
    db.commit()
    got = next(r for r in B._load_resources(db) if r["resource_id"] == "i-1")
    assert (got["scanned_at"], got["absent_since"]) == (datetime(2026, 9, 27, 8), datetime(2026, 9, 28, 8))
