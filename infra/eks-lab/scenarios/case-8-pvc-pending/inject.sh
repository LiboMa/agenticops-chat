#!/usr/bin/env bash
# Case 8: PVC Pending (Wrong StorageClass)
# Inject: Apply PVC with nonexistent StorageClass + consumer Pod
# Expected: KubePVCPending alert (~5 min)

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../common.sh"

echo -e "\n${BOLD}=== Case 8: PVC Pending (Wrong StorageClass) ===${NC}\n"

# Inject: apply PVC with nonexistent StorageClass
report_info "Applying PVC with storageClassName=nonexistent-sc..."
kubectl apply -f "${SCRIPT_DIR}/bad-pvc.yaml"

# Apply consumer pod that references the PVC
report_info "Deploying consumer pod that references the bad PVC..."
kubectl apply -f "${SCRIPT_DIR}/pvc-consumer.yaml"

# Verify PVC is Pending
sleep 5
PVC_STATUS=$(kubectl get pvc agenticops-bad-pvc -n online-boutique \
    -o jsonpath='{.status.phase}' 2>/dev/null || echo "unknown")
report_info "PVC status: ${PVC_STATUS}"

report_pass "Fault injected — PVC agenticops-bad-pvc with storageClassName=nonexistent-sc"
report_info "Expected alerts: KubePVCPending (~5 min)"
