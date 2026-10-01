"""Root-cause location eval (MVP-2.6.1 spec §3.C.6): one batch per invocation, 13 cases.

`run-e2e.sh --location-only` gives the app the eval environment (LOCATION_BATCH=off|on picks
rca_topology_context_enabled; auto-fix and the RAG pipeline are off so nothing touches the cluster or the KB)
and restarts it. The app's database is an emptyDir, so the module preflight onboards the cluster again: resource
scan → K8s connector → graph build.

Per case: inject → settle → alert → the alert must open a NEW issue (a merge makes the run invalid; retried
once) → wait for the RCA → score its location → resolve the issue as the eval teardown → restore. Scoring and
the report tables are location_eval.py; runs go to results/location-<ts>.json after every case.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone

import pytest
import requests

import location_eval as le
from conftest import E2E_DIR, kubectl_json, restore_and_wait, run_chaos

BATCH = os.environ.get("LOCATION_BATCH", "")
CLUSTER = os.environ.get("AIOPS_CHAOS_CLUSTER", "agenticops-chaos-lab")
ATTEMPTS = 2
RCA_TIMEOUT_S = 960          # the RCA watchdog is 900 s
TEARDOWN = "eval teardown"
CASES = le.load_default_cases()
SEEN_ISSUES: set = set()

pytestmark = pytest.mark.skipif(BATCH not in ("off", "on"),
                                reason="the location eval runs only via run-e2e.sh --location-only")


def _retry_409(call, timeout_s: int):
    """POST until it is not refused as busy (409)."""
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            return call()
        except requests.HTTPError as e:
            if e.response is None or e.response.status_code != 409 or time.monotonic() > deadline:
                raise
            time.sleep(15)


def _k8s_connector(client) -> dict:
    return next(c for c in client.get("/api/connectors")["connectors"] if c["name"] == "k8s")


def _run_k8s_connector(client) -> list:
    """One manual K8s connector run, waited for; its run rows (one per cluster). A manual run that changed
    anything also refreshes the graph (rule layer) before it stops running."""
    before = {r["id"] for r in _k8s_connector(client)["recent_runs"]}
    _retry_409(lambda: client.post("/api/connectors/k8s/run"), 900)
    deadline = time.monotonic() + 900
    while True:
        c = _k8s_connector(client)
        new = [r for r in c["recent_runs"] if r["id"] not in before and r["trigger"] == "manual"]
        if new and not c["running"]:
            return new
        assert time.monotonic() < deadline, "the K8s connector run did not finish in 900 s"
        time.sleep(10)


@pytest.fixture(scope="module")
def onboarded(client):
    assert client.get("/api/settings")["auto_fix_enabled"] is False, "the eval environment is not applied"
    account = next(a for a in client.get("/api/accounts") if a.get("name") == "chaos-lab")
    client.post("/api/scan", json={"account_ids": [account["id"]], "focus": "computing"}, timeout=1800)
    runs = _run_k8s_connector(client)
    assert {r["status"] for r in runs} <= {"complete", "partial"}, runs
    # The post-scan build may have been running when the connector tried to refresh the graph.
    _retry_409(lambda: client.post("/api/galaxy/rebuild", timeout=1800), 1800)


@pytest.fixture(scope="module")
def results():
    runs: list = []
    path = E2E_DIR / "results" / f"location-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json"
    path.parent.mkdir(exist_ok=True)

    def record(run: dict) -> None:
        runs.append(run)
        path.write_text(json.dumps({"batch": BATCH, "runs": runs, "summary": le.summarize(runs)}, indent=2))

    return record


def _wait_rca(client, issue_id: int) -> list:
    deadline = time.monotonic() + RCA_TIMEOUT_S
    while time.monotonic() < deadline:
        rcas = client.get(f"/api/health-issues/{issue_id}/rca")
        if rcas:
            return rcas
        time.sleep(15)
    return []


def _teardown(client, issue_id: int) -> None:
    """Resolve, not dismiss: a dismissal would teach the detect agent that the fault was a false positive."""
    try:
        issue = client.get(f"/api/health-issues/{issue_id}")
        client.put(f"/api/health-issues/{issue_id}",
                   json={"status": "resolved",
                         "description": f"{issue['description']}\n\n[closed by the location eval: {TEARDOWN}]"})
    except requests.HTTPError as e:  # already terminal, or gone: nothing to close; the run stays scored
        print(f"[teardown] issue {issue_id}: {e}")


def _attempt(client, case: dict) -> dict:
    restore_and_wait(case)
    stdout = run_chaos(case["inject"], capture=True)
    time.sleep(case.get("settle_s", 10))
    pod_nodes = {}
    for d in case.get("root_cause_dynamic") or []:
        if d.get("from_pod_node"):
            ns, name = d["from_pod_node"].split("/", 1)
            pod_nodes[d["from_pod_node"]] = kubectl_json(f"get pod {name} -n {ns}").get("spec", {}).get("nodeName")
    accept = le.accept_keys(case.get("root_cause")) | le.dynamic_keys(case, stdout, pod_nodes)

    resp = client.send_cloudwatch_alert(case["alert"])
    issue_id = resp.get("health_issue_id")
    if not issue_id or resp.get("deduplicated") or issue_id in SEEN_ISSUES:
        return {"valid": False, "reason": f"no new issue (health_issue_id={issue_id}, "
                                          f"deduplicated={resp.get('deduplicated')}): {resp.get('message')}"}
    SEEN_ISSUES.add(issue_id)
    try:
        started = time.monotonic()
        rcas = _wait_rca(client, issue_id)
        rca = rcas[0] if rcas else {}
        # The location is scored as stored. Graph recall is a property of the graph, and objects the injection
        # created reach the graph only through discovery, so it is measured on a graph refreshed now.
        refresh = [r["status"] for r in _run_k8s_connector(client)]
        anchor = client.get(f"/api/graph/focus?issue_id={issue_id}&depth=1&node_cap=1")["anchor"]
        ref = anchor["refs"][0] if anchor.get("status") == "anchored" and anchor.get("refs") else None
        # All rule relations within 2 hops, both ways: resource_id, because issue_id filters by the issue class.
        focus = client.get(f"/api/graph/focus?resource_id={ref}&depth=2&node_cap=10000&edge_cap=50000"
                           "&include_llm=false") if ref else None
        ref_keys = {r["id"]: le.parse_k8s_id(r["resource_id"])
                    for r in client.get(f"/api/resources?q={CLUSTER}/&include_absent=true")["items"]}
        location = rca.get("location")
        return {"valid": True, "issue_id": issue_id, "rca_id": rca.get("id"),
                "rca_wait_s": round(time.monotonic() - started),
                "note": None if rcas else f"no RCA in {RCA_TIMEOUT_S} s",
                "location_status": rca.get("location_status"),
                "candidates": [[c["rank"], c.get("resource_id")] for c in (location or {}).get("candidates", [])],
                "rank": le.hit_rank(location, accept),
                "anchor_status": anchor.get("status"), "anchor_ref": ref,
                "graph_refresh": refresh, "focus_truncated": bool(focus and focus.get("truncated")),
                "graph_recall": le.graph_recall(focus, ref_keys, accept),
                "accept": sorted((list(k) for k in accept), key=str), "teardown": TEARDOWN}
    finally:
        _teardown(client, issue_id)


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_location(client, onboarded, results, case):
    run = {"batch": BATCH, "case": case["id"], "fault_type": case["fault_type"], "valid": False,
           "rank": None, "graph_recall": None, "location_status": None}
    reasons = []
    try:
        for attempt in range(1, ATTEMPTS + 1):
            run["attempts"] = attempt
            try:
                outcome = _attempt(client, case)
            except Exception as e:  # noqa: BLE001 — recorded as an invalid attempt, never lost
                outcome = {"valid": False, "reason": f"{type(e).__name__}: {e}"}
            if outcome["valid"]:
                run.update(outcome)
                break
            reasons.append(outcome["reason"])
    finally:
        restore_and_wait(case)
    run["invalid_reason"] = None if run["valid"] else "; ".join(reasons)
    results(run)
    assert run["valid"], run["invalid_reason"]
