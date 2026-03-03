#!/usr/bin/env bash
# Case 3: NetworkPolicy blocking → service degraded
# Inject: Apply deny-all NetworkPolicy on cartservice
# Expected: KubePodNotReady alert (~3 min, readiness probe fails)

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../common.sh"

echo -e "\n${BOLD}=== Case 3: NetworkPolicy Blocking (cartservice) ===${NC}\n"

# Verify cartservice is healthy before injection
READY=$(kubectl get deploy cartservice -n online-boutique \
    -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
report_info "cartservice ready replicas before injection: ${READY:-0}"

# Inject: apply deny-all NetworkPolicy
report_info "Applying deny-all NetworkPolicy on cartservice..."
kubectl apply -f "${SCRIPT_DIR}/networkpolicy.yaml"

report_pass "Fault injected — NetworkPolicy agenticops-chaos-deny-cartservice applied"
report_info "Expected alerts: KubePodNotReady (~3 min, readiness probe fails due to blocked ingress)"
