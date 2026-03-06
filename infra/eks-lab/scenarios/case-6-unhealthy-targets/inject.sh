#!/usr/bin/env bash
# Case 6: Unhealthy LB Targets
# Inject: Patch checkoutservice readiness probe to unreachable port 19999
# Expected: KubePodNotReady alert (~3 min), TargetDown (~3 min)

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../common.sh"

echo -e "\n${BOLD}=== Case 6: Unhealthy LB Targets (checkoutservice) ===${NC}\n"

# Save current readiness probe for verification later
CURRENT_PROBE=$(kubectl get deploy checkoutservice -n online-boutique \
    -o jsonpath='{.spec.template.spec.containers[0].readinessProbe}' 2>/dev/null || echo "unknown")
report_info "Original readiness probe: ${CURRENT_PROBE}"

# Get current deployment generation for rollback reference
CURRENT_GEN=$(kubectl get deploy checkoutservice -n online-boutique \
    -o jsonpath='{.metadata.generation}' 2>/dev/null || echo "1")
echo "$CURRENT_GEN" > /tmp/case6-original-generation.txt

# Inject: patch readiness probe to point to unreachable port
# Also bump memory request to 128Mi to satisfy LimitRange (min 128Mi per container)
report_info "Patching checkoutservice readiness probe to port 19999 (unreachable)..."
kubectl patch deploy checkoutservice -n online-boutique --type=json -p='[
  {"op":"replace","path":"/spec/template/spec/containers/0/readinessProbe","value":{
    "tcpSocket":{"port":19999},
    "initialDelaySeconds":1,
    "periodSeconds":5,
    "failureThreshold":2
  }},
  {"op":"replace","path":"/spec/template/spec/containers/0/resources/requests/memory","value":"128Mi"}
]'
kubectl rollout status deploy/checkoutservice -n online-boutique --timeout=60s 2>/dev/null || true

report_pass "Fault injected — checkoutservice readiness probe → port 19999"
report_info "Expected alerts: KubePodNotReady (~3 min), TargetDown (~3 min)"
