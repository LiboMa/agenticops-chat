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
TOTAL=7

# Spinner for showing progress while a command runs
spin() {
    local label="$1"
    shift
    local pid
    local frames=("⠋" "⠙" "⠹" "⠸" "⠴" "⠦" "⠧" "⠏")
    local i=0

    # Run command in background
    "$@" &>/dev/null &
    pid=$!

    # Animate spinner while waiting
    while kill -0 "$pid" 2>/dev/null; do
        printf "\r  %s %s ..." "${frames[$((i % ${#frames[@]}))]}" "${label}"
        i=$((i + 1))
        sleep 0.1
    done

    # Get exit code
    wait "$pid" && local rc=0 || local rc=$?

    # Clear spinner line and print result
    printf "\r\033[K"
    if [[ $rc -eq 0 ]]; then
        echo "  [PASS] ${label}"
        PASS=$((PASS + 1))
    else
        echo "  [FAIL] ${label}"
        FAIL=$((FAIL + 1))
    fi
}

# Spinner for commands whose output we need to capture
spin_capture() {
    local label="$1"
    shift
    local pid tmpfile
    local frames=("⠋" "⠙" "⠹" "⠸" "⠴" "⠦" "⠧" "⠏")
    local i=0

    tmpfile=$(mktemp)

    # Run command in background, capture output
    "$@" > "$tmpfile" 2>/dev/null &
    pid=$!

    while kill -0 "$pid" 2>/dev/null; do
        printf "\r  %s %s ..." "${frames[$((i % ${#frames[@]}))]}" "${label}"
        i=$((i + 1))
        sleep 0.1
    done

    wait "$pid" && local rc=0 || local rc=$?
    printf "\r\033[K"

    CAPTURED=$(cat "$tmpfile")
    rm -f "$tmpfile"
    return $rc
}

header() {
    local step="$1"
    local total="$2"
    local title="$3"
    echo ""
    echo "[$step/$total] ${title}"
}

echo "============================================"
echo "  AgenticOps Integration Verification"
echo "  Cluster: ${CLUSTER_NAME} (${REGION})"
echo "============================================"

# Step 0: Get account ID
printf "\n  Resolving AWS account ID ..."
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}"
printf "\r\033[K  Account: ${ACCOUNT_ID}\n"

# 1. STS AssumeRole
header 1 "$TOTAL" "IAM / STS"
spin "AssumeRole → ${ROLE_NAME}" \
    aws sts assume-role \
        --role-arn "${ROLE_ARN}" \
        --role-session-name verify-test \
        --duration-seconds 900

# 2. EKS Describe
header 2 "$TOTAL" "EKS Cluster"
spin "Describe cluster ${CLUSTER_NAME}" \
    aws eks describe-cluster --name "${CLUSTER_NAME}" --region "${REGION}"

# 3. CloudWatch alarms
header 3 "$TOTAL" "CloudWatch Alarms"
spin_capture "Querying alarms with prefix ${PREFIX}" \
    aws cloudwatch describe-alarms \
        --alarm-name-prefix "${PREFIX}" \
        --region "${REGION}" \
        --query 'length(MetricAlarms)' \
        --output text \
    || true
ALARM_COUNT="${CAPTURED:-0}"

if [[ "${ALARM_COUNT}" -ge 6 ]]; then
    echo "  [PASS] Alarm count: ${ALARM_COUNT} (expected ≥6)"
    PASS=$((PASS + 1))
else
    echo "  [FAIL] Alarm count: ${ALARM_COUNT} (expected ≥6)"
    FAIL=$((FAIL + 1))
fi

# 4. CloudWatch log groups
header 4 "$TOTAL" "CloudWatch Logs"
LOG_GROUP="/aws/eks/${CLUSTER_NAME}/cluster"
spin "Log group exists: ${LOG_GROUP}" \
    aws logs describe-log-groups \
        --log-group-name-prefix "${LOG_GROUP}" \
        --region "${REGION}" \
        --query 'logGroups[0].logGroupName'

# 5. kubectl nodes
header 5 "$TOTAL" "Kubernetes Nodes"
spin_capture "Counting nodes" kubectl get nodes --no-headers || true
NODE_COUNT=$(echo "${CAPTURED}" | grep -c '.' || echo "0")

if [[ "${NODE_COUNT}" -ge 2 ]]; then
    echo "  [PASS] Node count: ${NODE_COUNT} (expected ≥2)"
    PASS=$((PASS + 1))
else
    echo "  [FAIL] Node count: ${NODE_COUNT} (expected ≥2)"
    FAIL=$((FAIL + 1))
fi

# 6. kubectl pods
header 6 "$TOTAL" "Kubernetes Pods"
spin_capture "Counting pods in ${NAMESPACE}" kubectl get pods -n "${NAMESPACE}" --no-headers || true
POD_COUNT=$(echo "${CAPTURED}" | grep -c '.' || echo "0")

if [[ "${POD_COUNT}" -ge 5 ]]; then
    echo "  [PASS] Pod count in ${NAMESPACE}: ${POD_COUNT} (expected ≥5)"
    PASS=$((PASS + 1))
else
    echo "  [FAIL] Pod count in ${NAMESPACE}: ${POD_COUNT} (expected ≥5)"
    FAIL=$((FAIL + 1))
fi

# 7. Pod status (all Running?)
header 7 "$TOTAL" "Pod Health"
spin_capture "Checking pod statuses" kubectl get pods -n "${NAMESPACE}" --no-headers || true
NOT_RUNNING_LINES=$(echo "${CAPTURED}" | grep -v 'Running' || true)
if [[ -z "${NOT_RUNNING_LINES}" ]]; then
    echo "  [PASS] All pods Running"
    PASS=$((PASS + 1))
else
    NOT_RUNNING_COUNT=$(echo "${NOT_RUNNING_LINES}" | wc -l | tr -d ' ')
    echo "  [FAIL] ${NOT_RUNNING_COUNT} pod(s) not in Running state"
    echo "${NOT_RUNNING_LINES}" | sed 's/^/         /'
    FAIL=$((FAIL + 1))
fi

# Summary
echo ""
echo "============================================"
if [[ "${FAIL}" -eq 0 ]]; then
    echo "  Result: ${PASS}/${TOTAL} passed — ALL OK"
else
    echo "  Result: ${PASS}/${TOTAL} passed, ${FAIL} failed"
fi
echo "============================================"

if [[ "${FAIL}" -gt 0 ]]; then
    echo ""
    echo "Some checks failed. Review output above."
    exit 1
fi

echo ""
echo "Register with AgenticOps:"
echo ""
echo "  aiops create account chaos-lab \\"
echo "    --account-id ${ACCOUNT_ID} \\"
echo "    --role-arn ${ROLE_ARN} \\"
echo "    --regions ${REGION} --activate"
echo ""
echo "Then in aiops chat:"
echo "  > scan services=EKS,EC2 regions=us-east-1"
echo "  > detect scope=all deep=true"
