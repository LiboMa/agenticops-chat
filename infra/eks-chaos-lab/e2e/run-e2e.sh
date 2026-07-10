#!/usr/bin/env bash
# Remote-server entrypoint for the EKS chaos E2E suite.
# Tunnels to the ClusterIP app via port-forward, runs pytest, always restores.
# Usage: bash run-e2e.sh [--assert-only|--evidence-only] [-- <pytest args>]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHAOS_LAB_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
NS="agenticops"
LOCAL_PORT="${LOCAL_PORT:-8000}"
SELECT=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --assert-only)   SELECT="test_e2e_four_phases.py"; shift;;
    --evidence-only) SELECT="test_e2e_evidence.py"; shift;;
    --) shift; break;;
    *) break;;
  esac
done

export CHAOS_LAB_DIR
export AGENTICOPS_URL="http://localhost:${LOCAL_PORT}"
export AWS_ACCOUNT_ID="${AWS_ACCOUNT_ID:-$(aws sts get-caller-identity --query Account --output text)}"

echo "[preflight] cluster + app reachable?"
kubectl get svc agenticops -n "${NS}" >/dev/null

echo "[tunnel] kubectl port-forward svc/agenticops ${LOCAL_PORT}:8000"
kubectl port-forward "svc/agenticops" -n "${NS}" "${LOCAL_PORT}:8000" >/tmp/agenticops-pf.log 2>&1 &
PF_PID=$!
cleanup() {
  kill "${PF_PID}" 2>/dev/null || true
  bash "${CHAOS_LAB_DIR}/chaos/restore-all.sh" || true
}
trap cleanup EXIT

# Wait for the tunnel + app health.
for i in $(seq 1 30); do
  if curl -sf "${AGENTICOPS_URL}/api/health" >/dev/null 2>&1; then break; fi
  sleep 2
done
curl -sf "${AGENTICOPS_URL}/api/health" >/dev/null || { echo "app health check failed"; exit 1; }

echo "[run] pytest"
cd "${SCRIPT_DIR}"
python -m pytest ${SELECT} -v --junitxml=results/junit.xml "$@" || true

echo "[done] artifacts under ${SCRIPT_DIR}/results/"
