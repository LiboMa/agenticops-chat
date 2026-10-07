"""GraphQueryService (MVP-2.6.1 Plan A Task 8): bounded reads over published relations + live health."""
import json
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import event

from agenticops.config import settings
from agenticops.galaxy.models import GalaxyBuild, ResourceRelation
from agenticops.graph import query_service as qs
from agenticops.models import AlertEvent, Base, CloudAccount, CloudResource, HealthIssue, get_session

NOW = datetime.now(timezone.utc)


@pytest.fixture
def db(tmp_path):
    import agenticops.models as models_mod
    models_mod._engine = None
    settings.database_url = f"sqlite:///{tmp_path}/graph_query.db"
    engine = models_mod.get_engine()
    Base.metadata.create_all(engine)
    qs.clear_cache()
    s = get_session()
    yield s
    s.close()
    qs.clear_cache()
    models_mod._engine = None


def _res(s, rid, acct, rtype, resource_id, **kw):
    s.add(CloudResource(id=rid, account_id=acct, provider="aws", region="us-east-1", resource_type=rtype,
                        resource_id=resource_id, name=resource_id, tags={}, raw_data=kw.pop("raw_data", {}),
                        **kw))


def _rel(s, src, dst, rtype, *, build=1, acct=1, prov="rule", evidence="x"):
    s.add(ResourceRelation(build_id=build, account_id=acct, src_ref=src, dst_ref=dst, relation_type=rtype,
                           provenance=prov, evidence={"text": evidence}))


def _issue(s, ref, severity="high", status="open", acct=1, **kw):
    issue = HealthIssue(resource_id=f"r-{ref}", resource_ref=ref, account_id=acct, severity=severity,
                        status=status, source="test", title="t", description="d", **kw)
    s.add(issue)
    s.flush()
    return issue.id


@pytest.fixture
def seed(db):
    """acct-a: VPC(1) ⊃ Subnet(2) ⊃ EC2(3); EC2 secured_by SG(4); ELB(5) routes_to EC2; RDS(6) secured_by SG;
    llm EC2 references RDS. acct-b: EC2(7). Relation ids 1..6 follow insertion order."""
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
    _rel(db, 3, 6, "references", prov="llm", evidence="DB_HOST=db-1")
    db.commit()
    return db


@contextmanager
def _count_sql():
    import agenticops.models as models_mod
    counter = {"n": 0}

    def _on(*_args, **_kwargs):
        counter["n"] += 1

    engine = models_mod.get_engine()
    event.listen(engine, "before_cursor_execute", _on)
    try:
        yield counter
    finally:
        event.remove(engine, "before_cursor_execute", _on)


def _refs(sub):
    return {n["ref"] for n in sub.nodes}


def _node(sub, ref):
    return next(n for n in sub.nodes if n["ref"] == ref)


def _labels(sub):
    return {(e["src"], e["dst"]): e["direction_label"] for e in sub.edges}


# ── traversal & direction ────────────────────────────────────────────


def test_one_hop_both_directions_labels_edges(seed):
    sub = qs.neighborhood(3, session=seed)
    assert sub.build_id == 1 and not sub.truncated
    assert _refs(sub) == {3, 2, 4, 5}
    assert _labels(sub) == {(2, 3): "upstream", (3, 4): "upstream", (5, 3): "downstream"}
    assert all(e["provenance"] == "rule" for e in sub.edges)
    assert _node(sub, 3)["hops"] == 0 and _node(sub, 2)["hops"] == 1


def test_up_walks_dependencies_only(seed):
    assert _refs(qs.neighborhood(3, depth=2, direction="up", session=seed)) == {1, 2, 3, 4}


def test_down_walks_dependents_only(seed):
    assert _refs(qs.neighborhood(4, depth=2, direction="down", session=seed)) == {4, 3, 6, 5}


def test_include_llm_adds_display_edge_without_direction(seed):
    sub = qs.neighborhood(3, include_llm=True, session=seed)
    assert 6 in _refs(sub)
    llm = next(e for e in sub.edges if e["provenance"] == "llm")
    assert (llm["src"], llm["dst"], llm["direction_label"]) == (3, 6, "none")
    assert llm["evidence"] == "DB_HOST=db-1"


def test_relation_type_filter(seed):
    assert _refs(qs.neighborhood(3, depth=2, relation_types=["contains"], session=seed)) == {3, 2, 1}


def test_same_account_only(seed):
    _rel(seed, 3, 1, "attached_to", acct=2)       # a row filed under another account
    seed.commit()
    assert _refs(qs.neighborhood(3, session=seed)) == {3, 2, 4, 5}
    qs.clear_cache()
    _rel(seed, 3, 7, "attached_to", acct=1)       # filed under acct-a, but ref 7 belongs to acct-b
    seed.commit()
    sub = qs.neighborhood(3, session=seed)
    assert 7 not in _refs(sub)
    assert all(7 not in (e["src"], e["dst"]) for e in sub.edges)


# ── SQL budget & cache ───────────────────────────────────────────────


def test_sql_budget_and_topology_cache(seed):
    with _count_sql() as c:
        qs.neighborhood(3, depth=2, session=seed)
    assert c["n"] == 4                            # build + 2 hops + nodes/health
    with _count_sql() as c:
        qs.neighborhood(3, depth=2, session=seed)
    assert c["n"] == 2                            # build + nodes/health
    with _count_sql() as c:
        qs.neighborhood(3, depth=1, session=seed)
    assert c["n"] == 3                            # a different depth is a different key
    qs.clear_cache()
    with _count_sql() as c:
        qs.neighborhood(3, depth=2, session=seed)
    assert c["n"] == 4


def test_new_published_build_misses_cache(seed):
    assert _refs(qs.neighborhood(3, session=seed)) == {3, 2, 4, 5}
    seed.add(GalaxyBuild(id=2, status="completed", trigger="manual",
                         rules_published_at=NOW + timedelta(minutes=1)))
    seed.flush()
    _rel(seed, 3, 4, "secured_by", build=2)
    seed.commit()
    sub = qs.neighborhood(3, session=seed)
    assert sub.build_id == 2 and _refs(sub) == {3, 4}


def test_health_is_live_on_cache_hit(seed):
    assert _node(qs.neighborhood(3, session=seed), 4)["health"] == "unknown"
    _issue(seed, 4, severity="critical")
    seed.commit()
    with _count_sql() as c:
        sub = qs.neighborhood(3, session=seed)
    assert c["n"] == 2
    assert _node(sub, 4)["health"] == "critical" and _node(sub, 4)["anomalous"] is True


def test_default_session_scope(seed):
    assert _refs(qs.neighborhood(3)) == {3, 2, 4, 5}


# ── health overlay ───────────────────────────────────────────────────


def test_overlay_ignores_ref_reused_by_another_account(seed):
    _issue(seed, 7, severity="critical", acct=1)  # stale ref: id 7 now belongs to acct-b
    seed.commit()
    assert qs.health_overlay(seed) == {}
    assert _node(qs.neighborhood(7, session=seed), 7)["health"] == "unknown"


def test_closed_issues_do_not_colour(seed):
    _issue(seed, 3, severity="critical", status="dismissed")
    _issue(seed, 3, severity="critical", status="resolved")
    seed.commit()
    assert qs.health_overlay(seed) == {}
    node = _node(qs.neighborhood(3, session=seed), 3)
    assert (node["health"], node["issue_ids"], node["anomalous"]) == ("unknown", [], False)


def test_severity_mapping(seed):
    _issue(seed, 3, severity="high")
    _issue(seed, 4, severity="medium")
    _issue(seed, 5, severity="low")
    _issue(seed, 2, severity="info")
    seed.commit()
    got = {ref: v["health"] for ref, v in qs.health_overlay(seed).items()}
    assert got == {3: "warning", 4: "notice", 5: "notice", 2: "notice"}
    assert set(qs.health_overlay(seed, refs=[3, 4])) == {3, 4}


def test_worst_severity_wins_and_earliest_signal(seed):
    early = (NOW - timedelta(minutes=20)).replace(tzinfo=None)
    late = (NOW - timedelta(minutes=10)).replace(tzinfo=None)
    a = _issue(seed, 3, severity="low", observed_at=late)
    b = _issue(seed, 3, severity="critical", first_seen=early)
    seed.commit()
    got = qs.health_overlay(seed)[3]
    assert got["health"] == "critical"
    assert got["issue_ids"] == sorted([a, b])
    assert got["signal_at"] == early


# ── truncation ───────────────────────────────────────────────────────


@pytest.fixture
def star(db):
    """VPC 10 ⊃ Subnets 11..40; Subnet 40 ⊃ EC2 50 (open high issue); VPC 10 ⊃ Deployment 60 (waiting pods)."""
    db.add(CloudAccount(id=1, name="acct-a", provider="aws", credentials={}))
    _res(db, 10, 1, "VPC", "vpc-10")
    for rid in range(11, 41):
        _res(db, rid, 1, "Subnet", f"subnet-{rid}")
    _res(db, 50, 1, "EC2", "i-50")
    _res(db, 60, 1, "K8s_Deployment", "deploy-60",
         raw_data={"pod_summary": {"ready": 0, "desired": 2, "waiting_reasons": ["ImagePullBackOff"]}})
    db.add(GalaxyBuild(id=1, status="completed", trigger="manual", rules_published_at=NOW))
    db.flush()
    for rid in range(11, 41):
        _rel(db, 10, rid, "contains")
    _rel(db, 40, 50, "contains")
    _rel(db, 10, 60, "contains")
    _issue(db, 50, severity="high")
    db.commit()
    return db


def test_node_cap_keeps_anomalous_nodes_and_their_path(star):
    sub = qs.neighborhood(10, depth=2, node_cap=5, session=star)
    assert _refs(sub) == {10, 11, 40, 50, 60}
    assert (sub.truncated, sub.truncated_reason) == (True, "node_cap")
    assert _labels(sub)[(40, 50)] == "downstream"
    again = qs.neighborhood(10, depth=2, node_cap=5, session=star)
    assert again.to_dict() == sub.to_dict()


def test_edge_cap_keeps_tree_edges_and_all_nodes(seed):
    sub = qs.neighborhood(3, edge_cap=2, session=seed)
    assert [(e["src"], e["dst"]) for e in sub.edges] == [(2, 3), (3, 4)]
    assert (sub.truncated, sub.truncated_reason) == (True, "edge_cap")
    assert 5 in _refs(sub)


def test_expansion_cap_bounds_discovery(star, monkeypatch):
    monkeypatch.setattr(qs, "_EXPANSION_CAP", 3)
    sub = qs.neighborhood(10, depth=2, session=star)
    assert _refs(sub) == {10, 11, 12}
    assert (sub.truncated, sub.truncated_reason) == (True, "expansion_cap")


# ── impact ───────────────────────────────────────────────────────────


def test_potential_impact_is_downstream_rule_only_and_uncapped(seed, monkeypatch):
    monkeypatch.setattr(settings, "graph_query_node_cap", 2)
    sub = qs.potential_impact(4, session=seed)
    assert _refs(sub) == {4, 3, 6, 5} and not sub.truncated
    assert all(e["provenance"] == "rule" for e in sub.edges)


def _alert(s, resource_id, account, at, issue_id=None, disposition="noise"):
    s.add(AlertEvent(source="test", external_id=f"{resource_id}-{at.isoformat()}", severity="high", title="t",
                     resource_id=resource_id, account_id=account, received_at=at, health_issue_id=issue_id,
                     disposition=disposition))


def test_observed_impact_keeps_nodes_with_own_signal_or_open_issue(seed):
    _alert(seed, "alb", "acct-a", NOW - timedelta(minutes=5))        # noise signal on ELB 5 → counts
    _issue(seed, 6, severity="medium")                                # open issue on RDS 6 → counts
    _alert(seed, "i-1", "acct-a", NOW - timedelta(hours=2))           # EC2 3: outside the window
    _alert(seed, "i-1", "acct-b", NOW - timedelta(minutes=5))         # EC2 3: another account's i-1
    seed.commit()
    sub = qs.observed_impact(4, window=(NOW - timedelta(minutes=30), NOW + timedelta(minutes=10)),
                             session=seed)
    assert _refs(sub) == {4, 5, 6}
    assert [(e["src"], e["dst"]) for e in sub.edges] == [(6, 4)]


def test_observed_impact_counts_linked_signal_of_closed_issue(seed):
    iid = _issue(seed, 3, severity="high", status="resolved")
    _alert(seed, "something-else", "acct-a", NOW - timedelta(minutes=5), issue_id=iid, disposition="merged")
    seed.commit()
    sub = qs.observed_impact(4, window=(NOW - timedelta(minutes=30), NOW), session=seed)
    assert 3 in _refs(sub)


# ── edge cases ───────────────────────────────────────────────────────


def test_no_published_build(db):
    db.add(GalaxyBuild(id=1, status="completed", trigger="manual"))   # never published
    db.commit()
    sub = qs.neighborhood(1, session=db)
    assert (sub.build_id, sub.nodes, sub.edges) == (None, [], [])


def test_missing_start_resource(seed):
    sub = qs.neighborhood(999, session=seed)
    assert (sub.build_id, sub.nodes, sub.edges) == (1, [], [])


def test_rank_key_order():
    naive = (NOW - timedelta(minutes=10)).replace(tzinfo=None)
    nodes = {
        "a": {"ref": 1, "anomalous": True, "signal_at": NOW - timedelta(minutes=5), "hops": 1},
        "b": {"ref": 2, "anomalous": True, "signal_at": naive, "hops": 2},
        "c": {"ref": 3, "anomalous": True, "signal_at": None, "hops": 1},
        "d": {"ref": 4, "anomalous": False, "signal_at": None, "hops": 1},
        "e": {"ref": 5, "anomalous": False, "signal_at": None, "hops": 3},
    }
    order = sorted(nodes, key=lambda k: qs.rank_key(nodes[k], frozenset({5})))
    assert order == ["b", "a", "c", "e", "d"]


def test_absent_node_is_marked(seed):
    seed.get(CloudResource, 4).absent_since = NOW
    seed.commit()
    sub = qs.neighborhood(3, session=seed)
    assert _node(sub, 4)["absent"] is True and _node(sub, 2)["absent"] is False


@pytest.mark.parametrize("kwargs", [{"depth": 0}, {"direction": "sideways"}, {"node_cap": 0}, {"edge_cap": 0}])
def test_bad_arguments(seed, kwargs):
    with pytest.raises(ValueError):
        qs.neighborhood(3, session=seed, **kwargs)


def test_observed_impact_rejects_inverted_window(seed):
    with pytest.raises(ValueError):
        qs.observed_impact(4, window=(NOW, NOW - timedelta(minutes=1)), session=seed)


def test_to_dict_is_json_serialisable(seed):
    _issue(seed, 3, severity="high")
    seed.commit()
    data = qs.neighborhood(3, session=seed).to_dict()
    json.dumps(data)
    assert isinstance(_node(qs.neighborhood(3, session=seed), 3)["signal_at"], datetime)
    assert isinstance(next(n for n in data["nodes"] if n["ref"] == 3)["signal_at"], str)
