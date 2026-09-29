"""Galaxy rule-layer publication (MVP-2.6.1 spec §3.A.3 ④⑤): resource_relations before the LLM phase,
rule-only refresh, prune keep-set, re-anchoring after builds."""

import json
from datetime import datetime, timedelta

import pytest

from agenticops.models import Base, get_session, get_db_session, CloudAccount, CloudResource, HealthIssue
from agenticops.galaxy.models import GalaxyBuild, GalaxyResourceState, ResourceRelation
from agenticops.galaxy import builder as B

# Grounded in the EC2's raw_data (NetworkInterfaces[].VpcId), so _verify_edges keeps it.
EDGE = {"source": "res:2", "target": "res:1", "relation_type": "references",
        "evidence": "VpcId=vpc-a", "confidence": 0.95}


@pytest.fixture
def db(tmp_path):
    import agenticops.models as models_mod
    from agenticops.config import settings
    models_mod._engine = None
    settings.database_url = f"sqlite:///{tmp_path}/galaxy_publish.db"
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
                      resource_type="VPC", resource_id="vpc-a", name="vpc-a", tags={}, raw_data={}),
        CloudResource(account_id=acct.id, provider="aws", region="cn-north-1",
                      resource_type="EC2", resource_id="i-1", name="web", tags={},
                      raw_data={"NetworkInterfaces": [{"VpcId": "vpc-a"}]}),
    ])
    db.commit()
    return acct.id


def _llm_returns(edges, calls=None):
    def fake(prompt, model_id, max_tokens):
        if calls is not None:
            calls.append(prompt)
        return json.dumps({"edges": edges}), {"input": 10, "output": 5}
    return fake


def _provenances(s, build_id):
    return {r.provenance for r in s.query(ResourceRelation).filter_by(build_id=build_id)}


def _state():
    with get_db_session() as s:
        return sorted((r.resource_pk, r.content_hash, r.last_analyzed_build_id)
                      for r in s.query(GalaxyResourceState))


def _triples(edges):
    return sorted((int(e["source"][4:]), int(e["target"][4:]), e["relation_type"]) for e in edges
                  if e["source"].startswith("res:") and e["target"].startswith("res:"))


# ── normal build: rules first ──


def test_rules_are_published_before_the_llm_runs(db, seeded, monkeypatch):
    seen = {}

    def fake(prompt, model_id, max_tokens):
        seen["lock_free"] = not B._RULE_LOCK.locked()
        with get_db_session() as s:
            b = s.query(GalaxyBuild).filter_by(status="running").one()
            seen["published"] = b.rules_published_at is not None
            seen["provenances"] = _provenances(s, b.id)
        return json.dumps({"edges": [EDGE]}), {"input": 10, "output": 5}

    monkeypatch.setattr(B, "_call_bedrock", fake)
    bid = B.build_graph(trigger="manual", full=True)
    assert seen == {"lock_free": True, "published": True, "provenances": {"rule"}}
    with get_db_session() as s:
        assert s.get(GalaxyBuild, bid).status == "completed"
        assert _provenances(s, bid) == {"rule", "llm"}


def test_relation_rows_conserve_the_build_json(db, seeded, monkeypatch):
    monkeypatch.setattr(B, "_call_bedrock", _llm_returns([EDGE]))
    bid = B.build_graph(trigger="manual", full=True)
    with get_db_session() as s:
        b = s.get(GalaxyBuild, bid)
        rows = s.query(ResourceRelation).filter_by(build_id=bid).all()
        rule_rows = sorted((r.src_ref, r.dst_ref, r.relation_type) for r in rows if r.provenance == "rule")
        llm_rows = sorted((r.src_ref, r.dst_ref, r.relation_type) for r in rows if r.provenance == "llm")
        assert rule_rows == _triples(b.rule_graph["edges"]) and rule_rows      # VPC contains EC2 at least
        assert llm_rows == _triples(b.llm_graph["edges"]) == [(2, 1, "references")]
        assert {r.account_id for r in rows} == {seeded}
        assert all(isinstance(r.evidence.get("text"), str) for r in rows)
        assert {r.confidence for r in rows if r.provenance == "rule"} == {1.0}


def test_cross_account_llm_edge_stays_in_the_build_json_only(db, seeded, monkeypatch):
    other = CloudAccount(name="acct-b", provider="aws", is_enabled=True)
    db.add(other)
    db.flush()
    far = CloudResource(account_id=other.id, provider="aws", region="cn-north-1", resource_type="RDS",
                        resource_id="db-9", name="db-9", tags={}, raw_data={})
    db.add(far)
    db.commit()
    far_node = f"res:{far.id}"
    cross = {"source": "res:2", "target": far_node, "relation_type": "references",
             "evidence": "VpcId=vpc-a", "confidence": 0.9}
    monkeypatch.setattr(B, "_call_bedrock", _llm_returns([EDGE, cross]))
    bid = B.build_graph(trigger="manual", full=True)
    with get_db_session() as s:
        assert {e["target"] for e in s.get(GalaxyBuild, bid).llm_graph["edges"]} == {"res:1", far_node}
        llm_rows = s.query(ResourceRelation).filter_by(build_id=bid, provenance="llm").all()
        assert [(r.src_ref, r.dst_ref) for r in llm_rows] == [(2, 1)]


def test_llm_failure_fails_the_build_but_keeps_its_rules_readable(db, seeded, monkeypatch):
    def boom(prompt, model_id, max_tokens):
        raise RuntimeError("bedrock down")

    monkeypatch.setattr(B, "_call_bedrock", boom)
    bid = B.build_graph(trigger="manual", full=True)
    with get_db_session() as s:
        b = s.get(GalaxyBuild, bid)
        assert b.status == "failed" and "bedrock down" in b.error
        assert b.rules_published_at is not None
        assert _provenances(s, bid) == {"rule"}
        assert B.latest_published_id(s) == bid
        assert s.query(GalaxyResourceState).count() == 0      # the diff baseline only moves on success


def test_upgrade_with_unchanged_inventory_still_publishes_relations(db, seeded, monkeypatch):
    calls = []
    monkeypatch.setattr(B, "_call_bedrock", _llm_returns([EDGE], calls))
    first = B.build_graph(trigger="manual", full=True)
    with get_db_session() as s:          # what a pre-2.6.1 build looks like: nothing published
        s.query(ResourceRelation).delete()
        s.get(GalaxyBuild, first).rules_published_at = None
    n_calls = len(calls)
    second = B.build_graph(trigger="auto", full=False)
    assert second != first
    assert len(calls) == n_calls         # inventory unchanged → nothing is re-sent to the LLM
    with get_db_session() as s:
        b = s.get(GalaxyBuild, second)
        assert b.status == "completed" and b.rules_published_at is not None
        assert _provenances(s, second) == {"rule", "llm"}       # the old LLM edge is carried and published
    assert B.build_graph(trigger="auto", full=False) == second  # published now → the skip applies again


# ── rule-only refresh ──


@pytest.mark.parametrize("trigger,llm", [("k8s-discovery", True), ("rca-recollect", True),
                                         ("manual", False), ("auto", False)])
def test_trigger_and_llm_flag_must_agree(db, trigger, llm):
    with pytest.raises(ValueError):
        B.build_graph(trigger=trigger, llm=llm)
    with get_db_session() as s:
        assert s.query(GalaxyBuild).count() == 0


def test_rule_only_refresh_during_llm_phase_keeps_llm_edges(db, seeded, monkeypatch):
    monkeypatch.setattr(B, "_call_bedrock", _llm_returns([EDGE]))
    first = B.build_graph(trigger="manual", full=True)
    with get_db_session() as s:
        first_llm = s.get(GalaxyBuild, first).llm_graph["edges"]
    assert len(first_llm) == 1
    seen = {}

    def llm_that_refreshes(prompt, model_id, max_tokens):
        assert not B._RULE_LOCK.locked(), "rule lock held during the LLM phase"
        seen["state_before"] = _state()
        seen["refresh"] = B.build_graph(trigger="k8s-discovery", llm=False)
        seen["state_after"] = _state()
        return json.dumps({"edges": [EDGE]}), {"input": 10, "output": 5}

    monkeypatch.setattr(B, "_call_bedrock", llm_that_refreshes)
    second = B.build_graph(trigger="manual", full=True)
    with get_db_session() as s:
        n = s.get(GalaxyBuild, second)
        assert n.status == "completed", n.error
        refresh = seen["refresh"]
        assert first < second < refresh
        r = s.get(GalaxyBuild, refresh)
        assert (r.status, r.trigger, r.input_tokens, r.output_tokens, r.cost_usd) == \
            ("completed", "k8s-discovery", 0, 0, 0.0)
        assert r.rules_published_at is not None
        assert r.llm_graph["edges"] == first_llm             # carried from the last completed LLM build
        assert _provenances(s, refresh) == {"rule", "llm"}
        assert _provenances(s, second) == {"rule", "llm"}    # the normal build still publishes both layers
        assert B.latest_published_id(s) == refresh           # it derived after the normal build's rule phase
        assert B._latest_llm_build(s).id == second
    assert seen["state_before"] == seen["state_after"]       # the refresh never touches the diff baseline


def test_refresh_is_not_blocked_by_another_process_running_build(db, seeded):
    with get_db_session() as s:
        s.add(GalaxyBuild(status="running", trigger="auto"))
    with get_db_session() as s:
        running = s.query(GalaxyBuild).filter_by(status="running").one().id
    assert B.build_graph(trigger="auto") == running           # a normal build still yields to it
    refresh = B.build_graph(trigger="k8s-discovery", llm=False)
    assert refresh != running
    with get_db_session() as s:
        assert s.get(GalaxyBuild, refresh).status == "completed"


def test_refresh_leaves_the_llm_diff_baseline_alone(db, seeded, monkeypatch):
    calls = []
    monkeypatch.setattr(B, "_call_bedrock", _llm_returns([EDGE], calls))
    first = B.build_graph(trigger="manual", full=True)
    before = _state()
    with get_db_session() as s:
        s.query(CloudResource).filter_by(resource_id="i-1").delete()
    refresh = B.build_graph(trigger="rca-recollect", llm=False)
    assert _state() == before
    with get_db_session() as s:
        assert s.get(GalaxyBuild, refresh).llm_graph["edges"] == []   # EDGE's source is gone
        assert "llm" not in _provenances(s, refresh)
    n_calls = len(calls)
    after = B.build_graph(trigger="auto", full=False)
    assert after not in (first, refresh)       # the removal is still visible to the next normal build
    with get_db_session() as s:
        assert s.get(GalaxyBuild, after).status == "completed"
        assert s.query(GalaxyResourceState).count() == 1
    assert len(calls) == n_calls               # a removal alone sends nothing to the LLM


# ── prune keep-set ──


def test_prune_keeps_running_llm_and_published_builds_with_their_relations(db):
    t = datetime(2026, 9, 28, 8)
    llm = GalaxyBuild(status="completed", trigger="manual", finished_at=t, rules_published_at=t)
    running = GalaxyBuild(status="running", trigger="manual", rules_published_at=t + timedelta(minutes=1))
    refreshes = [GalaxyBuild(status="completed", trigger="k8s-discovery",
                             finished_at=t + timedelta(minutes=2 + i), rules_published_at=t + timedelta(minutes=2 + i))
                 for i in range(3)]
    failed = [GalaxyBuild(status="failed", trigger="auto") for _ in range(3)]   # failed before publishing
    builds = [llm, running, *refreshes, *failed]
    db.add_all(builds)
    db.flush()
    for b in builds:
        db.add(ResourceRelation(build_id=b.id, account_id=1, src_ref=1, dst_ref=2, relation_type="contains"))
    kept = {llm.id, running.id, refreshes[-1].id, *(b.id for b in failed)}
    db.commit()
    with get_db_session() as s:
        B._prune_old_builds(s, keep=3)
    with get_db_session() as s:
        assert {b.id for b in s.query(GalaxyBuild)} == kept
        assert {r.build_id for r in s.query(ResourceRelation)} == kept


# ── re-anchoring hook ──


@pytest.mark.parametrize("trigger,llm", [("manual", True), ("rca-recollect", False)])
def test_completed_builds_reanchor_open_issues(db, seeded, monkeypatch, trigger, llm):
    monkeypatch.setattr(B, "_call_bedrock", _llm_returns([]))
    issue = HealthIssue(resource_id="i-2", severity="high", source="manual", title="api down",
                        description="d", status="open", anchor_status="unanchored")
    db.add(issue)
    db.commit()
    issue_id = issue.id
    api = CloudResource(account_id=seeded, provider="aws", region="cn-north-1", resource_type="EC2",
                        resource_id="i-2", name="api", tags={}, raw_data={})
    db.add(api)
    db.commit()
    api_id = api.id
    B.build_graph(trigger=trigger, llm=llm)
    with get_db_session() as s:
        got = s.get(HealthIssue, issue_id)
        assert (got.anchor_status, got.resource_ref, got.account_id) == ("anchored", api_id, seeded)


def test_reanchor_failure_never_fails_a_completed_build(db, seeded, monkeypatch):
    from agenticops.services import identity_resolver

    def broken(session):
        raise RuntimeError("resolver down")

    monkeypatch.setattr(B, "_call_bedrock", _llm_returns([]))
    monkeypatch.setattr(identity_resolver, "reanchor_open_issues", broken)
    bid = B.build_graph(trigger="manual", full=True)
    with get_db_session() as s:
        assert s.get(GalaxyBuild, bid).status == "completed"
