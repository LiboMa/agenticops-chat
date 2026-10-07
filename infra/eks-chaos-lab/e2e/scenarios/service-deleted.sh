#!/usr/bin/env bash
# Evidence scenario: delete the backend Service (endpoints go empty), and restore.
set -euo pipefail
NS="chaos-lab"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# The Service's source of truth is the workload manifest. A `kubectl get -o yaml` backup cannot be re-applied
# (it carries resourceVersion, so the create is rejected), and a retried break overwrote it with nothing.
MANIFEST="${SCRIPT_DIR}/../../workloads/backend-deployment.yaml"
ACTION="${1:-}"
case "${ACTION}" in
  break)
    kubectl delete svc backend -n "${NS}" --ignore-not-found
    echo "backend Service deleted — frontend can no longer resolve it."
    ;;
  restore)
    kubectl apply -f "${MANIFEST}"
    echo "backend Service restored."
    ;;
  *) echo "Usage: service-deleted.sh [break|restore]"; exit 1;;
esac
