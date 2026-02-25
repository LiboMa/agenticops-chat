#!/usr/bin/env bash
# Verify that the EKS Chaos Lab is correctly set up for AgenticOps.
# Tests: STS AssumeRole → EKS Describe → CloudWatch alarms → Log groups → kubectl
set -euo pipefail

CLUSTER_NAME="agenticops-chaos-lab"
REGION="us-east-1"
ROLE_NAME="AgenticOpsReadOnlyRole"
NAMESPACE="chaos-lab"
PREFIX="EKS-${CLUSTER_NAME}"

PASS=0
FAIL=0

check() {
    local label="$1"
    shift
    if "$@" &>/dev/null; then
        echo "  [PASS] ${label}"
        ((PASS++))
    else
        echo "  [FAIL] ${label}"
        ((FAIL++))
    fi
}

echo "============================================"
echo "  AgenticOps Integration Verification"
echo "============================================"
echo ""

# Get account ID
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}"

# 1. STS AssumeRole
echo "1. IAM / STS"
check "AssumeRole → ${ROLE_NAME}" \
    aws sts assume-role \
        --role-arn "${ROLE_ARN}" \
        --role-session-name verify-test \
        --duration-seconds 900

# 2. EKS Describe
echo ""
echo "2. EKS Cluster"
check "Describe cluster ${CLUSTER_NAME}" \
    aws eks describe-cluster --name "${CLUSTER_NAME}" --region "${REGION}"

# 3. CloudWatch alarms
echo ""
echo "3. CloudWatch Alarms"
ALARM_COUNT=$(aws cloudwatch describe-alarms \
    --alarm-name-prefix "${PREFIX}" \
    --region "${REGION}" \
    --query 'length(MetricAlarms)' \
    --output text 2>/dev/null || echo "0")

if [[ "${ALARM_COUNT}" -ge 6 ]]; then
    echo "  [PASS] Alarm count: ${ALARM_COUNT} (expected ≥6)"
    ((PASS++))
else
    echo "  [FAIL] Alarm count: ${ALARM_COUNT} (expected ≥6)"
    ((FAIL++))
fi

# 4. CloudWatch log groups
echo ""
echo "4. CloudWatch Logs"
LOG_GROUP="/aws/eks/${CLUSTER_NAME}/cluster"
check "Log group exists: ${LOG_GROUP}" \
    aws logs describe-log-groups \
        --log-group-name-prefix "${LOG_GROUP}" \
        --region "${REGION}" \
        --query 'logGroups[0].logGroupName'

# 5. kubectl connectivity
echo ""
echo "5. Kubernetes"
NODE_COUNT=$(kubectl get nodes --no-headers 2>/dev/null | wc -l | tr -d ' ')
if [[ "${NODE_COUNT}" -ge 2 ]]; then
    echo "  [PASS] Node count: ${NODE_COUNT} (expected ≥2)"
    ((PASS++))
else
    echo "  [FAIL] Node count: ${NODE_COUNT} (expected ≥2)"
    ((FAIL++))
fi

POD_COUNT=$(kubectl get pods -n "${NAMESPACE}" --no-headers 2>/dev/null | wc -l | tr -d ' ')
if [[ "${POD_COUNT}" -ge 5 ]]; then
    echo "  [PASS] Pod count in ${NAMESPACE}: ${POD_COUNT} (expected ≥5)"
    ((PASS++))
else
    echo "  [FAIL] Pod count in ${NAMESPACE}: ${POD_COUNT} (expected ≥5)"
    ((FAIL++))
fi

# Summary
echo ""
echo "============================================"
echo "  Results: ${PASS} passed, ${FAIL} failed"
echo "============================================"

if [[ "${FAIL}" -gt 0 ]]; then
    echo ""
    echo "Some checks failed. Review output above."
    exit 1
fi

echo ""
echo "All checks passed. Register with AgenticOps:"
echo ""
echo "  aiops create account chaos-lab \\"
echo "    --account-id ${ACCOUNT_ID} \\"
echo "    --role-arn ${ROLE_ARN} \\"
echo "    --regions ${REGION} --activate"
echo ""
echo "Then in aiops chat:"
echo "  > scan services=EKS,EC2 regions=us-east-1"
echo "  > detect scope=all deep=true"
