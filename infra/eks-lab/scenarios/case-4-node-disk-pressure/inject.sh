#!/usr/bin/env bash
# Case 4: Node DiskPressure → NodeNotReady
# Inject: Deploy disk-filler pod that writes 70G to hostPath on workload node
# Expected: NodeDiskPressure alert (~1 min), NodeNotReady (~2 min)
# NOTE: Uses hostPath so data persists even if kubelet evicts the pod

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../common.sh"

echo -e "\n${BOLD}=== Case 4: Node DiskPressure ===${NC}\n"

# Verify workload node exists
WORKLOAD_NODE=$(kubectl get nodes -l role=workload -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")
if [[ -z "$WORKLOAD_NODE" ]]; then
    # Fall back to any non-master node
    WORKLOAD_NODE=$(kubectl get nodes --no-headers | grep -v "control-plane\|master" | head -1 | awk '{print $1}')
fi
report_info "Target workload node: ${WORKLOAD_NODE}"
echo "$WORKLOAD_NODE" > /tmp/case4-target-node.txt

# Inject: deploy disk-filler pod (hostPath — survives eviction)
report_info "Deploying disk-filler pod on node ${WORKLOAD_NODE} (hostPath /var/chaos-disk-fill)..."
kubectl apply -f "${SCRIPT_DIR}/disk-filler.yaml"
kubectl wait --for=condition=Ready pod/agenticops-disk-filler -n online-boutique --timeout=60s 2>/dev/null || true

# Wait until disk is actually filled
report_info "Waiting for disk fill to complete..."
for i in $(seq 1 12); do
    FILL_LOG=$(kubectl logs agenticops-disk-filler -n online-boutique --tail=1 2>/dev/null || echo "")
    if [[ "$FILL_LOG" == *"complete"* ]]; then
        break
    fi
    sleep 5
done

report_pass "Fault injected — disk-filler pod deployed with hostPath (will fill 70G on ${WORKLOAD_NODE})"
report_info "Expected alerts: NodeDiskPressure (~1 min), NodeNotReady (~2 min)"
report_info "NOTE: hostPath data persists after pod eviction — node stays in DiskPressure"
