#!/usr/bin/env bash
# Remote-server entrypoint for the EKS chaos E2E suite.
# Tunnels to the ClusterIP app via port-forward, runs pytest, always restores.
# Usage: bash run-e2e.sh [--assert-only|--evidence-only] [-- <pytest args>]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHAOS_LAB_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
NS="agenticops"
SELECT=""

# Pick a local port for the tunnel. Default 8000, but if something is already
# bound there (e.g. a local `uvicorn agenticops.web.app` dev server), pick a
# free port instead — otherwise `kubectl port-forward` silently fails to bind
# and every request hits the OTHER app on :8000 (observed live: login 401s
# against a stale local DB). Override with LOCAL_PORT=<n>.
pick_port() {
  local p
  for p in "${LOCAL_PORT:-8000}" 8899 8901 18000; do
    if ! (exec 3<>"/dev/tcp/127.0.0.1/${p}") 2>/dev/null; then echo "${p}"; return; fi
    exec 3>&- 2>/dev/null || true
    echo "[preflight] local port ${p} is busy — trying next" >&2
  done
  echo "8000"
}
LOCAL_PORT="$(pick_port)"

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

# Confirm the tunnel reaches the IN-CLUSTER app (not some other :8000 process):
# a valid admin login must succeed. If this 401s, we're talking to the wrong app.
if ! curl -sf -X POST "${AGENTICOPS_URL}/api/auth/login" \
      -H 'Content-Type: application/json' \
      -d "{\"email\":\"${AIOPS_ADMIN_EMAIL:-admin}\",\"password\":\"${AIOPS_ADMIN_PASSWORD:-aiops2026}\"}" \
      >/dev/null 2>&1; then
  echo "[preflight] login via ${AGENTICOPS_URL} failed — the tunnel may be hitting a different app. Aborting."
  exit 1
fi
echo "[tunnel] verified in-cluster app on ${AGENTICOPS_URL}"

echo "[run] pytest"
cd "${SCRIPT_DIR}"
python -m pytest ${SELECT} -v --junitxml=results/junit.xml "$@" || true

echo "[done] artifacts under ${SCRIPT_DIR}/results/"
