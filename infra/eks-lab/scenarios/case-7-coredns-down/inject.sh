#!/usr/bin/env bash
# Case 7: CoreDNS Failure
# Inject: Scale CoreDNS deployment to 0 replicas
# Expected: KubeCoreDNSDown alert (~1 min)
#
# NOTE: EKS addon controller may self-recover CoreDNS. The verify script
# accepts both agent-driven fix and EKS self-recovery outcomes.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../common.sh"

echo -e "\n${BOLD}=== Case 7: CoreDNS Failure ===${NC}\n"

# Save current CoreDNS replica count
CURRENT_REPLICAS=$(kubectl get deploy coredns -n kube-system \
    -o jsonpath='{.spec.replicas}' 2>/dev/null || echo "2")
echo "$CURRENT_REPLICAS" > /tmp/case7-original-replicas.txt
report_info "Original CoreDNS replicas: ${CURRENT_REPLICAS}"

# Inject: scale CoreDNS to 0
report_info "Scaling CoreDNS to 0 replicas..."
kubectl scale deploy/coredns -n kube-system --replicas=0

# Verify CoreDNS pods are gone
sleep 5
REMAINING=$(kubectl get pods -n kube-system -l k8s-app=kube-dns --no-headers 2>/dev/null | wc -l | tr -d ' ')
report_info "CoreDNS pods remaining: ${REMAINING}"

report_pass "Fault injected — CoreDNS scaled to 0 (was ${CURRENT_REPLICAS})"
report_info "Expected alerts: KubeCoreDNSDown (~1 min)"
report_info "NOTE: EKS addon controller may self-recover — verify accepts both outcomes"
