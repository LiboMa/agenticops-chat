"""Pytest fixtures for the EKS chaos E2E harness."""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import time

import pytest
import yaml

from client import AgenticOpsClient  # same dir; pytest adds rootdir to sys.path via conftest

E2E_DIR = pathlib.Path(__file__).resolve().parent
CHAOS_LAB_DIR = pathlib.Path(os.environ.get("CHAOS_LAB_DIR", str(E2E_DIR.parent)))
SCENARIOS = yaml.safe_load(open(E2E_DIR / "scenarios.yaml"))


def pytest_generate_tests(metafunc):
    if "assert_scenario" in metafunc.fixturenames:
        cases = [s for s in SCENARIOS if s["mode"] == "assert"]
        metafunc.parametrize("assert_scenario", cases, ids=[c["id"] for c in cases])
    if "evidence_scenario" in metafunc.fixturenames:
        cases = [s for s in SCENARIOS if s["mode"] == "evidence"]
        metafunc.parametrize("evidence_scenario", cases, ids=[c["id"] for c in cases])


@pytest.fixture(scope="session")
def client() -> AgenticOpsClient:
    base = os.environ.get("AGENTICOPS_URL", "http://localhost:8000")
    c = AgenticOpsClient(base)
    # The app seeds the admin user with email literally "admin" (see app.py
    # create_user(email="admin", ...)), NOT an @-address.
    email = os.environ.get("AIOPS_ADMIN_EMAIL", "admin")
    pw = os.environ.get("AIOPS_ADMIN_PASSWORD", "aiops2026")
    c.login(email, pw)
    acct = os.environ.get("AWS_ACCOUNT_ID")
    if acct:
        c.ensure_account("chaos-lab", acct, ["us-east-1"])
    return c


def run_chaos(rel_cmd: str) -> None:
    parts = rel_cmd.split()
    script = CHAOS_LAB_DIR / parts[0]
    subprocess.run(["bash", str(script), *parts[1:]], check=True,
                   cwd=str(CHAOS_LAB_DIR), timeout=300)


def kubectl_json(args: str) -> dict:
    out = subprocess.run(["kubectl", *args.split(), "-o", "json"],
                         capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        return {}
    return json.loads(out.stdout) if out.stdout.strip() else {}


def verify_fix(expect: dict) -> tuple[bool, str]:
    kind = expect["kind"]
    if kind == "replicas_min":
        d = kubectl_json(f"get deploy {expect['deployment']} -n {expect['namespace']}")
        n = (d.get("status", {}) or {}).get("availableReplicas", 0) or 0
        return n >= expect["min"], f"availableReplicas={n} (>= {expect['min']})"
    if kind == "image_not_contains":
        d = kubectl_json(f"get deploy {expect['deployment']} -n {expect['namespace']}")
        imgs = [c.get("image", "") for c in
                d.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])]
        bad = [i for i in imgs if expect["substring"] in i]
        return not bad, f"images={imgs}"
    if kind == "node_schedulable":
        d = kubectl_json("get nodes")
        unsched = [n["metadata"]["name"] for n in d.get("items", [])
                   if (n.get("spec", {}) or {}).get("unschedulable")]
        return not unsched, f"unschedulable={unsched}"
    if kind == "no_pod_label":
        d = kubectl_json(f"get pods -n {expect['namespace']} -l {expect['selector']}")
        items = d.get("items", [])
        return len(items) == 0, f"pods_with_label={len(items)}"
    if kind == "no_networkpolicy":
        d = kubectl_json(f"get networkpolicy -n {expect['namespace']}")
        names = [n["metadata"]["name"] for n in d.get("items", [])]
        return expect["name"] not in names, f"netpols={names}"
    if kind == "coredns_min":
        d = kubectl_json("get deploy coredns -n kube-system")
        n = (d.get("status", {}) or {}).get("availableReplicas", 0) or 0
        return n >= expect["min"], f"coredns availableReplicas={n}"
    if kind == "service_exists":
        d = kubectl_json(f"get svc {expect['name']} -n {expect['namespace']}")
        return bool(d.get("metadata")), f"service present={bool(d.get('metadata'))}"
    return False, f"unknown expect kind {kind}"


def restore_and_wait(scenario: dict) -> None:
    try:
        run_chaos(scenario["restore"])
    except Exception as e:  # noqa: BLE001 — restore must not mask the test result
        print(f"[restore] warning: {e}")
    time.sleep(5)
