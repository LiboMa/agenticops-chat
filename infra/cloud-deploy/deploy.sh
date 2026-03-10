#!/bin/bash
set -euo pipefail

# ---------------------------------------------------------------------------
# deploy.sh — deploy AgenticOps via CloudFormation
# ---------------------------------------------------------------------------
# Usage:
#   ./deploy.sh --vpc-id VPC --private-subnet1 SN1 --private-subnet2 SN2 \
#               --public-subnet1 SN1 --public-subnet2 SN2 --rds-password PWD \
#               [--stack-name NAME] [--region REGION] [--db rds|sqlite-efs] \
#               [--vector rds|s3] [--domain DOMAIN] [--hosted-zone-id HZ] \
#               [--acm-cert-arn ARN]
# ---------------------------------------------------------------------------

STACK_NAME="agenticops"
REGION="us-east-1"
DB_BACKEND="rds"
VECTOR="rds"
VPC_ID=""
PRIVATE_SUBNET1=""
PRIVATE_SUBNET2=""
PUBLIC_SUBNET1=""
PUBLIC_SUBNET2=""
RDS_PASSWORD=""
DOMAIN=""
HOSTED_ZONE_ID=""
ACM_CERT_ARN=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --stack-name)       STACK_NAME="$2";       shift 2 ;;
    --region)           REGION="$2";           shift 2 ;;
    --vpc-id)           VPC_ID="$2";           shift 2 ;;
    --private-subnet1)  PRIVATE_SUBNET1="$2";  shift 2 ;;
    --private-subnet2)  PRIVATE_SUBNET2="$2";  shift 2 ;;
    --public-subnet1)   PUBLIC_SUBNET1="$2";   shift 2 ;;
    --public-subnet2)   PUBLIC_SUBNET2="$2";   shift 2 ;;
    --rds-password)     RDS_PASSWORD="$2";     shift 2 ;;
    --db)               DB_BACKEND="$2";       shift 2 ;;
    --vector)           VECTOR="$2";           shift 2 ;;
    --domain)           DOMAIN="$2";           shift 2 ;;
    --hosted-zone-id)   HOSTED_ZONE_ID="$2";   shift 2 ;;
    --acm-cert-arn)     ACM_CERT_ARN="$2";     shift 2 ;;
    *)
      echo "Unknown option: $1" >&2
      exit 1
      ;;
  esac
done

# --- Validate required params ---
missing=()
[[ -z "$VPC_ID" ]]          && missing+=("--vpc-id")
[[ -z "$PRIVATE_SUBNET1" ]] && missing+=("--private-subnet1")
[[ -z "$PRIVATE_SUBNET2" ]] && missing+=("--private-subnet2")
[[ -z "$PUBLIC_SUBNET1" ]]  && missing+=("--public-subnet1")
[[ -z "$PUBLIC_SUBNET2" ]]  && missing+=("--public-subnet2")
[[ -z "$RDS_PASSWORD" ]]    && missing+=("--rds-password")

if [[ ${#missing[@]} -gt 0 ]]; then
  echo "Error: missing required parameters: ${missing[*]}" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE="${SCRIPT_DIR}/cfn-agenticops.yaml"

echo "Deploying stack '${STACK_NAME}' in ${REGION} ..."

aws cloudformation deploy \
  --region "$REGION" \
  --stack-name "$STACK_NAME" \
  --template-file "$TEMPLATE" \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
    VpcId="$VPC_ID" \
    PrivateSubnet1="$PRIVATE_SUBNET1" \
    PrivateSubnet2="$PRIVATE_SUBNET2" \
    PublicSubnet1="$PUBLIC_SUBNET1" \
    PublicSubnet2="$PUBLIC_SUBNET2" \
    RDSPassword="$RDS_PASSWORD" \
    DatabaseBackend="$DB_BACKEND" \
    VectorStorage="$VECTOR" \
    DomainName="$DOMAIN" \
    HostedZoneId="$HOSTED_ZONE_ID" \
    AcmCertArn="$ACM_CERT_ARN"

echo ""
echo "Stack outputs:"
aws cloudformation describe-stacks \
  --region "$REGION" \
  --stack-name "$STACK_NAME" \
  --query 'Stacks[0].Outputs' \
  --output table
