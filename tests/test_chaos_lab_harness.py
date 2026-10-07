"""The chaos lab must survive its own faults (MVP-2.6.1 joint E2E findings, 2026-10-02).

coredns-down SIGKILLed the observer (a liveness probe that calls AWS, names resolved through the observed cluster's
CoreDNS), and service-deleted could not restore what it deleted. Both voided a location-eval batch.
"""
import os
import pathlib
import subprocess

import yaml

LAB = pathlib.Path(__file__).resolve().parents[1] / "infra/eks-chaos-lab"


def _app_pod_spec() -> dict:
    docs = yaml.safe_load_all((LAB / "agenticops/deployment.yaml").read_text())
    return next(d for d in docs if d and d.get("kind") == "Deployment")["spec"]["template"]["spec"]


def test_liveness_does_not_call_external_services():
    # /api/health calls AWS STS: as the liveness probe it turned a DNS outage into a restart of the observer.
    probe = _app_pod_spec()["containers"][0]["livenessProbe"]
    assert "httpGet" not in probe
    assert probe["tcpSocket"]["port"] == 8000


def test_observer_does_not_resolve_names_through_the_observed_clusters_dns():
    spec = _app_pod_spec()
    assert spec["dnsPolicy"] == "Default"  # the node's (VPC) resolver: Bedrock, STS and EKS stay reachable
    script = spec["initContainers"][0]["args"][0]
    assert "kubernetes.default.svc" not in script
    assert "server: https://${KUBERNETES_SERVICE_HOST}:${KUBERNETES_SERVICE_PORT}" in script


def test_service_deleted_restores_from_the_workload_manifest(tmp_path):
    calls = tmp_path / "calls"
    kubectl = tmp_path / "kubectl"
    # The Service is already gone, as on a retried attempt: every `get` fails.
    kubectl.write_text(f'#!/bin/sh\necho "$*" >> "{calls}"\n[ "$1" = get ] && exit 1\nexit 0\n')
    kubectl.chmod(0o755)
    env = {**os.environ, "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}"}
    script = LAB / "e2e/scenarios/service-deleted.sh"
    for action in ("break", "break", "restore"):
        subprocess.run(["bash", str(script), action], env=env, check=True, capture_output=True)

    applied = [line.split() for line in calls.read_text().splitlines() if line.startswith("apply")]
    manifest = LAB / "workloads/backend-deployment.yaml"
    assert len(applied) == 1 and applied[0][:2] == ["apply", "-f"]
    assert pathlib.Path(applied[0][2]).resolve() == manifest
    assert any(d and d["kind"] == "Service" and d["metadata"]["name"] == "backend"
               for d in yaml.safe_load_all(manifest.read_text()))
