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
BASTION_IP="${BASTION_IP:?ERROR: Set BASTION_IP to your bastion private IP (e.g. export BASTION_IP=10.0.1.100)}"

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

    log "Rendering prometheus-values.yaml with BASTION_IP=${BASTION_IP}"
    sed "s/<BASTION_PRIVATE_IP>/${BASTION_IP}/g" \
        "${SCRIPT_DIR}/monitoring/prometheus-values.yaml" > /tmp/prometheus-values-rendered.yaml

    log "Installing kube-prometheus-stack"
    helm upgrade --install prometheus prometheus-community/kube-prometheus-stack \
        --namespace monitoring \
        --values /tmp/prometheus-values-rendered.yaml \
        --timeout 10m \
        --wait
    log "Prometheus + Grafana installed"
}

# -------------------------------------------------------------------
# Step 4b: Install metrics-server (needed for kubectl top, HPA)
# -------------------------------------------------------------------
install_metrics_server() {
    # eksctl may install metrics-server as an EKS addon — skip if already running
    if kubectl get deploy metrics-server -n kube-system &>/dev/null; then
        log "metrics-server already installed (EKS addon), skipping"
        return
    fi
    log "Installing metrics-server"
    kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml
    kubectl wait --for=condition=available deploy/metrics-server -n kube-system --timeout=120s
    log "metrics-server installed"
}

# -------------------------------------------------------------------
# Step 4c: Apply alert rules (PrometheusRule CRD)
# -------------------------------------------------------------------
install_alert_rules() {
    log "Applying PrometheusRule alert rules"
    kubectl apply -f "${SCRIPT_DIR}/monitoring/alert-rules.yaml" -n monitoring
    log "Alert rules applied"
}

# -------------------------------------------------------------------
# Step 4d: Install Jaeger (all-in-one trace backend)
# -------------------------------------------------------------------
install_jaeger() {
    helm repo add jaegertracing https://jaegertracing.github.io/helm-charts
    helm repo update jaegertracing

    log "Installing Jaeger (all-in-one)"
    helm upgrade --install jaeger jaegertracing/jaeger \
        --namespace monitoring \
        --values "${SCRIPT_DIR}/monitoring/jaeger-values.yaml" \
        --timeout 5m \
        --wait
    log "Jaeger installed (query: jaeger-query.monitoring:16686)"
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

    # Patch OTEL endpoint + enable tracing for all microservices
    log "Patching OTEL exporter endpoint and enabling tracing on Online Boutique services"
    local OTEL_ENDPOINT="http://otel-collector-opentelemetry-collector.monitoring:4317"
    local COLLECTOR_ADDR="otel-collector-opentelemetry-collector.monitoring:4317"
    for deploy in cartservice productcatalogservice currencyservice paymentservice \
                   shippingservice emailservice checkoutservice recommendationservice adservice frontend; do
        kubectl set env deploy/"$deploy" -n online-boutique \
            OTEL_EXPORTER_OTLP_ENDPOINT="$OTEL_ENDPOINT" \
            OTEL_SERVICE_NAME="$deploy" \
            COLLECTOR_SERVICE_ADDR="$COLLECTOR_ADDR" \
            ENABLE_TRACING=1 2>/dev/null || true
    done

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
# Step 8: Snapshot clean state for scenario restore
# -------------------------------------------------------------------
snapshot_clean_state() {
    log "Saving clean-state snapshot for scenario framework"
    mkdir -p "${SCRIPT_DIR}/scenarios"
    kubectl get deploy -n online-boutique -o yaml > "${SCRIPT_DIR}/scenarios/.clean-state.yaml"
    log "Clean state saved to scenarios/.clean-state.yaml"
}

# -------------------------------------------------------------------
# Step 9: Wait for pods and print access info
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

    info "All services are ClusterIP (internal only). Access via kubectl port-forward:"
    echo ""
    info "Online Boutique: kubectl port-forward svc/frontend -n online-boutique 8080:80"
    info "Grafana:         kubectl port-forward svc/prometheus-grafana -n monitoring 3000:80  (admin / agenticops-lab)"
    info "LitmusChaos:     kubectl port-forward svc/litmus-frontend-service -n chaos-testing 9091:9091  (admin / litmus)"
    info "Prometheus:      kubectl port-forward svc/prometheus-kube-prometheus-prometheus -n monitoring 9090:9090"
    echo ""
    info "SSH tunnel from local: ssh -L 3000:localhost:3000 -L 8080:localhost:8080 ubuntu@<bastion>"
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
    install_metrics_server
    install_alert_rules
    install_jaeger
    install_otel_collector
    install_online_boutique
    install_litmus
    snapshot_clean_state
    wait_and_print_info
}

main "$@"
