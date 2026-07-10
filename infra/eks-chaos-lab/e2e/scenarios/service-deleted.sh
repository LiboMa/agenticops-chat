#!/usr/bin/env bash
# Evidence scenario: delete the backend Service (endpoints go empty), and restore.
set -euo pipefail
NS="chaos-lab"
ACTION="${1:-}"
case "${ACTION}" in
  break)
    kubectl get svc backend -n "${NS}" -o yaml > /tmp/agenticops-backend-svc.yaml 2>/dev/null || true
    kubectl delete svc backend -n "${NS}" --ignore-not-found
    echo "backend Service deleted — frontend can no longer resolve it."
    ;;
  restore)
    if [[ -f /tmp/agenticops-backend-svc.yaml ]]; then
      kubectl apply -f /tmp/agenticops-backend-svc.yaml || true
    else
      kubectl expose deployment backend -n "${NS}" --name=backend --port=80 --target-port=8080 2>/dev/null || true
    fi
    echo "backend Service restored."
    ;;
  *) echo "Usage: service-deleted.sh [break|restore]"; exit 1;;
esac
