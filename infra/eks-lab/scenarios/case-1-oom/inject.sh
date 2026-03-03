#!/usr/bin/env bash
# Case 1: OOM Kill → CrashLoopBackOff
# Inject: Set adservice memory limit to 32Mi (normally ~300Mi Java app)
# Expected: KubePodOOMKilled alert (immediate) + KubePodCrashLooping (1 min)

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../common.sh"

echo -e "\n${BOLD}=== Case 1: OOM Kill (adservice) ===${NC}\n"

# Save current memory limit for verification later
CURRENT_LIMIT=$(kubectl get deploy adservice -n online-boutique \
    -o jsonpath='{.spec.template.spec.containers[0].resources.limits.memory}' 2>/dev/null || echo "unknown")
echo "$CURRENT_LIMIT" > /tmp/case1-original-memory.txt
report_info "Original memory limit: ${CURRENT_LIMIT}"

# Inject: set memory limit to 32Mi (OOM guaranteed for Java app)
report_info "Setting adservice memory limit to 32Mi..."
kubectl set resources deploy/adservice -n online-boutique \
    --limits=memory=32Mi
kubectl rollout status deploy/adservice -n online-boutique --timeout=60s 2>/dev/null || true

report_pass "Fault injected — adservice memory=32Mi (was ${CURRENT_LIMIT})"
report_info "Expected alerts: KubePodOOMKilled (immediate), KubePodCrashLooping (~1 min)"
