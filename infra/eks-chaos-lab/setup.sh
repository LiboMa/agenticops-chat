#!/usr/bin/env bash
# Master setup script for EKS Chaos Lab.
# Creates: IAM role → EKS cluster → workloads → CloudWatch alarms
# Usage: bash setup.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLUSTER_NAME="agenticops-chaos-lab"
REGION="us-east-1"
NAMESPACE="chaos-lab"

echo "============================================"
echo "  AgenticOps EKS Chaos Lab — Setup"
echo "============================================"
echo ""
echo "  Cluster:  ${CLUSTER_NAME}"
echo "  Region:   ${REGION}"
echo "  Nodes:    2x t3.medium (~\$5-7/day)"
echo ""

# Check prerequisites
echo "Checking prerequisites..."
for cmd in aws eksctl kubectl; do
    if ! command -v "${cmd}" &>/dev/null; then
        echo "ERROR: ${cmd} is not installed. Please install it first."
        exit 1
    fi
done

# Verify AWS credentials
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text 2>/dev/null) || {
    echo "ERROR: AWS credentials not configured. Run 'aws configure' first."
    exit 1
}
echo "  AWS Account: ${AWS_ACCOUNT_ID}"
echo "  AWS CLI:     $(aws --version 2>&1 | head -1)"
echo "  eksctl:      $(eksctl version 2>&1)"
echo "  kubectl:     $(kubectl version --client --short 2>/dev/null || kubectl version --client 2>&1 | head -1)"
echo ""

read -p "Proceed with setup? (y/N) " -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 0
fi

# Step 1: Create IAM role
echo ""
echo "============================================"
echo "  Step 1/6: Create IAM Role"
echo "============================================"
bash "${SCRIPT_DIR}/iam/agenticops-role.sh"

# Step 2: Create EKS cluster
echo ""
echo "============================================"
echo "  Step 2/6: Create EKS Cluster"
echo "============================================"
echo "This will take ~12-15 minutes..."
echo ""

if eksctl get cluster --name "${CLUSTER_NAME}" --region "${REGION}" &>/dev/null; then
    echo "Cluster ${CLUSTER_NAME} already exists — skipping creation."
else
    eksctl create cluster -f "${SCRIPT_DIR}/cluster.yaml"
fi

# Verify kubectl context
echo ""
echo "Verifying kubectl context..."
kubectl cluster-info
echo ""

# Step 3: Deploy workloads
echo ""
echo "============================================"
echo "  Step 3/6: Deploy Workloads"
echo "============================================"
kubectl apply -f "${SCRIPT_DIR}/workloads/namespace.yaml"
kubectl apply -f "${SCRIPT_DIR}/workloads/configmap.yaml"
kubectl apply -f "${SCRIPT_DIR}/workloads/backend-deployment.yaml"
kubectl apply -f "${SCRIPT_DIR}/workloads/frontend-deployment.yaml"
kubectl apply -f "${SCRIPT_DIR}/workloads/frontend-hpa.yaml"
kubectl apply -f "${SCRIPT_DIR}/workloads/frontend-pdb.yaml"
kubectl apply -f "${SCRIPT_DIR}/workloads/backend-pdb.yaml"

# Step 4: Wait for pods
echo ""
echo "============================================"
echo "  Step 4/6: Wait for Pods Ready"
echo "============================================"
echo "Waiting for backend deployment..."
kubectl rollout status deployment/backend -n "${NAMESPACE}" --timeout=180s
echo "Waiting for frontend deployment..."
kubectl rollout status deployment/frontend -n "${NAMESPACE}" --timeout=180s
echo ""
kubectl get pods -n "${NAMESPACE}"
echo ""
kubectl get svc -n "${NAMESPACE}"

# Step 5: Wait for Container Insights metrics
echo ""
echo "============================================"
echo "  Step 5/6: Wait for Container Insights"
echo "============================================"
echo "Waiting 60 seconds for metrics to populate..."
sleep 60
echo "Done."

# Step 6: Create CloudWatch alarms
echo ""
echo "============================================"
echo "  Step 6/6: Create CloudWatch Alarms"
echo "============================================"
bash "${SCRIPT_DIR}/alarms/create-alarms.sh" "${CLUSTER_NAME}" "${REGION}"

# Summary
ROLE_ARN="arn:aws:iam::${AWS_ACCOUNT_ID}:role/AgenticOpsReadOnlyRole"

echo ""
echo "============================================"
echo "  Setup Complete!"
echo "============================================"
echo ""
echo "Cluster:  ${CLUSTER_NAME}"
echo "Region:   ${REGION}"
echo "Pods:     $(kubectl get pods -n ${NAMESPACE} --no-headers 2>/dev/null | wc -l | tr -d ' ') running"
echo "Services: $(kubectl get svc -n ${NAMESPACE} --no-headers 2>/dev/null | wc -l | tr -d ' ')"
echo ""
echo "Register with AgenticOps:"
echo "  aiops create account chaos-lab \\"
echo "    --account-id ${AWS_ACCOUNT_ID} \\"
echo "    --role-arn ${ROLE_ARN} \\"
echo "    --regions ${REGION} --activate"
echo ""
echo "Then in aiops chat:"
echo "  > scan all"
echo "  > detect scope=all"
echo ""
echo "IMPORTANT: Remember to run 'bash cleanup.sh' when done to avoid charges."
