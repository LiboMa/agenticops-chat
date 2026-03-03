#!/usr/bin/env bash
# Case Cross-Service: Redis Latency → Cascading 5xx
# Inject: Starve redis-cart of CPU/memory → slow responses → cascade to frontend
# Expected: HighErrorRate alert on frontend, trace shows redis-cart as root cause
#
# Call chain affected:
#   frontend → checkoutservice → cartservice → redis-cart (throttled!) ← ROOT CAUSE
#   frontend → checkoutservice → productcatalogservice (unaffected)
#   frontend → currencyservice (unaffected)

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../common.sh"

echo -e "\n${BOLD}=== Case Cross-Service: Redis Latency Cascade ===${NC}\n"

# Save current resource limits for restoration
CURRENT_CPU=$(kubectl get deploy redis-cart -n online-boutique \
    -o jsonpath='{.spec.template.spec.containers[0].resources.limits.cpu}' 2>/dev/null || echo "unknown")
CURRENT_MEM=$(kubectl get deploy redis-cart -n online-boutique \
    -o jsonpath='{.spec.template.spec.containers[0].resources.limits.memory}' 2>/dev/null || echo "unknown")
echo "${CURRENT_CPU}|${CURRENT_MEM}" > /tmp/case-cross-service-original-resources.txt
report_info "Original redis-cart resources: cpu=${CURRENT_CPU}, memory=${CURRENT_MEM}"

# Inject: set redis-cart to extremely limited resources
# CPU=10m + memory=16Mi makes Redis severely throttled → slow responses → cascade
report_info "Setting redis-cart resources: cpu=10m memory=16Mi (starvation)..."
kubectl set resources deploy/redis-cart -n online-boutique \
    --requests=cpu=10m,memory=16Mi --limits=cpu=10m,memory=16Mi
kubectl rollout status deploy/redis-cart -n online-boutique --timeout=60s 2>/dev/null || true

report_pass "Fault injected — redis-cart cpu=10m memory=16Mi (was cpu=${CURRENT_CPU} memory=${CURRENT_MEM})"
report_info "Expected: HighErrorRate on frontend (5xx > 5%, ~3 min), HighLatencyP99 (p99 > 2s)"
report_info "Expected trace chain: frontend → checkoutservice → cartservice → redis-cart (TIMEOUT)"
