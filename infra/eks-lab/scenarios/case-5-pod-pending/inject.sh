#!/usr/bin/env bash
# Case 5: Pod Pending (Resource Exhaustion)
# Inject: Deploy 6 stress pods (900m CPU each) → saturate cluster → scale frontend to 5 → Pending
# Expected: KubePodPending alert (~3 min), KubeDeploymentReplicasMismatch (~5 min)

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../common.sh"

echo -e "\n${BOLD}=== Case 5: Pod Pending (Resource Exhaustion) ===${NC}\n"

# Save current frontend replica count
CURRENT_REPLICAS=$(kubectl get deploy frontend -n online-boutique \
    -o jsonpath='{.spec.replicas}' 2>/dev/null || echo "1")
echo "$CURRENT_REPLICAS" > /tmp/case5-original-replicas.txt
report_info "Original frontend replicas: ${CURRENT_REPLICAS}"

# Inject step 1: deploy stress pods to exhaust cluster CPU
report_info "Deploying stress pods (6 x 900m CPU) to exhaust cluster resources..."
kubectl apply -f "${SCRIPT_DIR}/stress-pods.yaml"

# Wait for stress pods to claim resources
sleep 10

# Inject step 2: scale frontend to trigger Pending
report_info "Scaling frontend to 5 replicas (will be Pending due to resource exhaustion)..."
kubectl scale deploy/frontend -n online-boutique --replicas=5

report_pass "Fault injected — 6 stress pods (5400m CPU) + frontend scaled to 5"
report_info "Expected alerts: KubePodPending (~3 min), KubeDeploymentReplicasMismatch (~5 min)"
