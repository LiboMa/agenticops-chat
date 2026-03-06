#!/usr/bin/env bash
# Case 3: Redis Dependency Failure → cartservice degraded
# Inject: Patch redis-cart with invalid command (crash-loop)
# Expected: KubePodCrashLooping (~1 min), KubeDeploymentReplicasMismatch (~5 min)
# The agent must identify redis-cart is crash-looping and rollback

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../common.sh"

echo -e "\n${BOLD}=== Case 3: Redis Dependency Failure ===${NC}\n"

# Verify redis-cart and cartservice are healthy before injection
REDIS_READY=$(kubectl get deploy redis-cart -n online-boutique \
    -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
CART_READY=$(kubectl get deploy cartservice -n online-boutique \
    -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
report_info "Before injection: redis-cart=${REDIS_READY:-0} ready, cartservice=${CART_READY:-0} ready"

# Inject: patch redis-cart with a command that crashes
report_info "Patching redis-cart with invalid command (will crash-loop)..."
kubectl patch deploy redis-cart -n online-boutique --type=json \
    -p='[{"op":"add","path":"/spec/template/spec/containers/0/command","value":["sh","-c","echo REDIS_CRASH_INJECTED; exit 1"]}]'

# Verify the pod is crash-looping
sleep 15
POD_STATUS=$(kubectl get pods -l app=redis-cart -n online-boutique --no-headers 2>/dev/null | head -1 | awk '{print $3}')
if [[ "$POD_STATUS" == *"Error"* || "$POD_STATUS" == *"CrashLoop"* ]]; then
    report_pass "Fault injected — redis-cart pod is ${POD_STATUS}"
else
    report_info "redis-cart pod status: ${POD_STATUS} (crash-loop may take a moment)"
fi

report_info "Expected alerts: KubePodCrashLooping (~1 min), KubeDeploymentReplicasMismatch (~5 min)"
report_info "Impact: cartservice cannot access Redis → cart operations will fail"
