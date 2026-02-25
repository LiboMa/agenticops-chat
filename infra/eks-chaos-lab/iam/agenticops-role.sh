#!/usr/bin/env bash
# Create the AgenticOpsReadOnlyRole IAM role with inline read-only policy.
# Idempotent — safe to run multiple times.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROLE_NAME="AgenticOpsReadOnlyRole"
POLICY_NAME="AgenticOpsReadOnly"

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
echo "Account ID: ${ACCOUNT_ID}"

# Build trust policy with real account ID
TRUST_POLICY=$(sed "s/CALLER_ACCOUNT_ID/${ACCOUNT_ID}/" "${SCRIPT_DIR}/trust-policy.json")

# Create role (or skip if exists)
if aws iam get-role --role-name "${ROLE_NAME}" &>/dev/null; then
    echo "Role ${ROLE_NAME} already exists — updating trust policy"
    aws iam update-assume-role-policy \
        --role-name "${ROLE_NAME}" \
        --policy-document "${TRUST_POLICY}"
else
    echo "Creating role ${ROLE_NAME}..."
    aws iam create-role \
        --role-name "${ROLE_NAME}" \
        --assume-role-policy-document "${TRUST_POLICY}" \
        --description "Read-only role for AgenticOps agents" \
        --tags Key=Project,Value=agenticops Key=Environment,Value=chaos-lab
fi

# Attach inline policy (put-role-policy is idempotent)
echo "Attaching inline policy ${POLICY_NAME}..."
aws iam put-role-policy \
    --role-name "${ROLE_NAME}" \
    --policy-name "${POLICY_NAME}" \
    --policy-document "file://${SCRIPT_DIR}/readonly-policy.json"

ROLE_ARN=$(aws iam get-role --role-name "${ROLE_NAME}" --query 'Role.Arn' --output text)
echo ""
echo "Done. Role ARN: ${ROLE_ARN}"
echo ""
echo "Register with AgenticOps:"
echo "  aiops create account chaos-lab \\"
echo "    --account-id ${ACCOUNT_ID} \\"
echo "    --role-arn ${ROLE_ARN} \\"
echo "    --regions us-east-1 --activate"
