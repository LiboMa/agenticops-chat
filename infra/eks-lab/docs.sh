#!/usr/bin/env bash
# AgenticOps EKS Lab — Quick reference and operational runbook
# Usage: ./docs.sh [section]
#
# Sections: all, urls, kubectl, ssm, grafana, chaos, agenticops, costs, troubleshooting
# No args = show all sections

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KUBECONFIG_PATH="${SCRIPT_DIR}/kubeconfig"
CLUSTER_NAME="agenticops-lab"
REGION="us-west-2"

BOLD='\033[1m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
DIM='\033[2m'
NC='\033[0m'

section() { echo -e "\n${BOLD}━━━ $* ━━━${NC}\n"; }
cmd()     { echo -e "  ${CYAN}\$${NC} $*"; }
note()    { echo -e "  ${DIM}# $*${NC}"; }
blank()   { echo ""; }

SECTION="${1:-all}"

# ===================================================================
show_urls() {
    section "Access URLs"

    if [[ -f "$KUBECONFIG_PATH" ]]; then
        export KUBECONFIG="$KUBECONFIG_PATH"

        FRONTEND=$(kubectl get svc frontend-external -n online-boutique -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || echo "<pending>")
        GRAFANA=$(kubectl get svc prometheus-grafana -n monitoring -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || echo "<pending>")
        LITMUS=$(kubectl get svc litmus-frontend-service -n chaos-testing -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || echo "<pending>")

        echo -e "  Online Boutique:  ${BLUE}http://$FRONTEND${NC}"
        echo -e "  Grafana:          ${BLUE}http://$GRAFANA${NC}  (admin / agenticops-lab)"
        echo -e "  LitmusChaos:      ${BLUE}http://$LITMUS${NC}  (admin / litmus)"
    else
        echo "  (kubeconfig not found — run setup.sh first)"
    fi

    blank
    echo "  If URLs show <pending>, LoadBalancers are still provisioning."
    cmd "kubectl get svc -A | grep LoadBalancer"
}

# ===================================================================
show_kubectl() {
    section "kubectl Commands"

    note "Set kubeconfig"
    cmd "export KUBECONFIG=$KUBECONFIG_PATH"
    blank

    note "Cluster overview"
    cmd "kubectl get nodes -o wide"
    cmd "kubectl get pods -A"
    cmd "kubectl top nodes"
    cmd "kubectl top pods -n online-boutique"
    blank

    note "Online Boutique"
    cmd "kubectl get pods -n online-boutique"
    cmd "kubectl get svc -n online-boutique"
    cmd "kubectl logs deploy/frontend -n online-boutique --tail=50"
    cmd "kubectl logs deploy/loadgenerator -n online-boutique --tail=20"
    cmd "kubectl exec -it deploy/frontend -n online-boutique -- sh"
    blank

    note "Monitoring"
    cmd "kubectl get pods -n monitoring"
    cmd "kubectl logs -n monitoring -l app.kubernetes.io/name=opentelemetry-collector --tail=30"
    cmd "kubectl port-forward svc/prometheus-kube-prometheus-prometheus -n monitoring 9090:9090"
    cmd "kubectl port-forward svc/prometheus-grafana -n monitoring 3000:80"
    blank

    note "Chaos testing"
    cmd "kubectl get pods -n chaos-testing"
    cmd "kubectl get chaosexperiments -n online-boutique 2>/dev/null || echo 'No experiments yet'"
    blank

    note "Debugging"
    cmd "kubectl describe pod <pod-name> -n <namespace>"
    cmd "kubectl get events -n <namespace> --sort-by='.lastTimestamp'"
    cmd "kubectl get pvc -A"
    cmd "kubectl get sc"
}

# ===================================================================
show_ssm() {
    section "SSM / SSH Access"

    note "List cluster node instance IDs"
    cmd "aws ec2 describe-instances --region $REGION \\"
    cmd "  --filters 'Name=tag:eks:cluster-name,Values=$CLUSTER_NAME' 'Name=instance-state-name,Values=running' \\"
    cmd "  --query 'Reservations[*].Instances[*].[InstanceId,PrivateIpAddress,Tags[?Key==\`eks:nodegroup-name\`].Value|[0]]' \\"
    cmd "  --output table"
    blank

    note "Start SSM session to a node"
    cmd "aws ssm start-session --target <instance-id> --region $REGION"
    blank

    note "Run a command via SSM (non-interactive)"
    cmd "aws ssm send-command --region $REGION \\"
    cmd "  --instance-ids <instance-id> \\"
    cmd "  --document-name 'AWS-RunShellScript' \\"
    cmd "  --parameters 'commands=[\"uptime\",\"df -h\",\"free -m\"]' \\"
    cmd "  --output text --query 'Command.CommandId'"
    blank

    note "Get SSM command output"
    cmd "aws ssm get-command-invocation --region $REGION \\"
    cmd "  --command-id <command-id> --instance-id <instance-id> \\"
    cmd "  --query '[StandardOutputContent,StandardErrorContent]' --output text"
    blank

    note "SSH (if key pair configured)"
    cmd "ssh -i ~/.ssh/sa-malibo.pem ec2-user@<node-external-ip>"
}

# ===================================================================
show_grafana() {
    section "Grafana Dashboards"

    echo "  28 pre-installed dashboards from kube-prometheus-stack:"
    blank
    echo "  Compute Resources:"
    echo "    - Kubernetes / Compute Resources / Cluster"
    echo "    - Kubernetes / Compute Resources / Namespace (Pods)"
    echo "    - Kubernetes / Compute Resources / Namespace (Workloads)"
    echo "    - Kubernetes / Compute Resources / Node (Pods)"
    echo "    - Kubernetes / Compute Resources / Pod"
    echo "    - Kubernetes / Compute Resources / Workload"
    blank
    echo "  Networking:"
    echo "    - Kubernetes / Networking / Cluster"
    echo "    - Kubernetes / Networking / Namespace (Pods)"
    echo "    - Kubernetes / Networking / Pod"
    blank
    echo "  Infrastructure:"
    echo "    - Kubernetes / API server"
    echo "    - Kubernetes / Controller Manager"
    echo "    - Kubernetes / Kubelet"
    echo "    - Kubernetes / Persistent Volumes"
    echo "    - Kubernetes / Proxy"
    echo "    - Kubernetes / Scheduler"
    echo "    - CoreDNS"
    echo "    - Node Exporter / Nodes"
    echo "    - Alertmanager / Overview"
    blank

    note "Port-forward and open locally"
    cmd "kubectl port-forward svc/prometheus-grafana -n monitoring 3000:80"
    echo "  Then open http://localhost:3000 (admin / agenticops-lab)"
    blank

    note "Useful Prometheus queries (via Grafana Explore or port-forward :9090)"
    cmd "# Cluster CPU usage by namespace"
    echo '  sum(rate(container_cpu_usage_seconds_total{container!=""}[5m])) by (namespace)'
    blank
    cmd "# Online Boutique memory per service"
    echo '  sum(container_memory_working_set_bytes{namespace="online-boutique",container!=""}) by (container)'
    blank
    cmd "# Request rate to frontend"
    echo '  rate(http_server_request_count_total{app="frontend"}[5m])'
    blank
    cmd "# Pod restart count"
    echo '  kube_pod_container_status_restarts_total{namespace="online-boutique"}'
    blank
    cmd "# Node disk usage"
    echo '  1 - (node_filesystem_avail_bytes / node_filesystem_size_bytes)'
}

# ===================================================================
show_chaos() {
    section "Chaos Engineering (LitmusChaos)"

    echo "  LitmusChaos ChaosCenter is deployed with:"
    echo "    - Frontend (web UI)"
    echo "    - Server (API)"
    echo "    - Auth server"
    echo "    - MongoDB 3-node replicaset"
    blank

    note "Access ChaosCenter"
    echo "  Open the LitmusChaos URL (see ./docs.sh urls)"
    echo "  Default credentials: admin / litmus"
    blank

    note "Quick chaos experiments to try"
    blank
    echo "  1. Pod Delete — kill a random Online Boutique pod:"
    echo "     ChaosCenter → New Experiment → Select online-boutique namespace"
    echo "     → pod-delete → Target: app=cartservice → Run"
    blank
    echo "  2. Network Loss — inject packet loss on frontend:"
    echo "     → pod-network-loss → Target: app=frontend"
    echo "     → NETWORK_PACKET_LOSS_PERCENTAGE=50 → Run"
    blank
    echo "  3. Node Drain — drain a workload node:"
    echo "     → node-drain → Target: a workload node → Run"
    echo "     Watch: kubectl get pods -n online-boutique -w"
    blank

    note "Monitor during chaos"
    cmd "kubectl get pods -n online-boutique -w"
    cmd "kubectl get events -n online-boutique --sort-by='.lastTimestamp' -w"
    echo "  Open Grafana → K8s Compute Resources / Namespace → online-boutique"
}

# ===================================================================
show_agenticops() {
    section "AgenticOps Integration Testing"

    note "Set up environment"
    cmd "export KUBECONFIG=$KUBECONFIG_PATH"
    blank

    note "Test kubectl tools"
    cmd "aiops chat 'check health of agenticops-lab cluster in us-west-2'"
    cmd "aiops chat 'list all pods in online-boutique namespace'"
    cmd "aiops chat 'show resource usage for the online-boutique workloads'"
    blank

    note "Test SSM tools"
    cmd "aiops chat 'check disk space on the EKS nodes in agenticops-lab'"
    cmd "aiops chat 'run uptime on the workload nodes via SSM'"
    blank

    note "Test AWS CLI tools"
    cmd "aiops chat 'describe the agenticops-lab EKS cluster'"
    cmd "aiops chat 'list CloudWatch alarms for the agenticops-lab cluster'"
    blank

    note "Test detection / RCA"
    cmd "aiops chat 'detect health issues in the agenticops-lab cluster'"
    cmd "aiops chat 'run RCA on any anomalies in online-boutique'"
    blank

    note "Test with chaos (run chaos experiment first)"
    echo "  1. Start a pod-delete chaos experiment on cartservice"
    echo "  2. Wait 30 seconds for detection"
    cmd "aiops chat 'detect issues in online-boutique and investigate any failures'"
    blank

    note "Test graph/topology tools"
    cmd "aiops chat 'show network topology for the agenticops-lab VPC'"
    cmd "aiops chat 'find single points of failure in the agenticops-lab infrastructure'"
    blank

    note "Test skills"
    cmd "aiops chat 'activate the kubernetes-admin skill and check pod health in online-boutique'"
    cmd "aiops chat 'activate linux-admin skill and check memory usage on the EKS nodes'"
}

# ===================================================================
show_costs() {
    section "Cost Estimate & Resource Cleanup"

    echo "  Running resources and estimated hourly cost (us-west-2):"
    blank
    echo "    EKS Control Plane:      \$0.10/hr"
    echo "    m5.large × 3 (workload): \$0.288/hr  (\$0.096 each)"
    echo "    m5.large × 2 (monitor):  \$0.192/hr"
    echo "    EBS gp3 volumes (~170GB): ~\$0.014/hr"
    echo "    NLB × 3 (frontend/grafana/litmus): ~\$0.054/hr"
    echo "    CloudWatch logs:         ~\$0.02/hr"
    echo "    NAT Gateway (if used):   \$0.045/hr + data"
    echo "    ────────────────────────────────────"
    echo "    Approximate total:       ~\$0.72/hr ≈ \$17/day"
    blank

    note "Pause the cluster (scale node groups to 0)"
    cmd "eksctl scale nodegroup --cluster $CLUSTER_NAME --name workload --nodes 0 --nodes-min 0 --region $REGION"
    cmd "eksctl scale nodegroup --cluster $CLUSTER_NAME --name monitoring --nodes 0 --nodes-min 0 --region $REGION"
    blank

    note "Resume the cluster"
    cmd "eksctl scale nodegroup --cluster $CLUSTER_NAME --name workload --nodes 3 --nodes-min 2 --region $REGION"
    cmd "eksctl scale nodegroup --cluster $CLUSTER_NAME --name monitoring --nodes 2 --nodes-min 2 --region $REGION"
    blank

    note "Full teardown"
    cmd "cd $SCRIPT_DIR && ./teardown.sh"
}

# ===================================================================
show_troubleshooting() {
    section "Troubleshooting"

    echo "  Common issues and fixes:"
    blank

    echo "  ${BOLD}Pods stuck in Pending${NC}"
    cmd "kubectl describe pod <pod> -n <ns>  # check Events section"
    echo "  Usually: insufficient resources, node taints, or PVC not bound"
    blank

    echo "  ${BOLD}PVC stuck in Pending${NC}"
    cmd "kubectl describe pvc <pvc> -n <ns>"
    echo "  Fix: check StorageClass exists (kubectl get sc) and EBS CSI driver is ACTIVE"
    blank

    echo "  ${BOLD}LoadBalancer stuck in <pending>${NC}"
    cmd "kubectl describe svc <svc> -n <ns>  # check Events"
    echo "  Fix: usually takes 1-3 minutes. Check subnet tags and security groups."
    blank

    echo "  ${BOLD}Prometheus targets down${NC}"
    cmd "kubectl port-forward svc/prometheus-kube-prometheus-prometheus -n monitoring 9090:9090"
    echo "  Open http://localhost:9090/targets — check which targets are down"
    echo "  Common: old nodes draining (expected), kube-proxy on new nodes (transient)"
    blank

    echo "  ${BOLD}Nodes NotReady or SchedulingDisabled${NC}"
    cmd "kubectl get nodes"
    cmd "kubectl describe node <node-name>  # check Conditions"
    echo "  If node rotation: wait for new nodes, old ones auto-drain"
    echo "  If all nodes: check EC2 console, security groups, IAM roles"
    blank

    echo "  ${BOLD}OTEL Collector not receiving traces${NC}"
    cmd "kubectl logs -n monitoring -l app.kubernetes.io/name=opentelemetry-collector --tail=50"
    echo "  Check: Online Boutique 2025 release removed built-in OTEL."
    echo "  To add: instrument services with OTEL SDK or use auto-instrumentation."
    blank

    echo "  ${BOLD}LitmusChaos MongoDB not starting${NC}"
    cmd "kubectl get pvc -n chaos-testing"
    cmd "kubectl describe statefulset litmus-mongodb -n chaos-testing"
    echo "  Fix: ensure gp3 StorageClass exists and PVC is Bound"
    blank

    echo "  ${BOLD}Can't connect to cluster${NC}"
    cmd "aws eks update-kubeconfig --name $CLUSTER_NAME --region $REGION --kubeconfig $KUBECONFIG_PATH"
    cmd "kubectl cluster-info"
    echo "  Check: AWS credentials valid, cluster exists, network connectivity"
}

# ===================================================================
# Main
# ===================================================================

echo -e "${BOLD}AgenticOps EKS Lab — Reference Guide${NC}"
echo "Cluster: $CLUSTER_NAME | Region: $REGION"

case "$SECTION" in
    all)
        show_urls
        show_kubectl
        show_ssm
        show_grafana
        show_chaos
        show_agenticops
        show_costs
        show_troubleshooting
        ;;
    urls)            show_urls ;;
    kubectl)         show_kubectl ;;
    ssm)             show_ssm ;;
    grafana)         show_grafana ;;
    chaos)           show_chaos ;;
    agenticops)      show_agenticops ;;
    costs)           show_costs ;;
    troubleshooting) show_troubleshooting ;;
    *)
        echo "Unknown section: $SECTION"
        echo "Usage: ./docs.sh [all|urls|kubectl|ssm|grafana|chaos|agenticops|costs|troubleshooting]"
        exit 1
        ;;
esac

echo ""
