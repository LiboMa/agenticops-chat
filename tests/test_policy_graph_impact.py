"""Policy blast radius over the published graph, shadow mode by default (MVP-2.6.1 Plan C Task 6, spec §3.C.5)."""
import json
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from agenticops.config import settings
from agenticops.galaxy.models import GalaxyBuild, ResourceRelation
from agenticops.graph import query_service as qs
from agenticops.models import (Base, ChangeRequest, CloudAccount, CloudResource, FixPlan, HealthIssue,
                               PipelineEvent, RCAResult, get_session)
from agenticops.services import policy_engine as pe

NOW = datetime.now(timezone.utc)


@pytest.fixture
def db(tmp_path, monkeypatch):
    import agenticops.audit.models  # noqa: F401
    import agenticops.models as models_mod
    monkeypatch.setattr(models_mod, "_engine", None)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/policy_graph.db")
    Base.metadata.create_all(models_mod.get_engine())
    qs.clear_cache()
    s = get_session()
    yield s
    s.close()
    qs.clear_cache()
    models_mod._engine = None


def _res(s, rid, acct, rtype, name):
    s.add(CloudResource(id=rid, account_id=acct, provider="aws", region="us-east-1", resource_type=rtype,
                        resource_id=name, name=name, tags={}, raw_data={}))


def _rel(s, src, dst, rtype, *, acct=1, prov="rule"):
    s.add(ResourceRelation(build_id=1, account_id=acct, src_ref=src, dst_ref=dst, relation_type=rtype,
                           provenance=prov, evidence={"text": "x"}))


@pytest.fixture
def seed(db):
    """acct-a: VPC(1) ⊃ Subnet(2) ⊃ EC2(3); EC2 and RDS(6) secured_by SG(4); ELB(5) routes_to EC2;
    llm EC2 references RDS. acct-b: EC2(7). Downstream of SG 4: EC2 3, RDS 6, ELB 5."""
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


# ── the count ─────────────────────────────────────────────────────────


def test_counts_the_potential_impact_without_the_resource_itself(seed):
    assert pe.estimate_blast_radius(4, 1, session=seed) == 3
    assert pe.estimate_blast_radius(4, 1, session=seed) == len(qs.potential_impact(4, session=seed).nodes) - 1


def test_nothing_downstream_counts_zero(seed):
    assert pe.estimate_blast_radius(5, 1, session=seed) == 0


def test_opens_its_own_session_when_given_none(seed):
    assert pe.estimate_blast_radius(4, 1) == 3


@pytest.mark.parametrize("ref, account_id", [
    (None, 1), ("4", 1), (True, 1), (4, None),
    (4, 2),        # the ref belongs to another account
    (99, 1),       # no such inventory row
])
def test_unknown_is_none(seed, ref, account_id):
    assert pe.estimate_blast_radius(ref, account_id, session=seed) is None


def test_no_published_build_is_none(db):
    _res(db, 4, 1, "SecurityGroup", "sg-1")
    db.commit()
    assert pe.estimate_blast_radius(4, 1, session=db) is None


def test_an_error_is_none(seed):
    with patch.object(qs, "potential_impact", side_effect=RuntimeError("boom")):
        assert pe.estimate_blast_radius(4, 1, session=seed) is None


# ── shadow / enforce ──────────────────────────────────────────────────


def test_shadow_mode_records_the_count_and_feeds_none(seed, monkeypatch):
    monkeypatch.setattr(settings, "policy_graph_impact_enforce", False)
    assert pe.policy_blast_radius([4], 1, session=seed) == (None, 3)


def test_enforce_mode_feeds_the_count(seed, monkeypatch):
    monkeypatch.setattr(settings, "policy_graph_impact_enforce", True)
    assert pe.policy_blast_radius([4], 1, session=seed) == (3, None)


def test_the_widest_ref_wins_and_unknown_refs_are_skipped(seed, monkeypatch):
    monkeypatch.setattr(settings, "policy_graph_impact_enforce", True)
    assert pe.policy_blast_radius([5, None, 99, 4, 3], 1, session=seed) == (3, None)
    assert pe.policy_blast_radius([None, 99], 1, session=seed) == (None, None)
    assert pe.policy_blast_radius([], 1, session=seed) == (None, None)


def test_the_decision_carries_the_shadow_value():
    d = pe.PolicyDecision(action="auto_approve", rule_name="r", shadow_blast_radius=3)
    assert d.to_dict()["shadow_blast_radius"] == 3
    assert pe.PolicyDecision(action="auto_approve", rule_name="r").to_dict()["shadow_blast_radius"] is None


# ── the fix path ──────────────────────────────────────────────────────


def _fix_plan(s, ref):
    issue = HealthIssue(resource_id="sg-1", resource_ref=ref, anchor_status="anchored", account_id=1,
                        provider="aws", severity="medium", status="fix_planned", source="test", title="t",
                        description="d", issue_type="config")
    s.add(issue)
    s.flush()
    rca = RCAResult(health_issue_id=issue.id, root_cause="sg change", confidence=0.8)
    s.add(rca)
    s.flush()
    plan = FixPlan(health_issue_id=issue.id, rca_result_id=rca.id, risk_level="L1", title="p", summary="s",
                   steps=[], status="draft")
    s.add(plan)
    s.commit()
    return plan


def _evaluate_fix(s, plan):
    from agenticops.services import pipeline_service
    with patch.object(pe, "simulate_fix_impact", return_value=None):
        return pipeline_service._evaluate_policy_for_plan(s, plan)


def test_fix_path_shadow_mode_leaves_the_rule_asleep(seed, monkeypatch):
    monkeypatch.setattr(settings, "policy_graph_impact_enforce", False)
    d = _evaluate_fix(seed, _fix_plan(seed, 4))
    assert (d.action, d.rule_name, d.escalated_from) == ("auto_approve", "auto-approve-low-risk", None)
    assert d.to_dict()["shadow_blast_radius"] == 3


def test_fix_path_enforce_mode_wakes_blast_radius_escalation(seed, monkeypatch):
    monkeypatch.setattr(settings, "policy_graph_impact_enforce", True)
    d = _evaluate_fix(seed, _fix_plan(seed, 4))
    # The same plan auto-approves in shadow mode, so the flag alone woke the rule. (evaluate() keeps only the
    # final tier's reasons, so the escalation itself is visible as the tier move.)
    assert (d.action, d.escalated_from, d.effective_risk_level) == ("require_human", "L1", "L2")
    assert d.shadow_blast_radius is None


def test_fix_path_small_impact_stays_below_the_rule(seed, monkeypatch):
    monkeypatch.setattr(settings, "policy_graph_impact_enforce", True)
    d = _evaluate_fix(seed, _fix_plan(seed, 3))
    assert (d.action, d.escalated_from) == ("auto_approve", None)


# ── the change path ───────────────────────────────────────────────────


def _change(s, db_ids):
    cr = ChangeRequest(source="cli", requested_by="cli:test", title="t", description="d", account_id=1,
                       requested_change_type="normal", status="under_review",
                       target_resources=[{"resource_id": f"r-{i}", "db_id": i} for i in db_ids])
    s.add(cr)
    s.commit()
    return cr.id


def test_change_path_uses_the_widest_target(seed, monkeypatch):
    from agenticops.services import change_service as cs
    monkeypatch.setattr(settings, "policy_graph_impact_enforce", False)
    cr_id = _change(seed, [5, None, 4])     # the first target has nothing downstream; SG 4 has 3
    d = cs.evaluate_policy(cr_id, "L1", "tag")
    assert (d.action, d.shadow_blast_radius) == ("auto_approve", 3)
    event = seed.query(PipelineEvent).filter_by(change_request_id=cr_id, event_type="policy_decision").one()
    assert json.loads(event.detail)["policy_decision"]["shadow_blast_radius"] == 3


def test_change_path_enforce_mode_escalates(seed, monkeypatch):
    from agenticops.services import change_service as cs
    monkeypatch.setattr(settings, "policy_graph_impact_enforce", True)
    d = cs.evaluate_policy(_change(seed, [4]), "L1", "tag")
    # L1 tag would be change-standard-low-risk; one tier up it is change-normal-human.
    assert (d.action, d.rule_name, d.escalated_from) == ("require_human", "change-normal-human", "L1")
