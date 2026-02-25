#!/usr/bin/env bash
# Tear down the EKS Chaos Lab — deletes alarms, cluster, IAM role, and log groups.
# Usage: bash cleanup.sh
set -euo pipefail

CLUSTER_NAME="agenticops-chaos-lab"
REGION="us-east-1"
ROLE_NAME="AgenticOpsReadOnlyRole"
POLICY_NAME="AgenticOpsReadOnly"
PREFIX="EKS-${CLUSTER_NAME}"

echo "============================================"
echo "  AgenticOps EKS Chaos Lab — Cleanup"
echo "============================================"
echo ""
echo "This will DELETE:"
echo "  - 6 CloudWatch alarms (${PREFIX}-*)"
echo "  - EKS cluster: ${CLUSTER_NAME}"
echo "  - IAM role: ${ROLE_NAME}"
echo "  - CloudWatch log groups for the cluster"
echo ""

read -p "Are you sure? Type 'yes' to confirm: " CONFIRM
if [[ "${CONFIRM}" != "yes" ]]; then
    echo "Aborted."
    exit 0
fi

echo ""

# Step 1: Delete CloudWatch alarms
echo "Step 1/4: Deleting CloudWatch alarms..."
ALARM_NAMES=$(aws cloudwatch describe-alarms \
    --alarm-name-prefix "${PREFIX}" \
    --region "${REGION}" \
    --query 'MetricAlarms[].AlarmName' \
    --output text 2>/dev/null || true)

if [[ -n "${ALARM_NAMES}" ]]; then
    # shellcheck disable=SC2086
    aws cloudwatch delete-alarms \
        --alarm-names ${ALARM_NAMES} \
        --region "${REGION}"
    echo "  Deleted alarms: ${ALARM_NAMES}"
else
    echo "  No alarms found."
fi

# Step 2: Delete EKS cluster
echo ""
echo "Step 2/4: Deleting EKS cluster (this takes ~10 minutes)..."
if eksctl get cluster --name "${CLUSTER_NAME}" --region "${REGION}" &>/dev/null; then
    eksctl delete cluster --name "${CLUSTER_NAME}" --region "${REGION}" --wait
    echo "  Cluster deleted."
else
    echo "  Cluster not found — skipping."
fi

# Step 3: Delete IAM role
echo ""
echo "Step 3/4: Deleting IAM role..."
if aws iam get-role --role-name "${ROLE_NAME}" &>/dev/null; then
    # Remove inline policy first
    aws iam delete-role-policy \
        --role-name "${ROLE_NAME}" \
        --policy-name "${POLICY_NAME}" 2>/dev/null || true
    # Delete the role
    aws iam delete-role --role-name "${ROLE_NAME}"
    echo "  Deleted role ${ROLE_NAME}."
else
    echo "  Role not found — skipping."
fi

# Step 4: Delete CloudWatch log groups
echo ""
echo "Step 4/4: Deleting CloudWatch log groups..."
for LOG_GROUP in $(aws logs describe-log-groups \
    --log-group-name-prefix "/aws/eks/${CLUSTER_NAME}" \
    --region "${REGION}" \
    --query 'logGroups[].logGroupName' \
    --output text 2>/dev/null); do
    echo "  Deleting ${LOG_GROUP}"
    aws logs delete-log-group \
        --log-group-name "${LOG_GROUP}" \
        --region "${REGION}" 2>/dev/null || true
done

# Also clean up Container Insights log groups
for LOG_GROUP in $(aws logs describe-log-groups \
    --log-group-name-prefix "/aws/containerinsights/${CLUSTER_NAME}" \
    --region "${REGION}" \
    --query 'logGroups[].logGroupName' \
    --output text 2>/dev/null); do
    echo "  Deleting ${LOG_GROUP}"
    aws logs delete-log-group \
        --log-group-name "${LOG_GROUP}" \
        --region "${REGION}" 2>/dev/null || true
done

echo ""
echo "============================================"
echo "  Cleanup Complete"
echo "============================================"
echo ""
echo "All EKS Chaos Lab resources have been deleted."
