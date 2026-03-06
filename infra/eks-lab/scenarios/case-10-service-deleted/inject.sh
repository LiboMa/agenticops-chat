#!/usr/bin/env bash
# Case 10: Service Crash → 5xx Surge
# Inject: Patch cartservice with invalid command so it crash-loops
# Expected: KubePodCrashLooping (~1 min), KubeDeploymentReplicasMismatch (~5 min)
# The agent must identify the broken command and rollback or fix the deployment

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../common.sh"

echo -e "\n${BOLD}=== Case 10: Service Crash (cartservice) ===${NC}\n"

# Save current cartservice revision for rollback reference
CURRENT_IMAGE=$(kubectl get deploy cartservice -n online-boutique \
    -o jsonpath='{.spec.template.spec.containers[0].image}' 2>/dev/null || echo "unknown")
CURRENT_REPLICAS=$(kubectl get deploy cartservice -n online-boutique \
    -o jsonpath='{.spec.replicas}' 2>/dev/null || echo "1")
echo "${CURRENT_IMAGE}|${CURRENT_REPLICAS}" > /tmp/case10-original-cartservice.txt
report_info "Original cartservice: image=${CURRENT_IMAGE}, replicas=${CURRENT_REPLICAS}"

# Inject: patch cartservice with a command that immediately exits with error
report_info "Patching cartservice with invalid command (will crash-loop)..."
kubectl patch deploy cartservice -n online-boutique --type=json \
    -p='[{"op":"add","path":"/spec/template/spec/containers/0/command","value":["sh","-c","echo CRASH_INJECTED; exit 1"]}]'

# Verify the pod is crash-looping
sleep 15
POD_STATUS=$(kubectl get pods -l app=cartservice -n online-boutique --no-headers 2>/dev/null | head -1 | awk '{print $3}')
if [[ "$POD_STATUS" == *"Error"* || "$POD_STATUS" == *"CrashLoop"* || "$POD_STATUS" == *"Init"* ]]; then
    report_pass "Fault injected — cartservice pod is ${POD_STATUS}"
else
    report_info "cartservice pod status: ${POD_STATUS} (crash-loop may take a moment)"
fi

report_info "Expected alerts: KubePodCrashLooping (~1 min), KubeDeploymentReplicasMismatch (~5 min)"
