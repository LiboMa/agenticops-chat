#!/usr/bin/env bash
# AgenticOps EKS Lab — Teardown script
# Removes all Helm releases and deletes the EKS cluster
#
# Usage: ./teardown.sh [--skip-cluster]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KUBECONFIG_PATH="${SCRIPT_DIR}/kubeconfig"
CLUSTER_NAME="agenticops-lab"
REGION="us-west-2"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()  { echo -e "${GREEN}[+]${NC} $*"; }
warn() { echo -e "${YELLOW}[!]${NC} $*"; }
err()  { echo -e "${RED}[✗]${NC} $*" >&2; }

# Use local kubeconfig if it exists, otherwise fall back to default
if [[ -f "$KUBECONFIG_PATH" ]]; then
    export KUBECONFIG="$KUBECONFIG_PATH"
fi

echo ""
echo "============================================================"
echo "  AgenticOps Lab — Teardown"
echo "============================================================"
echo ""
warn "This will destroy the entire agenticops-lab EKS cluster."
read -rp "Continue? (y/N) " confirm
if [[ "${confirm,,}" != "y" ]]; then
    echo "Aborted."
    exit 0
fi

# -------------------------------------------------------------------
# Step 1: Uninstall Helm releases (order: app → chaos → monitoring)
# -------------------------------------------------------------------
log "Uninstalling Helm releases..."

kubectl delete -f "${SCRIPT_DIR}/app/kubernetes-manifests.yaml" -n online-boutique --ignore-not-found 2>/dev/null && log "  Removed: online-boutique" || warn "  online-boutique not found"
helm uninstall litmus -n chaos-testing 2>/dev/null && log "  Removed: litmus" || warn "  litmus not found"
helm uninstall otel-collector -n monitoring 2>/dev/null && log "  Removed: otel-collector" || warn "  otel-collector not found"
helm uninstall prometheus -n monitoring 2>/dev/null && log "  Removed: prometheus" || warn "  prometheus not found"

# -------------------------------------------------------------------
# Step 2: Clean up PVCs (Prometheus/Grafana/MongoDB storage)
# -------------------------------------------------------------------
log "Cleaning up PersistentVolumeClaims..."
for ns in monitoring chaos-testing online-boutique; do
    kubectl delete pvc --all -n "$ns" --ignore-not-found 2>/dev/null || true
done

# -------------------------------------------------------------------
# Step 3: Delete namespaces
# -------------------------------------------------------------------
log "Deleting namespaces..."
for ns in online-boutique monitoring chaos-testing; do
    kubectl delete namespace "$ns" --ignore-not-found 2>/dev/null || true
done

# -------------------------------------------------------------------
# Step 4: Delete EKS cluster
# -------------------------------------------------------------------
if [[ "${1:-}" == "--skip-cluster" ]]; then
    warn "Skipping cluster deletion (--skip-cluster)"
else
    log "Deleting EKS cluster: $CLUSTER_NAME (this takes ~10-15 minutes)"
    eksctl delete cluster \
        --name "$CLUSTER_NAME" \
        --region "$REGION" \
        --wait
    log "Cluster deleted"
fi

# -------------------------------------------------------------------
# Step 5: Clean up local files
# -------------------------------------------------------------------
if [[ -f "$KUBECONFIG_PATH" ]]; then
    rm -f "$KUBECONFIG_PATH"
    log "Removed local kubeconfig"
fi

echo ""
log "Teardown complete."
