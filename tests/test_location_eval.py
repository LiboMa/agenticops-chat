"""Location eval metrics, offline (MVP-2.6.1 Plan C Task 7, spec §3.C.6)."""
import importlib.util
import json
import pathlib

import pytest

# Load location_eval.py from infra/ (not a package) by path.
_E2E = pathlib.Path(__file__).resolve().parents[1] / "infra/eks-chaos-lab/e2e"
_spec = importlib.util.spec_from_file_location("location_eval", _E2E / "location_eval.py")
le = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(le)

CLUSTER = "agenticops-chaos-lab"
FRONTEND = ("Deployment", "chaos-lab", "frontend")
NODE = ("Node", None, "ip-10-0-1-5.ec2.internal")


def _cand(rank, resource_id):
    return {"ref": rank, "rank": rank, "resource_id": resource_id}


# ── ids and keys ──────────────────────────────────────────────────────


@pytest.mark.parametrize("resource_id, key", [
    (f"{CLUSTER}/Deployment/chaos-lab/frontend", FRONTEND),
    (f"{CLUSTER}/Node/ip-10-0-1-5.ec2.internal", NODE),
    (f"arn:aws:eks:us-east-1:111111111111:cluster/{CLUSTER}", None),
    ("i-0abc", None), (f"{CLUSTER}//frontend", None), (f"{CLUSTER}/a/b/c/d", None), (None, None), (3, None),
])
def test_parse_k8s_id(resource_id, key):
    assert le.parse_k8s_id(resource_id) == key


def test_accept_keys_leave_a_cluster_scoped_object_without_a_namespace():
    assert le.accept_keys([{"kind": "Deployment", "namespace": "chaos-lab", "name": "frontend"},
                           {"kind": "Node", "name": "n1"}]) == {FRONTEND, ("Node", None, "n1")}
    assert le.accept_keys(None) == set()


def test_dynamic_keys():
    case = {"root_cause_dynamic": [{"kind": "Node", "from_stdout": r"Target node: (\S+)"},
                                   {"kind": "Node", "from_pod_node": "chaos-lab/stress-test"}]}
    assert le.dynamic_keys(case, "Draining...\nTarget node: n1\n", {"chaos-lab/stress-test": "n2"}) == {
        ("Node", None, "n1"), ("Node", None, "n2")}
    assert le.dynamic_keys(case, "no match", {}) == set()
    assert le.dynamic_keys({}, "Target node: n1", {}) == set()


# ── scoring one run ───────────────────────────────────────────────────


def test_hit_rank_is_the_best_matching_rank():
    location = {"candidates": [_cand(1, f"{CLUSTER}/Pod/chaos-lab/frontend-7d9"),
                               _cand(2, f"{CLUSTER}/Deployment/chaos-lab/frontend"),
                               _cand(3, f"{CLUSTER}/Deployment/chaos-lab/frontend")]}
    assert le.hit_rank(location, {FRONTEND}) == 2
    assert le.hit_rank(location, {NODE}) is None
    assert le.hit_rank(None, {FRONTEND}) is None
    assert le.hit_rank({"candidates": []}, {FRONTEND}) is None


def test_graph_recall():
    focus = {"truncated": False, "nodes": [{"ref": 1}, {"ref": 2, "absent": True}]}
    ref_keys = {1: ("EKS", None, "x"), 2: FRONTEND}
    assert le.graph_recall(focus, ref_keys, {FRONTEND}) is True       # an absent node counts
    assert le.graph_recall(focus, ref_keys, {NODE}) is False
    assert le.graph_recall({**focus, "truncated": True}, ref_keys, {FRONTEND}) is False
    assert le.graph_recall(None, ref_keys, {FRONTEND}) is False


# ── the cases ─────────────────────────────────────────────────────────


SCENARIOS = [{"id": "s", "inject": "a.sh inject", "restore": "a.sh restore", "perceive": {"alert": {"AlarmName": "A"}}},
             {"id": "e", "inject": "b.sh break", "restore": "b.sh restore"}]
ROOT = [{"kind": "Deployment", "namespace": "chaos-lab", "name": "frontend"}]


def test_load_cases_fills_from_the_scenario_and_the_entry_wins():
    cases = le.load_cases([{"id": "s", "scenario": "s", "root_cause": ROOT},
                           {"id": "e", "scenario": "e", "root_cause": ROOT, "alert": {"AlarmName": "B"}},
                           {"id": "n", "inject": "c.sh x", "restore": "c.sh y", "alert": {"AlarmName": "C"},
                            "root_cause": ROOT}], SCENARIOS)
    assert [(c["inject"], c["restore"], c["alert"]["AlarmName"]) for c in cases] == [
        ("a.sh inject", "a.sh restore", "A"), ("b.sh break", "b.sh restore", "B"), ("c.sh x", "c.sh y", "C")]


@pytest.mark.parametrize("entry, error", [
    ({"id": "x", "scenario": "nope", "root_cause": ROOT}, "no scenario"),
    ({"id": "x", "scenario": "e", "root_cause": ROOT}, "missing alert"),
    ({"id": "x", "scenario": "s"}, "missing root_cause"),
])
def test_load_cases_rejects_an_incomplete_entry(entry, error):
    with pytest.raises(ValueError, match=error):
        le.load_cases([entry], SCENARIOS)


def test_the_shipped_ground_truth_has_13_complete_cases():
    cases = le.load_default_cases()
    assert len(cases) == 13 and len({c["id"] for c in cases}) == 13
    for c in cases:
        assert c["fault_type"] and c["alert"]["AlarmName"].startswith(f"EKS-{CLUSTER}-")
        assert "Dimensions" not in c["alert"]
        assert le.accept_keys(c.get("root_cause")) or c["root_cause_dynamic"]
        for script in (c["inject"], c["restore"]):
            assert (_E2E.parent / script.split()[0]).is_file(), script


# ── the batch summary ─────────────────────────────────────────────────


def _run(batch, rank, recall, valid=True, status="valid"):
    return {"batch": batch, "case": "c", "valid": valid, "rank": rank, "graph_recall": recall,
            "location_status": status}


def test_summarize():
    runs = [_run("on", 1, True), _run("on", 2, True, status="partial"), _run("on", None, False, status="invalid"),
            _run("on", 5, True, status=None),
            _run("on", None, None, valid=False), _run("off", None, None, valid=False)]
    out = le.summarize(runs)
    assert out["on"] == {"runs": 5, "valid": 4, "invalid": 1, "ac1": 0.25, "ac3": 0.5,
                         "mrr": round((1 + 0.5 + 0.2) / 4, 4), "located": 0.5, "graph_recall": 0.75}
    assert out["off"] == {"runs": 1, "valid": 0, "invalid": 1, "ac1": None, "ac3": None, "mrr": None,
                          "located": None, "graph_recall": None}


def test_main_prints_the_tables(tmp_path, capsys):
    path = tmp_path / "location-1.json"
    path.write_text(json.dumps({"batch": "on", "runs": [_run("on", 1, True)]}))
    assert le.main([str(path)]) == 0
    out = capsys.readouterr().out
    assert "| on | 1 | 1 | 0 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |" in out
    assert "| c | rank 1 · valid · recall yes |" in out
