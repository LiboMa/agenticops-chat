#!/usr/bin/env bash
# Restore all chaos experiments at once.
# Safe to run even if no chaos was injected.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NAMESPACE="chaos-lab"

echo "=== Restoring all chaos experiments ==="
echo ""

# 1. Remove stress pod
echo "[1/5] Removing stress pod..."
kubectl delete pod stress-test -n "${NAMESPACE}" --force --grace-period=0 2>/dev/null && echo "  Removed." || echo "  Not found (OK)."
echo ""

# 2. Remove chaos NetworkPolicy
echo "[2/5] Removing chaos NetworkPolicy..."
kubectl delete networkpolicy chaos-block-backend -n "${NAMESPACE}" 2>/dev/null && echo "  Removed." || echo "  Not found (OK)."
echo ""

# 3. Restore frontend image and config
echo "[3/5] Restoring frontend image and config..."
kubectl set image deployment/frontend -n "${NAMESPACE}" nginx=nginx:1.25-alpine 2>/dev/null || true
kubectl apply -f "${SCRIPT_DIR}/../workloads/configmap.yaml" 2>/dev/null || true
kubectl rollout restart deployment/frontend -n "${NAMESPACE}" 2>/dev/null || true
echo "  Frontend image and config restored."
echo ""

# 4. Restore replica counts
echo "[4/5] Restoring replica counts..."
kubectl scale deployment frontend -n "${NAMESPACE}" --replicas=3 2>/dev/null || true
kubectl scale deployment backend -n "${NAMESPACE}" --replicas=2 2>/dev/null || true
echo "  frontend=3, backend=2"
echo ""

# 5. Uncordon all nodes
echo "[5/5] Uncordoning all nodes..."
for NODE in $(kubectl get nodes -o jsonpath='{.items[*].metadata.name}' 2>/dev/null); do
    kubectl uncordon "${NODE}" 2>/dev/null || true
    echo "  Uncordoned ${NODE}"
done
echo ""

# Wait for rollouts
echo "Waiting for deployments to stabilize..."
kubectl rollout status deployment/frontend -n "${NAMESPACE}" --timeout=120s 2>/dev/null || true
kubectl rollout status deployment/backend -n "${NAMESPACE}" --timeout=120s 2>/dev/null || true

echo ""
echo "=== Restore complete ==="
echo ""
kubectl get nodes
echo ""
kubectl get pods -n "${NAMESPACE}" -o wide
