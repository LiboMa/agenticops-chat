#!/usr/bin/env bash
# AgenticOps EKS Lab — Verification script
# Checks cluster health, all components, metrics flow, and access URLs
#
# Usage: ./verify.sh [--quick]
#   --quick   Skip metric queries and detailed checks

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KUBECONFIG_PATH="${SCRIPT_DIR}/kubeconfig"
CLUSTER_NAME="agenticops-lab"
REGION="ap-southeast-1"
QUICK="${1:-}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m'

pass() { echo -e "  ${GREEN}✓${NC} $*"; }
fail() { echo -e "  ${RED}✗${NC} $*"; FAILURES=$((FAILURES + 1)); }
warn() { echo -e "  ${YELLOW}!${NC} $*"; }
info() { echo -e "  ${BLUE}i${NC} $*"; }
header() { echo -e "\n${BOLD}$*${NC}"; }

FAILURES=0

if [[ -f "$KUBECONFIG_PATH" ]]; then
    export KUBECONFIG="$KUBECONFIG_PATH"
else
    echo -e "${RED}kubeconfig not found at ${KUBECONFIG_PATH}${NC}"
    echo "Run setup.sh first, or: eksctl utils write-kubeconfig --cluster $CLUSTER_NAME --region $REGION --kubeconfig $KUBECONFIG_PATH"
    exit 1
fi

# ===================================================================
header "1. EKS Cluster"
# ===================================================================

# Cluster exists and is ACTIVE
CLUSTER_STATUS=$(aws eks describe-cluster --name "$CLUSTER_NAME" --region "$REGION" --query 'cluster.status' --output text 2>/dev/null || echo "NOT_FOUND")
if [[ "$CLUSTER_STATUS" == "ACTIVE" ]]; then
    pass "Cluster '$CLUSTER_NAME' is ACTIVE"
else
    fail "Cluster status: $CLUSTER_STATUS"
fi

# K8s API reachable
if kubectl cluster-info &>/dev/null; then
    pass "Kubernetes API reachable"
else
    fail "Cannot reach Kubernetes API"
    exit 1
fi

# Nodes
TOTAL_NODES=$(kubectl get nodes --no-headers 2>/dev/null | wc -l | tr -d ' ')
READY_NODES=$(kubectl get nodes --no-headers 2>/dev/null | grep -c ' Ready ' || true)
if [[ $READY_NODES -ge 4 ]]; then
    pass "Nodes: $READY_NODES/$TOTAL_NODES Ready"
else
    warn "Nodes: $READY_NODES/$TOTAL_NODES Ready (expected ≥4)"
fi

# Node groups
WORKLOAD_NODES=$(kubectl get nodes -l role=workload --no-headers 2>/dev/null | grep -c ' Ready ' || true)
MONITORING_NODES=$(kubectl get nodes -l role=monitoring --no-headers 2>/dev/null | grep -c ' Ready ' || true)
[[ $WORKLOAD_NODES -ge 2 ]] && pass "Workload nodes: $WORKLOAD_NODES Ready" || warn "Workload nodes: $WORKLOAD_NODES Ready (expected ≥2)"
[[ $MONITORING_NODES -ge 2 ]] && pass "Monitoring nodes: $MONITORING_NODES Ready" || warn "Monitoring nodes: $MONITORING_NODES Ready (expected 2)"

# Addons
for addon in vpc-cni coredns kube-proxy aws-ebs-csi-driver; do
    STATUS=$(aws eks describe-addon --cluster-name "$CLUSTER_NAME" --addon-name "$addon" --region "$REGION" --query 'addon.status' --output text 2>/dev/null || echo "MISSING")
    [[ "$STATUS" == "ACTIVE" ]] && pass "Addon $addon: ACTIVE" || warn "Addon $addon: $STATUS"
done

# ===================================================================
header "2. Online Boutique (online-boutique namespace)"
# ===================================================================

EXPECTED_SERVICES="adservice cartservice checkoutservice currencyservice emailservice frontend loadgenerator paymentservice productcatalogservice recommendationservice redis-cart shippingservice"

OB_RUNNING=$(kubectl get pods -n online-boutique --no-headers --field-selector=status.phase=Running 2>/dev/null | grep -cv 'Terminating' || true)
if [[ $OB_RUNNING -ge 11 ]]; then
    pass "Pods running: $OB_RUNNING (expected ≥11)"
else
    fail "Pods running: $OB_RUNNING (expected ≥11)"
fi

# Check each deployment
for svc in $EXPECTED_SERVICES; do
    READY=$(kubectl get deploy "$svc" -n online-boutique -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
    READY=${READY:-0}
    [[ $READY -ge 1 ]] && pass "$svc: $READY replica(s) ready" || fail "$svc: not ready"
done

# Frontend Service (ClusterIP — access via port-forward)
FRONTEND_TYPE=$(kubectl get svc frontend -n online-boutique -o jsonpath='{.spec.type}' 2>/dev/null || echo "")
if [[ "$FRONTEND_TYPE" == "ClusterIP" ]]; then
    pass "Frontend: ClusterIP (internal only, access via kubectl port-forward)"
elif [[ -n "$FRONTEND_TYPE" ]]; then
    warn "Frontend: $FRONTEND_TYPE (expected ClusterIP for internal-only access)"
else
    warn "Frontend service: not found"
fi

# ===================================================================
header "3. Monitoring Stack (monitoring namespace)"
# ===================================================================

# Prometheus
PROM_READY=$(kubectl get statefulset prometheus-prometheus-kube-prometheus-prometheus -n monitoring -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
[[ "${PROM_READY:-0}" -ge 1 ]] && pass "Prometheus: $PROM_READY replica(s) ready" || fail "Prometheus: not ready"

# Grafana
GRAFANA_READY=$(kubectl get deploy prometheus-grafana -n monitoring -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
[[ "${GRAFANA_READY:-0}" -ge 1 ]] && pass "Grafana: $GRAFANA_READY replica(s) ready" || fail "Grafana: not ready"

GRAFANA_TYPE=$(kubectl get svc prometheus-grafana -n monitoring -o jsonpath='{.spec.type}' 2>/dev/null || echo "")
if [[ "$GRAFANA_TYPE" == "ClusterIP" ]]; then
    pass "Grafana: ClusterIP (internal only, access via kubectl port-forward :3000)"
elif [[ -n "$GRAFANA_TYPE" ]]; then
    warn "Grafana: $GRAFANA_TYPE (expected ClusterIP for internal-only access)"
else
    warn "Grafana service: not found"
fi

# Alertmanager
AM_READY=$(kubectl get statefulset alertmanager-prometheus-kube-prometheus-alertmanager -n monitoring -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
[[ "${AM_READY:-0}" -ge 1 ]] && pass "Alertmanager: $AM_READY replica(s) ready" || warn "Alertmanager: not ready"

# Kube-state-metrics
KSM_READY=$(kubectl get deploy prometheus-kube-state-metrics -n monitoring -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
[[ "${KSM_READY:-0}" -ge 1 ]] && pass "Kube-state-metrics: ready" || fail "Kube-state-metrics: not ready"

# Node exporter (DaemonSet)
NE_DESIRED=$(kubectl get ds prometheus-prometheus-node-exporter -n monitoring -o jsonpath='{.status.desiredNumberScheduled}' 2>/dev/null || echo "0")
NE_READY=$(kubectl get ds prometheus-prometheus-node-exporter -n monitoring -o jsonpath='{.status.numberReady}' 2>/dev/null || echo "0")
[[ "$NE_READY" == "$NE_DESIRED" ]] && pass "Node exporter: $NE_READY/$NE_DESIRED ready" || warn "Node exporter: $NE_READY/$NE_DESIRED ready"

# OTEL Collector
OTEL_READY=$(kubectl get deploy otel-collector-opentelemetry-collector -n monitoring -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
[[ "${OTEL_READY:-0}" -ge 1 ]] && pass "OTEL Collector: ready" || fail "OTEL Collector: not ready"

# ===================================================================
header "4. Chaos Testing (chaos-testing namespace)"
# ===================================================================

LITMUS_FRONTEND=$(kubectl get deploy litmus-frontend -n chaos-testing -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
LITMUS_SERVER=$(kubectl get deploy litmus-server -n chaos-testing -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
LITMUS_AUTH=$(kubectl get deploy litmus-auth-server -n chaos-testing -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")

[[ "${LITMUS_FRONTEND:-0}" -ge 1 ]] && pass "Litmus Frontend: ready" || fail "Litmus Frontend: not ready"
[[ "${LITMUS_SERVER:-0}" -ge 1 ]] && pass "Litmus Server: ready" || fail "Litmus Server: not ready"
[[ "${LITMUS_AUTH:-0}" -ge 1 ]] && pass "Litmus Auth: ready" || fail "Litmus Auth: not ready"

MONGO_READY=$(kubectl get statefulset litmus-mongodb -n chaos-testing -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
[[ "${MONGO_READY:-0}" -ge 1 ]] && pass "MongoDB: $MONGO_READY replica(s) ready" || fail "MongoDB: not ready"

LITMUS_TYPE=$(kubectl get svc litmus-frontend-service -n chaos-testing -o jsonpath='{.spec.type}' 2>/dev/null || echo "")
if [[ "$LITMUS_TYPE" == "ClusterIP" ]]; then
    pass "LitmusChaos: ClusterIP (internal only, access via kubectl port-forward :9091)"
elif [[ -n "$LITMUS_TYPE" ]]; then
    warn "LitmusChaos: $LITMUS_TYPE (expected ClusterIP for internal-only access)"
else
    warn "LitmusChaos service: not found"
fi

# ===================================================================
header "5. Storage"
# ===================================================================

PVC_TOTAL=$(kubectl get pvc -A --no-headers 2>/dev/null | wc -l | tr -d ' ')
PVC_BOUND=$(kubectl get pvc -A --no-headers 2>/dev/null | grep -c 'Bound' || true)
[[ "$PVC_BOUND" == "$PVC_TOTAL" ]] && pass "PVCs: $PVC_BOUND/$PVC_TOTAL Bound" || warn "PVCs: $PVC_BOUND/$PVC_TOTAL Bound"

kubectl get pvc -A --no-headers 2>/dev/null | while read -r ns name status vol cap mode sc _rest; do
    if [[ "$status" == "Bound" ]]; then
        info "  $ns/$name — $cap ($sc)"
    else
        warn "  $ns/$name — $status"
    fi
done

# ===================================================================
if [[ "$QUICK" == "--quick" ]]; then
    header "6. Metrics Flow (skipped — use without --quick for full check)"
else
    header "6. Metrics Flow"

    # Port-forward Prometheus (background, auto-cleanup)
    PROM_PF_PID=""
    cleanup_pf() { [[ -n "$PROM_PF_PID" ]] && kill "$PROM_PF_PID" 2>/dev/null || true; }
    trap cleanup_pf EXIT

    kubectl port-forward svc/prometheus-kube-prometheus-prometheus -n monitoring 19090:9090 &>/dev/null &
    PROM_PF_PID=$!
    sleep 3

    prom_query() {
        local query="$1"
        curl -s -G 'http://localhost:19090/api/v1/query' --data-urlencode "query=$query" 2>/dev/null
    }

    # TSDB stats
    TSDB=$(curl -s 'http://localhost:19090/api/v1/status/tsdb' 2>/dev/null)
    SERIES=$(echo "$TSDB" | python3 -c "import json,sys; print(json.load(sys.stdin)['data']['headStats']['numSeries'])" 2>/dev/null || echo "0")
    if [[ "$SERIES" -gt 1000 ]]; then
        pass "Prometheus TSDB: $SERIES active series"
    else
        fail "Prometheus TSDB: only $SERIES series (expected >1000)"
    fi

    # Scrape targets
    TARGETS_JSON=$(curl -s 'http://localhost:19090/api/v1/targets' 2>/dev/null)
    TARGETS_UP=$(echo "$TARGETS_JSON" | python3 -c "
import json, sys
d = json.load(sys.stdin)
targets = d.get('data', {}).get('activeTargets', [])
up = sum(1 for t in targets if t['health'] == 'up')
print(f'{up}/{len(targets)}')
" 2>/dev/null || echo "?/?")
    pass "Scrape targets: $TARGETS_UP up"

    # Key metric families
    for metric_check in \
        "node_cpu_seconds_total|Node CPU" \
        "node_memory_MemTotal_bytes|Node Memory" \
        "kube_pod_info|K8s Pod Info" \
        "kube_deployment_status_replicas|K8s Deployments" \
        "container_cpu_usage_seconds_total|Container CPU" \
        "container_memory_working_set_bytes|Container Memory"; do
        METRIC="${metric_check%%|*}"
        LABEL="${metric_check##*|}"
        COUNT=$(prom_query "count($METRIC)" | python3 -c "import json,sys; r=json.load(sys.stdin)['data']['result']; print(r[0]['value'][1] if r else '0')" 2>/dev/null || echo "0")
        if [[ "$COUNT" -gt 0 ]]; then
            pass "$LABEL: $COUNT series"
        else
            fail "$LABEL: no data"
        fi
    done

    # Online Boutique container metrics specifically
    OB_MEM=$(prom_query 'count(container_memory_working_set_bytes{namespace="online-boutique"})' | python3 -c "import json,sys; r=json.load(sys.stdin)['data']['result']; print(r[0]['value'][1] if r else '0')" 2>/dev/null || echo "0")
    [[ "$OB_MEM" -gt 0 ]] && pass "Online Boutique memory metrics: $OB_MEM series" || warn "Online Boutique memory metrics: no data yet"

    # Grafana datasource connectivity
    GRAFANA_HEALTH=$(curl -s -u admin:agenticops-lab 'http://localhost:3000/api/health' 2>/dev/null || echo "{}")
    GRAFANA_DB=$(echo "$GRAFANA_HEALTH" | python3 -c "import json,sys; print(json.load(sys.stdin).get('database','?'))" 2>/dev/null || echo "?")
    if [[ "$GRAFANA_DB" == "ok" ]]; then
        pass "Grafana database: ok"
    else
        # Grafana might not be port-forwarded; try via its API
        warn "Grafana health check: $GRAFANA_DB (port-forward Grafana to check)"
    fi

    # Dashboard count
    DASH_COUNT=$(curl -s -u admin:agenticops-lab 'http://localhost:3000/api/search?type=dash-db' 2>/dev/null | python3 -c "import json,sys; print(len(json.load(sys.stdin)))" 2>/dev/null || echo "0")
    [[ "$DASH_COUNT" -gt 0 ]] && pass "Grafana dashboards: $DASH_COUNT available" || info "Grafana dashboards: port-forward to :3000 to check"

    cleanup_pf
    PROM_PF_PID=""
fi

# ===================================================================
header "7. SSM Access"
# ===================================================================

readarray -t INSTANCE_IDS < <(aws ec2 describe-instances --region "$REGION" \
    --filters "Name=tag:eks:cluster-name,Values=$CLUSTER_NAME" "Name=instance-state-name,Values=running" \
    --query 'Reservations[*].Instances[*].InstanceId' --output text 2>/dev/null | tr '\t' '\n' | grep -v '^$')

if [[ ${#INSTANCE_IDS[@]} -gt 0 ]]; then
    pass "EC2 instances: ${#INSTANCE_IDS[@]} running"

    # Check SSM agent status on first instance
    FIRST_INSTANCE="${INSTANCE_IDS[0]}"
    SSM_STATUS=$(aws ssm describe-instance-information --region "$REGION" \
        --filters "Key=InstanceIds,Values=$FIRST_INSTANCE" \
        --query 'InstanceInformationList[0].PingStatus' --output text 2>/dev/null || echo "Unknown")
    [[ "$SSM_STATUS" == "Online" ]] && pass "SSM agent on $FIRST_INSTANCE: Online" || warn "SSM agent on $FIRST_INSTANCE: $SSM_STATUS"
else
    warn "No running EC2 instances found for cluster"
fi

# ===================================================================
header "8. Access URLs"
# ===================================================================

echo ""
info "All services are ClusterIP (internal only). Access via kubectl port-forward + SSH tunnel:"
echo ""
info "Online Boutique:  kubectl port-forward svc/frontend -n online-boutique 8080:80"
info "Grafana:          kubectl port-forward svc/prometheus-grafana -n monitoring 3000:80  (admin / agenticops-lab)"
info "LitmusChaos:      kubectl port-forward svc/litmus-frontend-service -n chaos-testing 9091:9091  (admin / litmus)"
info "Prometheus:       kubectl port-forward svc/prometheus-kube-prometheus-prometheus -n monitoring 9090:9090"
info "Alertmanager:     kubectl port-forward svc/prometheus-kube-prometheus-alertmanager -n monitoring 9093:9093"
echo ""
info "SSH tunnel:       ssh -L 3000:localhost:3000 -L 8080:localhost:8080 -L 9090:localhost:9090 ubuntu@<bastion>"
info "Kubeconfig:       export KUBECONFIG=$KUBECONFIG_PATH"
echo ""

# ===================================================================
# Summary
# ===================================================================
echo ""
if [[ $FAILURES -eq 0 ]]; then
    echo -e "${GREEN}${BOLD}All checks passed.${NC}"
else
    echo -e "${RED}${BOLD}$FAILURES check(s) failed.${NC}"
    exit 1
fi
