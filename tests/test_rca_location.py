"""save_rca_result(location=…) (MVP-2.6.1 Plan C Task 3): fail-closed validation of the root-cause location."""
import json
from datetime import datetime

import pytest

from agenticops.config import settings
from agenticops.galaxy.models import GalaxyBuild, ResourceRelation
from agenticops.graph import query_service as qs
from agenticops.models import Base, CloudAccount, CloudResource, HealthIssue, RCAResult, get_session
from agenticops.services import rca_location as rl
from agenticops.tools import metadata_tools

EVIDENCE = [{"type": "metric", "ref": "CPUUtilization", "summary": "92%"},
            {"type": "graph", "ref": "graph:edge:3>4:secured_by", "summary": "sg in front"}]


@pytest.fixture
def db(tmp_path):
    import agenticops.models as models_mod
    models_mod._engine = None
    settings.database_url = f"sqlite:///{tmp_path}/location.db"
    engine = models_mod.get_engine()
    Base.metadata.create_all(engine)
    qs.clear_cache()
    s = get_session()
    yield s
    s.close()
    qs.clear_cache()
    models_mod._engine = None


@pytest.fixture
def seed(db):
    """acct-a: Subnet(2) contains EC2(3); EC2 secured_by SG(4) (rule); ELB(5) routes_to EC2 (llm).
    acct-b: EC2(7), with a relation 7 routes_to 3 recorded under acct-b. Build 1 is published."""
    db.add_all([CloudAccount(id=1, name="acct-a", provider="aws", credentials={}),
                CloudAccount(id=2, name="acct-b", provider="aws", credentials={})])
    for rid, acct, rtype, name in [(2, 1, "Subnet", "subnet-1"), (3, 1, "EC2", "i-1"), (4, 1, "SecurityGroup", "sg-1"),
                                   (5, 1, "ELB", "alb"), (7, 2, "EC2", "i-7")]:
        db.add(CloudResource(id=rid, account_id=acct, provider="aws", region="us-east-1", resource_type=rtype,
                             resource_id=name, name=name, tags={}, raw_data={}))
    db.add_all([GalaxyBuild(id=1, status="completed", trigger="manual", rules_published_at=datetime(2026, 9, 1)),
                GalaxyBuild(id=2, status="completed", trigger="manual")])
    db.flush()
    for src, dst, rtype, prov, acct in [(2, 3, "contains", "rule", 1), (3, 4, "secured_by", "rule", 1),
                                        (5, 3, "routes_to", "llm", 1), (7, 3, "routes_to", "rule", 2)]:
        db.add(ResourceRelation(build_id=1, account_id=acct, src_ref=src, dst_ref=dst, relation_type=rtype,
                                provenance=prov, evidence={}))
    db.add(HealthIssue(id=1, resource_id="i-1", resource_ref=3, anchor_status="anchored", account_id=1,
                       severity="high", status="investigating", source="test", title="t", description="d",
                       issue_type="cpu_spike"))
    db.commit()
    return db


def _check(s, location, evidence_count=2, issue_id=1):
    return rl.validate_location(s, s.get(HealthIssue, issue_id), location, evidence_count)


def _cand(ref, rank, supporting=None, refuting=None):
    c = {"ref": ref, "rank": rank}
    if supporting is not None:
        c["supporting"] = supporting
    if refuting is not None:
        c["refuting"] = refuting
    return c


# ── absent / invalid input ────────────────────────────────────────────


@pytest.mark.parametrize("location", ["", "  ", "{}", "null", None, {}])
def test_nothing_given_is_absent(seed, location):
    assert _check(seed, location) == (None, "absent", None)


@pytest.mark.parametrize("location,reason", [("{not json", "location: not valid JSON"),
                                             ("[1, 2]", "location: not an object"),
                                             ('"x"', "location: not an object")])
def test_unreadable_location_is_invalid(seed, location, reason):
    assert _check(seed, location) == ({"candidates": [], "path": [], "dropped": [reason]}, "invalid", None)


# ── candidates ────────────────────────────────────────────────────────


def test_valid_location_is_stored_enriched_against_the_published_build(seed):
    loc = {"candidates": [_cand(4, 1, ["E2"], ["e1"]), _cand(3, 2, ["E1"])],
           "path": [{"src_ref": 3, "dst_ref": 4, "relation_type": "secured_by"}]}
    stored, status, build = _check(seed, json.dumps(loc))
    assert (status, build) == ("valid", 1)
    assert stored == {
        "candidates": [
            {"ref": 4, "rank": 1, "type": "SecurityGroup", "name": "sg-1", "resource_id": "sg-1",
             "supporting": ["E2"], "refuting": ["E1"]},
            {"ref": 3, "rank": 2, "type": "EC2", "name": "i-1", "resource_id": "i-1", "supporting": ["E1"],
             "refuting": []}],
        "path": [{"src_ref": 3, "src_name": "i-1", "dst_ref": 4, "dst_name": "sg-1", "relation_type": "secured_by",
                  "provenance": "rule"}],
        "dropped": []}


def test_foreign_missing_and_non_int_refs_are_dropped(seed):
    loc = {"candidates": [_cand(7, 1), _cand(999, 2), _cand(True, 3), _cand("4", 3), _cand(4, 3)]}
    stored, status, _ = _check(seed, loc)
    assert status == "partial" and [c["ref"] for c in stored["candidates"]] == [4]
    assert stored["dropped"] == ["candidate 7: not in the issue's account", "candidate 999: no such resource",
                                 "candidate True: ref is not a resource id", "candidate '4': ref is not a resource id"]


def test_ranks_must_be_distinct_one_to_three_and_are_not_renumbered(seed):
    loc = {"candidates": [_cand(4, 2), _cand(3, 2), _cand(2, 4), _cand(5, 0), _cand(2, None), _cand(5, 3)]}
    stored, status, _ = _check(seed, loc)
    assert status == "partial"
    assert [(c["rank"], c["ref"]) for c in stored["candidates"]] == [(2, 4), (3, 5)]
    assert len(stored["dropped"]) == 4 and all("is not a free rank 1..3" in d for d in stored["dropped"])


def test_evidence_labels_must_name_this_rcas_evidence(seed):
    loc = {"candidates": [_cand(4, 1, ["E1", "E3", "X1", "E0", " e2 "], "E1")]}
    stored, status, _ = _check(seed, loc)
    assert status == "partial"
    assert stored["candidates"][0]["supporting"] == ["E1", "E2"] and stored["candidates"][0]["refuting"] == []
    assert stored["dropped"] == ["candidate 4 supporting: 'E3' is not an evidence item of this RCA",
                                 "candidate 4 supporting: 'X1' is not an evidence item of this RCA",
                                 "candidate 4 supporting: 'E0' is not an evidence item of this RCA",
                                 "candidate 4 refuting: not a list"]


def test_no_candidate_left_is_invalid(seed):
    stored, status, build = _check(seed, {"candidates": [_cand(7, 1)]})
    assert (status, build, stored["candidates"]) == ("invalid", 1, [])
    assert _check(seed, {"candidates": "4"})[1] == "invalid"


def test_an_issue_without_an_account_keeps_no_candidate(seed):
    seed.get(HealthIssue, 1).account_id = None
    seed.commit()
    stored, status, _ = _check(seed, {"candidates": [_cand(3, 1)]})
    assert status == "invalid" and stored["dropped"] == ["candidate 3: not in the issue's account"]


# ── path ──────────────────────────────────────────────────────────────


GOOD_EDGE = {"src_ref": 2, "dst_ref": 3, "relation_type": "contains"}


@pytest.mark.parametrize("bad", [
    {"src_ref": 3, "dst_ref": 2, "relation_type": "contains"},     # reversed: no such relation
    {"src_ref": 2, "dst_ref": 3, "relation_type": "routes_to"},    # wrong type
    {"src_ref": 5, "dst_ref": 3, "relation_type": "routes_to"},    # llm provenance
    {"src_ref": 7, "dst_ref": 3, "relation_type": "routes_to"},    # another account's relation
    {"src_ref": "2", "dst_ref": 3, "relation_type": "contains"},   # not an id
    "2>3",
])
def test_one_bad_edge_drops_the_whole_path(seed, bad):
    stored, status, _ = _check(seed, {"candidates": [_cand(2, 1)], "path": [GOOD_EDGE, bad]})
    assert status == "partial" and stored["path"] == [] and [c["ref"] for c in stored["candidates"]] == [2]
    assert stored["dropped"][0].startswith("path: edge ") and "is not a rule/observed relation of build 1" in \
        stored["dropped"][0]


def test_path_is_checked_against_the_given_build(seed):
    stored, status, build = _check(seed, {"candidates": [_cand(2, 1)], "path": [GOOD_EDGE], "build_id": 2})
    assert (status, build, stored["path"]) == ("partial", 2, [])
    stored, status, build = _check(seed, {"candidates": [_cand(2, 1)], "path": [GOOD_EDGE], "build_id": True})
    assert (status, build, len(stored["path"])) == ("valid", 1, 1)


def test_no_published_build_drops_the_path(seed):
    seed.query(GalaxyBuild).update({"rules_published_at": None})
    seed.commit()
    stored, status, build = _check(seed, {"candidates": [_cand(2, 1)], "path": [GOOD_EDGE]})
    assert (status, build, stored["path"]) == ("partial", None, [])
    assert stored["dropped"] == ["path: no published graph build to check it against"]


@pytest.mark.parametrize("anchor_status,ref", [("unanchored", None), ("ambiguous", None), ("account_level", None),
                                               (None, None)])
def test_an_unanchored_issue_has_no_path(seed, anchor_status, ref):
    issue = seed.get(HealthIssue, 1)
    issue.anchor_status, issue.resource_ref = anchor_status, ref
    seed.commit()
    stored, status, _ = _check(seed, {"candidates": [_cand(2, 1)], "path": [GOOD_EDGE]})
    assert (status, stored["path"]) == ("partial", [])
    assert stored["dropped"] == ["path: the issue is not anchored, so it has no path"]
    assert _check(seed, {"candidates": [_cand(2, 1)], "path": []})[1] == "valid"


def test_a_legacy_issue_with_a_ref_counts_as_anchored(seed):
    seed.get(HealthIssue, 1).anchor_status = None
    seed.commit()
    assert _check(seed, {"candidates": [_cand(2, 1)], "path": [GOOD_EDGE]})[1] == "valid"


# ── save_rca_result ───────────────────────────────────────────────────


def _save(**kw):
    return metadata_tools.save_rca_result._tool_func(
        health_issue_id=1, root_cause="sg change", confidence=0.8, contributing_factors="[]",
        recommendations="[]", evidence=json.dumps(EVIDENCE), **kw)


def test_save_without_location_is_absent(seed):
    msg = _save()
    assert "saved" in msg and "Location" not in msg
    rca = seed.query(RCAResult).one()
    assert (rca.location, rca.location_status, rca.location_build_id) == (None, "absent", None)


def test_save_stores_the_validated_location_and_says_what_was_dropped(seed):
    loc = {"candidates": [_cand(4, 1, ["E2"]), _cand(7, 2), _cand(999, 3)], "path": [GOOD_EDGE], "build_id": 1}
    msg = _save(location=json.dumps(loc))
    assert msg.endswith(" Location: partial. Dropped: candidate 7: not in the issue's account; "
                        "candidate 999: no such resource.")
    rca = seed.query(RCAResult).one()
    assert (rca.location_status, rca.location_build_id) == ("partial", 1)
    assert [c["ref"] for c in rca.location["candidates"]] == [4] and len(rca.location["path"]) == 1
    assert seed.get(HealthIssue, 1).status == "root_cause_identified"


def test_save_caps_the_dropped_list_in_its_reply(seed):
    msg = _save(location=json.dumps({"candidates": [_cand(999, 1), _cand(998, 2), _cand(997, 3), _cand(996, 3)]}))
    assert " Location: invalid. " in msg and msg.endswith("(+1 more).")


def test_a_failed_check_never_loses_the_rca(seed, monkeypatch):
    monkeypatch.setattr(rl, "validate_location", lambda *a: (_ for _ in ()).throw(RuntimeError("db gone")))
    msg = _save(location='{"candidates": [{"ref": 4, "rank": 1}]}')
    assert "saved" in msg and "Location: invalid." in msg
    rca = seed.query(RCAResult).one()
    assert (rca.location_status, rca.location) == (
        "invalid", {"candidates": [], "path": [], "dropped": ["location check failed — RuntimeError"]})


def test_rca_response_carries_the_location(seed):
    from agenticops.web.schemas import RCAResponse

    _save(location=json.dumps({"candidates": [_cand(4, 1)]}))
    out = RCAResponse.model_validate(seed.query(RCAResult).one()).model_dump()
    assert out["location_status"] == "valid" and out["location"]["candidates"][0]["ref"] == 4
    assert (out["location_build_id"], out["location_verdict"]) == (1, None)
