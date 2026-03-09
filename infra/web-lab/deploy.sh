#!/bin/bash
# WebLab 3-tier deployment: ALB (HTTPS/443) → EC2 (Flask) → RDS (MySQL)
# Usage: bash deploy.sh [create|update|delete|status]
set -euo pipefail

STACK_NAME="weblab-stack"
REGION="ap-southeast-1"
DB_PASSWORD="WebLab2026!"

# Paths
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CFN_TEMPLATE="${SCRIPT_DIR}/cfn-weblab.yaml"

action="${1:-create}"

case "$action" in
  create)
    echo "==> Creating stack ${STACK_NAME}..."
    aws cloudformation create-stack \
      --stack-name "$STACK_NAME" \
      --region "$REGION" \
      --template-body "file://${CFN_TEMPLATE}" \
      --parameters ParameterKey=DBPassword,ParameterValue="${DB_PASSWORD}" \
      --capabilities CAPABILITY_NAMED_IAM \
      --tags Key=Project,Value=weblab Key=Environment,Value=test

    echo "==> Waiting for stack creation (this takes ~10 min for RDS)..."
    aws cloudformation wait stack-create-complete \
      --stack-name "$STACK_NAME" \
      --region "$REGION"

    echo "==> Stack created! Outputs:"
    aws cloudformation describe-stacks \
      --stack-name "$STACK_NAME" \
      --region "$REGION" \
      --query 'Stacks[0].Outputs[*].{Key:OutputKey,Value:OutputValue}' \
      --output table
    ;;

  update)
    echo "==> Updating stack ${STACK_NAME}..."
    aws cloudformation update-stack \
      --stack-name "$STACK_NAME" \
      --region "$REGION" \
      --template-body "file://${CFN_TEMPLATE}" \
      --parameters ParameterKey=DBPassword,ParameterValue="${DB_PASSWORD}" \
      --capabilities CAPABILITY_NAMED_IAM

    echo "==> Waiting for update..."
    aws cloudformation wait stack-update-complete \
      --stack-name "$STACK_NAME" \
      --region "$REGION"

    echo "==> Updated."
    ;;

  delete)
    echo "==> Deleting stack ${STACK_NAME}..."
    aws cloudformation delete-stack \
      --stack-name "$STACK_NAME" \
      --region "$REGION"
    echo "==> Waiting for deletion..."
    aws cloudformation wait stack-delete-complete \
      --stack-name "$STACK_NAME" \
      --region "$REGION"
    echo "==> Deleted."
    ;;

  status)
    aws cloudformation describe-stacks \
      --stack-name "$STACK_NAME" \
      --region "$REGION" \
      --query 'Stacks[0].{Status:StackStatus,Reason:StackStatusReason}' \
      --output table 2>/dev/null || echo "Stack not found."

    aws cloudformation describe-stacks \
      --stack-name "$STACK_NAME" \
      --region "$REGION" \
      --query 'Stacks[0].Outputs[*].{Key:OutputKey,Value:OutputValue}' \
      --output table 2>/dev/null || true
    ;;

  *)
    echo "Usage: $0 [create|update|delete|status]"
    exit 1
    ;;
esac
