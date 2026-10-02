"""The chaos lab must survive its own faults (MVP-2.6.1 joint E2E findings, 2026-10-02).

service-deleted could not restore what it deleted, which voided a location-eval batch.
"""
import os
import pathlib
import subprocess

import yaml

LAB = pathlib.Path(__file__).resolve().parents[1] / "infra/eks-chaos-lab"


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
