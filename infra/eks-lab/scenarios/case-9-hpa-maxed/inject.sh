#!/usr/bin/env bash
# Case 9: HPA Not Scaling (maxReplicas=1)
# Inject: Create HPA on frontend with maxReplicas=1, then increase load
# Expected: KubeHPAMaxedOut alert (~5 min)

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../common.sh"

echo -e "\n${BOLD}=== Case 9: HPA Not Scaling (maxReplicas=1) ===${NC}\n"

# Check if HPA already exists
EXISTING_HPA=$(kubectl get hpa frontend-hpa -n online-boutique --no-headers 2>/dev/null || echo "")
if [[ -n "$EXISTING_HPA" ]]; then
    report_info "Existing HPA found — deleting before injection..."
    kubectl delete hpa frontend-hpa -n online-boutique 2>/dev/null || true
fi

# Save current loadgenerator replicas
CURRENT_LG_REPLICAS=$(kubectl get deploy loadgenerator -n online-boutique \
    -o jsonpath='{.spec.replicas}' 2>/dev/null || echo "1")
echo "$CURRENT_LG_REPLICAS" > /tmp/case9-original-lg-replicas.txt
report_info "Original loadgenerator replicas: ${CURRENT_LG_REPLICAS}"

# Inject step 1: apply HPA with maxReplicas=1
report_info "Applying HPA on frontend with maxReplicas=1..."
kubectl apply -f "${SCRIPT_DIR}/frontend-hpa.yaml"

# Inject step 2: increase load to trigger HPA saturation
report_info "Scaling loadgenerator to 3 replicas (increase traffic)..."
kubectl scale deploy/loadgenerator -n online-boutique --replicas=3

report_pass "Fault injected — frontend HPA maxReplicas=1 + loadgenerator=3"
report_info "Expected alerts: KubeHPAMaxedOut (~5 min)"
