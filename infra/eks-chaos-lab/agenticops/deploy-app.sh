#!/usr/bin/env bash
# Deploy AgenticOps into the chaos-lab EKS cluster (internal-only).
# Steps: ensure ECR repo → build+push image → create IRSA SA → apply manifests → wait ready.
# Usage: bash deploy-app.sh [--admin-password PW]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
CLUSTER="agenticops-chaos-lab"
REGION="us-east-1"
NS="agenticops"
ECR_REPO_NAME="agenticops"
IAM_POLICY_FILE="${SCRIPT_DIR}/../iam/agenticops-irsa-policy.json"
ADMIN_PW="aiops2026"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --admin-password) ADMIN_PW="$2"; shift 2;;
    *) echo "Unknown arg: $1"; exit 1;;
  esac
done

# HARD RULE guard: refuse if any manifest declares a public Service type.
if grep -rEn "type:\s*(LoadBalancer|NodePort)" "${SCRIPT_DIR}"/*.yaml; then
  echo "ERROR: public Service type found — app must stay ClusterIP. Aborting."
  exit 1
fi

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
REGISTRY="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"
ECR_URL="${REGISTRY}/${ECR_REPO_NAME}"

echo "[1/6] Ensure ECR repo ${ECR_REPO_NAME}"
aws ecr describe-repositories --repository-names "${ECR_REPO_NAME}" --region "${REGION}" >/dev/null 2>&1 \
  || aws ecr create-repository --repository-name "${ECR_REPO_NAME}" --region "${REGION}" >/dev/null

echo "[2/6] Build + push image"
AWS_REGION="${REGION}" bash "${REPO_ROOT}/docker/build.sh" push "${ECR_URL}"
IMAGE_TAG=$(cd "${REPO_ROOT}" && git rev-parse --short HEAD)
IMAGE="${ECR_URL}:${IMAGE_TAG}"

echo "[3/6] Create IRSA ServiceAccount (idempotent)"
POLICY_ARN="arn:aws:iam::${ACCOUNT_ID}:policy/AgenticOpsIRSAPolicy"
aws iam get-policy --policy-arn "${POLICY_ARN}" >/dev/null 2>&1 \
  || aws iam create-policy --policy-name AgenticOpsIRSAPolicy \
       --policy-document "file://${IAM_POLICY_FILE}" >/dev/null
kubectl create namespace "${NS}" --dry-run=client -o yaml | kubectl apply -f -
eksctl create iamserviceaccount \
  --cluster "${CLUSTER}" --region "${REGION}" \
  --namespace "${NS}" --name agenticops \
  --attach-policy-arn "${POLICY_ARN}" \
  --approve --override-existing-serviceaccounts
IRSA_ROLE_ARN=$(aws iam list-roles \
  --query "Roles[?contains(RoleName, 'agenticops') && contains(RoleName, 'chaos-lab')].Arn | [0]" \
  --output text 2>/dev/null || echo "")
# Fallback: read the annotation eksctl set on the SA.
if [[ -z "${IRSA_ROLE_ARN}" || "${IRSA_ROLE_ARN}" == "None" ]]; then
  IRSA_ROLE_ARN=$(kubectl get sa agenticops -n "${NS}" -o jsonpath='{.metadata.annotations.eks\.amazonaws\.com/role-arn}')
fi
echo "  IRSA role: ${IRSA_ROLE_ARN}"

echo "[4/6] Create app Secret"
kubectl create secret generic agenticops-secret -n "${NS}" \
  --from-literal=AIOPS_ADMIN_PASSWORD="${ADMIN_PW}" \
  --dry-run=client -o yaml | kubectl apply -f -

echo "[5/6] Apply manifests (SA annotation + image substituted)"
sed "s#__IRSA_ROLE_ARN__#${IRSA_ROLE_ARN}#g" "${SCRIPT_DIR}/serviceaccount.yaml" | kubectl apply -f -
kubectl apply -f "${SCRIPT_DIR}/rbac.yaml"
kubectl apply -f "${SCRIPT_DIR}/configmap.yaml"
sed "s#__IMAGE__#${IMAGE}#g" "${SCRIPT_DIR}/deployment.yaml" | kubectl apply -f -
kubectl apply -f "${SCRIPT_DIR}/service.yaml"

echo "[6/6] Wait for rollout"
kubectl rollout status deployment/agenticops -n "${NS}" --timeout=300s

cat <<EOF

Deployed. App is ClusterIP-only (no public ingress).
Reach it from this machine:
  kubectl port-forward svc/agenticops -n ${NS} 8000:8000
Then: curl -s localhost:8000/api/health
EOF
