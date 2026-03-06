#!/usr/bin/env bash
# Case 1: OOM Kill → CrashLoopBackOff
# Inject: Set adservice memory limit to 64Mi (normally ~300Mi Java app)
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

# Inject: set memory limit to 64Mi AND force JVM to try 256m heap — guaranteed OOM.
report_info "Setting adservice memory=64Mi + JAVA_TOOL_OPTIONS=-Xmx256m -Xms256m..."
kubectl set resources deploy/adservice -n online-boutique \
    --requests=memory=64Mi --limits=memory=64Mi
kubectl set env deploy/adservice -n online-boutique \
    JAVA_TOOL_OPTIONS="-Xmx256m -Xms256m"
kubectl rollout status deploy/adservice -n online-boutique --timeout=60s 2>/dev/null || true

report_pass "Fault injected — adservice memory=256Mi + JVM heap=256m (was ${CURRENT_LIMIT})"
report_info "Expected alerts: KubePodOOMKilled (immediate), KubePodCrashLooping (~1 min)"
