"""get_topology_evidence (MVP-2.6.1 Plan C Task 2): the RCA's graph evidence package around an issue's anchor."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from agenticops.config import settings
from agenticops.connectors.runner import ConnectorRunResult, TargetRun
from agenticops.galaxy.models import GalaxyBuild, ResourceRelation
from agenticops.graph import evidence as ev
from agenticops.graph import query_service as qs
from agenticops.models import (Base, ChangeRequest, CloudAccount, CloudResource, ConnectorRun, FixExecution, FixPlan,
                               HealthIssue, RCAResult, get_session)

NOW = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0) - timedelta(seconds=5)
CLUSTER_ARN = "arn:aws:eks:us-east-1:111111111111:cluster/prod"


@pytest.fixture
def db(tmp_path):
    import agenticops.models as models_mod
    models_mod._engine = None
    settings.database_url = f"sqlite:///{tmp_path}/evidence.db"
    engine = models_mod.get_engine()
    Base.metadata.create_all(engine)
    qs.clear_cache()
    s = get_session()
    yield s
    s.close()
    qs.clear_cache()
    models_mod._engine = None


def _res(s, rid, acct, rtype, resource_id, provider="aws", **kw):
    s.add(CloudResource(id=rid, account_id=acct, provider=provider, region="us-east-1", resource_type=rtype,
                        resource_id=resource_id, name=resource_id, tags={}, raw_data=kw.pop("raw_data", {}),
                        scanned_at=kw.pop("scanned_at", NOW - timedelta(minutes=1)), **kw))


def _rel(s, src, dst, rtype, *, acct=1):
    s.add(ResourceRelation(build_id=1, account_id=acct, src_ref=src, dst_ref=dst, relation_type=rtype,
                           provenance="rule", evidence={"text": f"{src}-{dst}"}))


def _issue(s, ref, severity="high", acct=1, issue_type="cpu_spike", **kw):
    kw.setdefault("anchor_status", "anchored" if ref else None)
    issue = HealthIssue(resource_id=f"r-{ref}", resource_ref=ref, account_id=acct, severity=severity, status="open",
                        source="test", title="t", description="d", issue_type=issue_type, **kw)
    s.add(issue)
    s.flush()
    return issue.id


@pytest.fixture
def seed(db):
    """acct-a: VPC(1) contains Subnet(2) contains EC2(3); EC2 secured_by SG(4); ELB(5) routes_to EC2;
    EKS cluster prod(10) contains Deployment web(11). acct-b: EC2(7). Issue #1 is on the EC2."""
    db.add_all([CloudAccount(id=1, name="acct-a", provider="aws", credentials={}),
                CloudAccount(id=2, name="acct-b", provider="aws", credentials={})])
    for rid, acct, rtype, name in [(1, 1, "VPC", "vpc-1"), (2, 1, "Subnet", "subnet-1"), (3, 1, "EC2", "i-1"),
                                   (4, 1, "SecurityGroup", "sg-1"), (5, 1, "ELB", "alb"), (7, 2, "EC2", "i-7"),
                                   (10, 1, "EKS", CLUSTER_ARN)]:
        _res(db, rid, acct, rtype, name)
    _res(db, 11, 1, "K8s_Deployment", "prod/default/Deployment/web", provider="kubernetes",
         raw_data={"cluster": "prod", "created_at": (NOW - timedelta(minutes=4)).isoformat() + "Z",
                   "pod_summary": {"ready": 1, "desired": 3, "waiting_reasons": ["ImagePullBackOff"]}})
    db.add(GalaxyBuild(id=1, status="completed", trigger="manual", rules_published_at=NOW))
    db.flush()
    _rel(db, 1, 2, "contains")
    _rel(db, 2, 3, "contains")
    _rel(db, 3, 4, "secured_by")
    _rel(db, 5, 3, "routes_to")
    _rel(db, 10, 11, "contains")
    _issue(db, 3, observed_at=NOW, first_seen=NOW - timedelta(minutes=5))
    db.commit()
    return db


def _run(db, at, status="complete", acct=1, scope="prod"):
    db.add(ConnectorRun(connector="k8s", account_id=acct, scope=scope, trigger="schedule", started_at=at,
                        finished_at=at, status=status, counts={}, per_kind={}))
    db.commit()


@pytest.fixture
def no_recollect(monkeypatch):
    def _boom(*args, **kwargs):
        raise AssertionError("no recollect expected")

    monkeypatch.setattr("agenticops.connectors.runner.run_connector", _boom)


# ── unavailable ───────────────────────────────────────────────────────


def test_missing_issue(seed):
    out = ev.build_evidence(999)
    assert out == {"available": False, "reason": "issue_not_found", "detail": "issue #999 does not exist"}


@pytest.mark.parametrize("status", ["unanchored", "account_level"])
def test_not_anchored_is_never_no_problem_found(seed, status):
    iid = _issue(seed, None, anchor_status=status)
    seed.commit()
    out = ev.build_evidence(iid)
    assert (out["available"], out["reason"], out["anchor_status"]) == (False, status, status)
    assert "not 'no problem found'" in out["detail"]


def test_legacy_issue_without_anchor_status_counts_as_unanchored(seed):
    iid = _issue(seed, None, anchor_status=None)
    seed.commit()
    assert ev.build_evidence(iid)["reason"] == "unanchored"


def test_ambiguous_lists_the_candidates(seed):
    audit = {"rule": "name", "candidates": [{"ref": 3, "account_id": 1, "reason": "name"},
                                            {"ref": 5, "account_id": 1, "reason": "name"}]}
    iid = _issue(seed, None, anchor_status="ambiguous", anchor_candidates=audit)
    seed.commit()
    out = ev.build_evidence(iid)
    assert (out["available"], out["reason"]) == (False, "ambiguous")
    assert [c["ref"] for c in out["anchor_candidates"]] == [3, 5]
    assert "not 'no problem found'" in out["detail"]


@pytest.mark.parametrize("ref,acct", [(999, 1), (3, 2)])
def test_gone_or_foreign_anchor_row_is_stale_ref(seed, ref, acct):
    iid = _issue(seed, ref, acct=acct)
    seed.commit()
    assert ev.build_evidence(iid)["reason"] == "stale_ref"


def test_no_published_build(seed, no_recollect):
    seed.query(GalaxyBuild).update({"rules_published_at": None})
    seed.commit()
    out = ev.build_evidence(1)
    assert (out["available"], out["reason"]) == (False, "no_published_build")
    assert out["anchor"]["ref"] == 3 and out["freshness"]["status"] == "fresh"


# ── the package ───────────────────────────────────────────────────────


def test_edges_carry_direction_and_evidence_refs(seed, no_recollect):
    out = ev.build_evidence(1)
    assert out["available"] and out["build_id"] == 1 and out["depth"] == 1
    assert out["anchor"] == {"ref": 3, "type": "EC2", "name": "i-1", "anchor_status": "anchored",
                             "evidence_ref": "graph:node:3", "health": "warning", "issue_ids": [1], "changes": [],
                             "absent": False}
    edges = {e["evidence_ref"]: (e["direction_label"], e["src_name"], e["dst_name"]) for e in out["edges"]}
    assert edges == {"graph:edge:2>3:contains": ("upstream", "subnet-1", "i-1"),
                     "graph:edge:3>4:secured_by": ("upstream", "i-1", "sg-1"),
                     "graph:edge:5>3:routes_to": ("downstream", "alb", "i-1")}
    assert sorted(n["ref"] for n in out["neighbors"]) == [2, 4, 5]
    assert all(n["evidence_ref"] == f"graph:node:{n['ref']}" for n in out["neighbors"])
    assert out["truncated"] is False
    start = datetime.fromisoformat(out["window"]["start"])
    assert start == NOW - timedelta(minutes=settings.rca_topology_window_before_minutes)


def test_candidates_rank_anomalous_then_changed_then_earlier_signal(seed, no_recollect):
    _issue(seed, 4, severity="critical", first_seen=NOW - timedelta(minutes=20))
    seed.get(CloudResource, 5).content_changed_at = NOW - timedelta(minutes=3)
    seed.commit()
    out = ev.build_evidence(1)
    assert [(c["rank"], c["ref"]) for c in out["candidates"]] == [(1, 4), (2, 3), (3, 5)]
    sg, anchor, elb = out["candidates"]
    assert sg["reasons"] == ["open issue #2 (critical)",
                             f"first signal at {(NOW - timedelta(minutes=20)).isoformat()}", "1 hop(s) from the anchor"]
    assert anchor["reasons"][-1] == "the anchor itself"
    assert elb["reasons"] == [f"content_changed at {(NOW - timedelta(minutes=3)).isoformat()}",
                              "1 hop(s) from the anchor"]
    assert elb["evidence_ref"] == "graph:node:5"


def test_a_changed_anchor_outranks_an_unchanged_anomalous_neighbor(seed, no_recollect):
    _issue(seed, 4, severity="critical", first_seen=NOW - timedelta(minutes=20))
    seed.get(CloudResource, 3).content_changed_at = NOW - timedelta(minutes=2)
    seed.commit()
    assert [c["ref"] for c in ev.build_evidence(1)["candidates"]] == [3, 4]


def test_changes_inside_the_window_only(seed, no_recollect):
    seed.get(CloudResource, 5).content_changed_at = NOW - timedelta(minutes=3)
    seed.get(CloudResource, 4).absent_since = NOW - timedelta(minutes=1)
    seed.get(CloudResource, 2).content_changed_at = NOW - timedelta(hours=2)
    seed.commit()
    views = {n["ref"]: n["changes"] for n in ev.build_evidence(1)["neighbors"]}
    assert views[5] == [{"kind": "content_changed", "at": (NOW - timedelta(minutes=3)).isoformat()}]
    assert views[4] == [{"kind": "absent", "at": (NOW - timedelta(minutes=1)).isoformat()}]
    assert views[2] == []
    widened = {n["ref"]: n["changes"] for n in ev.build_evidence(1, window_minutes=180)["neighbors"]}
    assert widened[2] == [{"kind": "content_changed", "at": (NOW - timedelta(hours=2)).isoformat()}]


def _fix_plan(s, issue_id):
    rca = RCAResult(health_issue_id=issue_id, root_cause="x", confidence=0.9)
    s.add(rca)
    s.flush()
    plan = FixPlan(plan_kind="fix", health_issue_id=issue_id, rca_result_id=rca.id, risk_level="L1", title="p",
                   summary="s", status="executed")
    s.add(plan)
    s.flush()
    return plan.id


def _change_plan(s, acct, db_ids):
    cr = ChangeRequest(title="c", description="d", requested_by="user:a@b", account_id=acct, status="completed",
                       target_resources=[{"resource_id": f"r{i}", "resource_type": "ELB", "db_id": i,
                                          "region": "us-east-1", "evidence": "id"} for i in db_ids])
    s.add(cr)
    s.flush()
    plan = FixPlan(plan_kind="change", change_request_id=cr.id, risk_level="L1", title="p", summary="s",
                   status="executed")
    s.add(plan)
    s.flush()
    return plan.id


def _execution(s, plan_id, at, issue_id=None):
    e = FixExecution(fix_plan_id=plan_id, health_issue_id=issue_id, status="succeeded", started_at=at)
    s.add(e)
    s.flush()
    return e.id


def test_our_own_executions_are_changes(seed, no_recollect):
    fix = _fix_plan(seed, 1)
    e1 = _execution(seed, fix, NOW - timedelta(minutes=2), issue_id=1)
    _execution(seed, fix, NOW - timedelta(hours=3), issue_id=1)  # outside the window
    change = _change_plan(seed, 1, [5])
    e3 = _execution(seed, change, NOW - timedelta(minutes=1))
    foreign = _change_plan(seed, 2, [4])  # another account's request naming the same db id
    _execution(seed, foreign, NOW - timedelta(minutes=1))
    seed.commit()
    out = ev.build_evidence(1)
    assert out["anchor"]["changes"] == [{"kind": "execution", "at": (NOW - timedelta(minutes=2)).isoformat(),
                                         "detail": f"fix plan #{fix}, execution #{e1} (succeeded)"}]
    views = {n["ref"]: n["changes"] for n in out["neighbors"]}
    assert views[5] == [{"kind": "execution", "at": (NOW - timedelta(minutes=1)).isoformat(),
                         "detail": f"change plan #{change}, execution #{e3} (succeeded)"}]
    assert views[4] == []
    assert [c["ref"] for c in out["candidates"]] == [3, 5]


def test_container_anchor_defaults_to_two_hops_and_depth_is_clamped(seed, no_recollect, monkeypatch):
    iid = _issue(seed, 1, issue_type="connectivity", observed_at=NOW)
    seed.commit()
    out = ev.build_evidence(iid)
    assert out["depth"] == 2 and sorted(n["ref"] for n in out["neighbors"]) == [2, 3]
    assert ev.build_evidence(iid, depth=9)["depth"] == settings.graph_query_max_depth
    monkeypatch.setattr(settings, "graph_query_max_depth", 1)
    assert ev.build_evidence(iid)["depth"] == 1


def test_non_k8s_anchor_freshness_comes_from_its_scan(seed, no_recollect):
    assert ev.build_evidence(1)["freshness"] == {"status": "fresh", "reason": "",
                                                 "collected_at": (NOW - timedelta(minutes=1)).isoformat()}
    seed.get(CloudResource, 3).scanned_at = NOW - timedelta(hours=2)
    seed.commit()
    fresh = ev.build_evidence(1)["freshness"]
    assert fresh["status"] == "stale" and "the anchored resource last collected at" in fresh["reason"]


# ── K8s recollect ─────────────────────────────────────────────────────


@pytest.mark.parametrize("row,scope", [
    ({"provider": "kubernetes", "type": "K8s_Pod", "cluster": "prod", "resource_id": "x"}, "prod"),
    ({"provider": "aws", "type": "EKS", "cluster": None, "resource_id": CLUSTER_ARN}, "prod"),
    ({"provider": "aws", "type": "EKS_Cluster", "cluster": None, "resource_id": "prod"}, "prod"),
    ({"provider": "aws", "type": "EC2", "cluster": None, "resource_id": "i-1"}, None),
    ({"provider": "kubernetes", "type": "K8s_Pod", "cluster": None, "resource_id": "x"}, None),
])
def test_k8s_scope(row, scope):
    assert ev._k8s_scope(row) == scope


def _k8s_issue(s):
    iid = _issue(s, 11, issue_type="availability", observed_at=NOW)
    s.commit()
    return iid


def test_old_collection_triggers_a_bounded_recollect_and_a_rule_only_refresh(seed, monkeypatch):
    _run(seed, NOW - timedelta(hours=1))
    iid = _k8s_issue(seed)
    calls, builds = [], []

    def _fake_run(name, **kwargs):
        calls.append((name, kwargs))
        _run(seed, datetime.now(timezone.utc).replace(tzinfo=None), status="partial")  # the recollect writes
        return ConnectorRunResult(connector=name, status="partial", changed=True, targets=[
            TargetRun(account="acct-a", scope="prod", run_id=2, status="partial", changed=True, counts={},
                      error="secrets: forbidden")])

    monkeypatch.setattr("agenticops.connectors.runner.run_connector", _fake_run)
    monkeypatch.setattr("agenticops.galaxy.builder.build_graph", lambda **kw: builds.append(kw) or 1)
    monkeypatch.setattr(settings, "galaxy_enabled", True)
    out = ev.build_evidence(iid)
    assert calls == [("k8s", {"account": "acct-a", "scope": "prod", "trigger": "rca",
                              "timeout_seconds": settings.rca_k8s_recollect_timeout_seconds})]
    assert builds == [{"trigger": "rca-recollect", "full": False, "llm": False}]
    assert out["freshness"]["status"] == "fresh"
    assert out["freshness"]["reason"] == "recollect of cluster prod was partial — secrets: forbidden"
    anchor = out["candidates"][0]
    assert anchor["ref"] == 11 and anchor["reasons"][:3] == [
        "open issue #2 (warning)", "pods waiting: ImagePullBackOff", "1/3 pods ready"]
    assert f"created at {(NOW - timedelta(minutes=4)).isoformat()}" in anchor["reasons"]


def test_unchanged_recollect_skips_the_graph_refresh(seed, monkeypatch):
    iid = _k8s_issue(seed)

    def _fake_run(name, **kwargs):
        _run(seed, datetime.now(timezone.utc).replace(tzinfo=None))
        return ConnectorRunResult(connector=name, status="complete", changed=False)

    monkeypatch.setattr("agenticops.connectors.runner.run_connector", _fake_run)
    monkeypatch.setattr("agenticops.galaxy.builder.build_graph",
                        lambda **kw: (_ for _ in ()).throw(AssertionError("no refresh expected")))
    monkeypatch.setattr(settings, "galaxy_enabled", True)
    fresh = ev.build_evidence(iid)["freshness"]
    assert (fresh["status"], fresh["reason"]) == ("fresh", "")


def test_recent_collection_is_not_recollected(seed, no_recollect):
    _run(seed, datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=30))
    out = ev.build_evidence(_k8s_issue(seed))
    assert out["available"] and out["freshness"]["status"] == "fresh"


def test_failed_recollect_marks_the_evidence_stale_and_goes_on(seed, monkeypatch):
    _run(seed, NOW - timedelta(hours=1))
    iid = _k8s_issue(seed)

    def _boom(name, **kwargs):
        raise RuntimeError("kubectl timed out")

    monkeypatch.setattr("agenticops.connectors.runner.run_connector", _boom)
    out = ev.build_evidence(iid)
    assert out["available"] and out["candidates"][0]["ref"] == 11
    assert out["freshness"]["status"] == "stale"
    assert out["freshness"]["reason"].startswith(
        "recollect of cluster prod failed — RuntimeError: kubectl timed out; cluster prod last collected at ")


@pytest.mark.parametrize("result,reason", [
    (RuntimeError("kubectl timed out"), "recollect of cluster prod failed — RuntimeError: kubectl timed out"),
    (ConnectorRunResult(connector="k8s", status="busy"), "recollect of cluster prod was busy"),
    (ConnectorRunResult(connector="k8s", status="failed", targets=[
        TargetRun(account="acct-a", scope="prod", run_id=2, status="failed", changed=False, counts={},
                  error="no kubeconfig")]), "recollect of cluster prod was failed — no kubeconfig"),
    (ConnectorRunResult(connector="k8s", status="complete", changed=True),
     "graph refresh after the recollect failed — build locked"),
], ids=["raises", "busy", "failed", "refresh-fails"])
def test_a_failed_recollect_is_stale_even_with_a_recent_prior_run(seed, monkeypatch, result, reason):
    prior = NOW - timedelta(minutes=5)  # inside the window, older than the min age
    _run(seed, prior)
    iid = _k8s_issue(seed)

    def _fake_run(name, **kwargs):
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr("agenticops.connectors.runner.run_connector", _fake_run)
    monkeypatch.setattr("agenticops.galaxy.builder.build_graph",
                        lambda **kw: (_ for _ in ()).throw(RuntimeError("build locked")))
    monkeypatch.setattr(settings, "galaxy_enabled", True)
    assert ev.build_evidence(iid)["freshness"] == {"status": "stale", "reason": reason,
                                                    "collected_at": prior.isoformat()}


def test_never_collected_cluster_with_a_failed_recollect(seed, monkeypatch):
    iid = _k8s_issue(seed)
    monkeypatch.setattr("agenticops.connectors.runner.run_connector",
                        lambda name, **kw: ConnectorRunResult(connector=name, status="failed", targets=[
                            TargetRun(account="acct-a", scope="prod", run_id=1, status="failed", changed=False,
                                      counts={}, error="no kubeconfig")]))
    fresh = ev.build_evidence(iid)["freshness"]
    assert fresh == {"status": "stale", "collected_at": None,
                     "reason": "recollect of cluster prod was failed — no kubeconfig; cluster prod never collected"}


def test_anchor_without_an_account_row_is_never_recollected(seed, monkeypatch):
    _res(seed, 20, 3, "K8s_Pod", "prod/default/Pod/orphan", provider="kubernetes", raw_data={"cluster": "prod"})
    seed.flush()
    iid = _issue(seed, 20, acct=3, issue_type="availability", observed_at=NOW)
    seed.commit()
    calls = []

    def _boom(name, **kwargs):
        calls.append(kwargs)
        raise AssertionError("no recollect expected")

    monkeypatch.setattr("agenticops.connectors.runner.run_connector", _boom)
    fresh = ev.build_evidence(iid)["freshness"]
    assert calls == []
    assert fresh == {"status": "stale", "collected_at": None,
                     "reason": "recollect of cluster prod skipped — the anchor row has no account; "
                               "cluster prod never collected"}


# ── the tool ──────────────────────────────────────────────────────────


def test_tool_returns_json(seed, no_recollect):
    out = json.loads(ev.get_topology_evidence._tool_func(issue_id=1))
    assert out["available"] and out["anchor"]["ref"] == 3


def test_tool_turns_an_exception_into_unavailable(monkeypatch):
    monkeypatch.setattr(ev, "build_evidence", lambda *a, **k: (_ for _ in ()).throw(ValueError("bad")))
    out = json.loads(ev.get_topology_evidence._tool_func(issue_id=1))
    assert out == {"available": False, "reason": "error", "detail": "ValueError: bad"}
