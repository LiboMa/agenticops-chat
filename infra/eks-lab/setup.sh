#!/usr/bin/env bash
# AgenticOps EKS Lab — One-shot setup script
# Creates EKS cluster + Online Boutique + Prometheus/Grafana + OTEL + LitmusChaos
#
# Prerequisites:
#   - AWS CLI configured with appropriate credentials
#   - eksctl >= 0.170.0
#   - kubectl >= 1.28
#   - helm >= 3.14
#
# Usage: ./setup.sh [--skip-cluster]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KUBECONFIG_PATH="${SCRIPT_DIR}/kubeconfig"
CLUSTER_NAME="agenticops-lab"
REGION="ap-southeast-1"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log()  { echo -e "${GREEN}[+]${NC} $*"; }
warn() { echo -e "${YELLOW}[!]${NC} $*"; }
err()  { echo -e "${RED}[✗]${NC} $*" >&2; }
info() { echo -e "${BLUE}[i]${NC} $*"; }

# -------------------------------------------------------------------
# Pre-flight checks
# -------------------------------------------------------------------
check_prerequisites() {
    local missing=0
    for cmd in aws eksctl kubectl helm; do
        if ! command -v "$cmd" &>/dev/null; then
            err "Required command not found: $cmd"
            missing=1
        fi
    done
    if [[ $missing -eq 1 ]]; then
        exit 1
    fi

    # Verify AWS credentials
    if ! aws sts get-caller-identity &>/dev/null; then
        err "AWS credentials not configured or expired"
        exit 1
    fi
    log "Prerequisites OK"
}

# -------------------------------------------------------------------
# Step 1: Create EKS cluster
# -------------------------------------------------------------------
create_cluster() {
    if [[ "${1:-}" == "--skip-cluster" ]]; then
        warn "Skipping cluster creation (--skip-cluster)"
        eksctl utils write-kubeconfig --cluster "$CLUSTER_NAME" --region "$REGION" --kubeconfig "$KUBECONFIG_PATH"
        return
    fi

    log "Creating EKS cluster: $CLUSTER_NAME (this takes ~15-20 minutes)"
    eksctl create cluster \
        -f "${SCRIPT_DIR}/cluster.yaml" \
        --kubeconfig "$KUBECONFIG_PATH"
    log "Cluster created successfully"
}

# -------------------------------------------------------------------
# Step 2: Create namespaces
# -------------------------------------------------------------------
create_namespaces() {
    log "Creating namespaces"
    for ns in online-boutique monitoring chaos-testing; do
        kubectl create namespace "$ns" --dry-run=client -o yaml | kubectl apply -f -
    done
}

# -------------------------------------------------------------------
# Step 3: Create gp3 StorageClass (default for EBS CSI)
# -------------------------------------------------------------------
create_storage_class() {
    log "Creating gp3 StorageClass"
    kubectl apply -f - <<'EOF'
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: gp3
provisioner: ebs.csi.aws.com
parameters:
  type: gp3
  fsType: ext4
reclaimPolicy: Delete
volumeBindingMode: WaitForFirstConsumer
allowVolumeExpansion: true
EOF
}

# -------------------------------------------------------------------
# Step 4: Install kube-prometheus-stack
# -------------------------------------------------------------------
install_prometheus() {
    log "Adding Helm repos"
    helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
    helm repo update prometheus-community

    log "Installing kube-prometheus-stack"
    helm upgrade --install prometheus prometheus-community/kube-prometheus-stack \
        --namespace monitoring \
        --values "${SCRIPT_DIR}/monitoring/prometheus-values.yaml" \
        --timeout 10m \
        --wait
    log "Prometheus + Grafana installed"
}

# -------------------------------------------------------------------
# Step 5: Install OpenTelemetry Collector
# -------------------------------------------------------------------
install_otel_collector() {
    helm repo add open-telemetry https://open-telemetry.github.io/opentelemetry-helm-charts
    helm repo update open-telemetry

    log "Installing OpenTelemetry Collector"
    helm upgrade --install otel-collector open-telemetry/opentelemetry-collector \
        --namespace monitoring \
        --values "${SCRIPT_DIR}/monitoring/otel-collector-values.yaml" \
        --timeout 5m \
        --wait
    log "OTEL Collector installed"
}

# -------------------------------------------------------------------
# Step 6: Install Online Boutique
# -------------------------------------------------------------------
install_online_boutique() {
    log "Installing Online Boutique (raw manifests)"
    local MANIFESTS_URL="https://raw.githubusercontent.com/GoogleCloudPlatform/microservices-demo/main/release/kubernetes-manifests.yaml"
    local MANIFESTS_FILE="${SCRIPT_DIR}/app/kubernetes-manifests.yaml"

    if [[ ! -f "$MANIFESTS_FILE" ]]; then
        curl -sL "$MANIFESTS_URL" -o "$MANIFESTS_FILE"
    fi

    kubectl apply -f "$MANIFESTS_FILE" -n online-boutique
    log "Online Boutique installed"
}

# -------------------------------------------------------------------
# Step 7: Install LitmusChaos
# -------------------------------------------------------------------
install_litmus() {
    helm repo add litmuschaos https://litmuschaos.github.io/litmus-helm/
    helm repo update litmuschaos

    log "Installing LitmusChaos"
    helm upgrade --install litmus litmuschaos/litmus \
        --namespace chaos-testing \
        --values "${SCRIPT_DIR}/chaos/litmus-values.yaml" \
        --timeout 10m \
        --wait
    log "LitmusChaos installed"
}

# -------------------------------------------------------------------
# Step 8: Wait for pods and print access info
# -------------------------------------------------------------------
wait_and_print_info() {
    log "Waiting for Online Boutique pods to be ready..."
    kubectl wait --for=condition=ready pod \
        --all -n online-boutique \
        --timeout=300s 2>/dev/null || warn "Some pods not ready yet — check manually"

    echo ""
    echo "============================================================"
    echo "  AgenticOps Lab — Setup Complete"
    echo "============================================================"
    echo ""

    # Kubeconfig
    info "Kubeconfig: export KUBECONFIG=${KUBECONFIG_PATH}"
    echo ""

    # Frontend URL
    FRONTEND_URL=$(kubectl get svc frontend-external -n online-boutique \
        -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || echo "pending")
    info "Online Boutique: http://${FRONTEND_URL}"

    # Grafana URL
    GRAFANA_URL=$(kubectl get svc prometheus-grafana -n monitoring \
        -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || echo "pending")
    info "Grafana:         http://${GRAFANA_URL} (admin / agenticops-lab)"

    # LitmusChaos URL
    LITMUS_URL=$(kubectl get svc litmus-frontend-service -n chaos-testing \
        -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || echo "pending")
    info "LitmusChaos:     http://${LITMUS_URL} (admin / litmus)"

    echo ""
    info "If URLs show 'pending', wait a minute and run:"
    info "  kubectl get svc -A | grep LoadBalancer"
    echo ""

    # Quick verification
    log "Cluster nodes:"
    kubectl get nodes -o wide
    echo ""
    log "Pod status by namespace:"
    for ns in online-boutique monitoring chaos-testing; do
        echo "--- $ns ---"
        kubectl get pods -n "$ns" --no-headers 2>/dev/null | awk '{printf "  %-50s %s\n", $1, $3}'
    done
    echo ""
    log "Setup complete. Use 'export KUBECONFIG=${KUBECONFIG_PATH}' to interact with the cluster."
}

# -------------------------------------------------------------------
# Main
# -------------------------------------------------------------------
main() {
    check_prerequisites
    create_cluster "${1:-}"
    export KUBECONFIG="$KUBECONFIG_PATH"
    create_namespaces
    create_storage_class
    install_prometheus
    install_otel_collector
    install_online_boutique
    install_litmus
    wait_and_print_info
}

main "$@"
