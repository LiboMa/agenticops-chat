#!/bin/bash
set -euo pipefail

# -----------------------------------------------------------------------------
# AgenticOps — One-Click Deployment to AWS Singapore
# Usage: ./deploy.sh [apply|destroy|plan|setup|redeploy]
#
# Actions:
#   apply    — Create infrastructure (Terraform) + run setup on instance
#   destroy  — Tear down all infrastructure
#   plan     — Preview Terraform changes
#   setup    — Run user_data.sh on existing instance (first-time app install)
#   redeploy — Pull latest code + rebuild + restart service
# -----------------------------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ACTION="${1:-apply}"
GIT_BRANCH="${2:-main}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
err()  { echo -e "${RED}[ERROR]${NC} $1" >&2; exit 1; }

# -----------------------------------------------------------------------------
# Pre-flight Checks
# -----------------------------------------------------------------------------

log "=== AgenticOps Deployment (ap-southeast-1) ==="

for cmd in aws terraform; do
  command -v "$cmd" >/dev/null 2>&1 || err "$cmd is required but not installed."
done

log "Validating AWS credentials..."
AWS_ACCOUNT=$(aws sts get-caller-identity --query Account --output text 2>/dev/null) || \
  err "AWS credentials not configured. Run 'aws configure' or set AWS_PROFILE."
log "AWS Account: $AWS_ACCOUNT"

REGION="ap-southeast-1"

# -----------------------------------------------------------------------------
# Helper: Run script on instance via SSM (sends script content directly)
# -----------------------------------------------------------------------------

run_on_instance() {
  local instance_id="$1"
  local script_path="$2"
  local description="$3"

  log "$description..."

  # Build JSON parameters file with script content
  local params_file
  params_file=$(mktemp /tmp/ssm-params-XXXXX.json)
  # Convert script to JSON array of single command (bash heredoc trick)
  python3 -c "
import json, sys
script = open('$script_path').read()
# SSM runs each command array element as a separate line — wrap in single bash -c
params = {'commands': [script]}
json.dump(params, open('$params_file', 'w'))
"

  local cmd_id
  cmd_id=$(aws ssm send-command \
    --instance-ids "$instance_id" \
    --region "$REGION" \
    --document-name "AWS-RunShellScript" \
    --timeout-seconds 900 \
    --parameters "file://$params_file" \
    --query "Command.CommandId" --output text)

  rm -f "$params_file"

  log "SSM Command: $cmd_id — waiting for completion..."

  # Wait for completion (up to 15 min)
  local timeout=900
  local elapsed=0
  while [ $elapsed -lt $timeout ]; do
    local status
    status=$(aws ssm get-command-invocation \
      --command-id "$cmd_id" \
      --instance-id "$instance_id" \
      --region "$REGION" \
      --query "Status" --output text 2>/dev/null || echo "Pending")

    case "$status" in
      Success)
        log "Command completed successfully."
        aws ssm get-command-invocation \
          --command-id "$cmd_id" \
          --instance-id "$instance_id" \
          --region "$REGION" \
          --query "StandardOutputContent" --output text 2>/dev/null | tail -15
        return 0
        ;;
      Failed|TimedOut|Cancelled)
        warn "Command $status. Output:"
        aws ssm get-command-invocation \
          --command-id "$cmd_id" \
          --instance-id "$instance_id" \
          --region "$REGION" \
          --query "[StandardOutputContent, StandardErrorContent]" --output text 2>/dev/null | tail -30
        return 1
        ;;
    esac
    sleep 15
    elapsed=$((elapsed + 15))
  done
  err "Command timed out after ${timeout}s"
}

# -----------------------------------------------------------------------------
# Terraform
# -----------------------------------------------------------------------------

cd "$SCRIPT_DIR"

if [ ! -d ".terraform" ]; then
  log "Initializing Terraform..."
  terraform init -input=false
fi

case "$ACTION" in
  plan)
    log "Running terraform plan..."
    terraform plan
    exit 0
    ;;
  destroy)
    warn "Destroying all resources..."
    terraform destroy -auto-approve
    log "All resources destroyed."
    exit 0
    ;;
  apply)
    log "Running terraform apply..."
    terraform apply -auto-approve

    INSTANCE_ID=$(terraform output -raw ec2_instance_id)
    CF_URL=$(terraform output -raw cloudfront_url)

    log "Waiting for EC2 instance to pass status checks..."
    aws ec2 wait instance-status-ok --instance-ids "$INSTANCE_ID" --region "$REGION"

    # Run setup script on instance
    run_on_instance "$INSTANCE_ID" "$SCRIPT_DIR/user_data.sh" "Running initial setup (git clone + uv + build)"
    ;;

  setup)
    # Re-run full setup on existing instance (substitute Terraform template vars)
    INSTANCE_ID=$(terraform output -raw ec2_instance_id)
    CF_URL=$(terraform output -raw cloudfront_url)
    SETUP_SCRIPT=$(mktemp /tmp/setup-XXXXX.sh)
    sed -e "s/\${app_port}/8000/g" \
        -e "s/\${bedrock_region}/us-east-1/g" \
        -e "s/\${bedrock_model}/global.anthropic.claude-opus-4-6-v1/g" \
        -e "s/\${admin_password}/aiops2026/g" \
        -e "s/\${git_branch}/${GIT_BRANCH}/g" \
        -e 's/\$\${/\${/g' \
        "$SCRIPT_DIR/user_data.sh" > "$SETUP_SCRIPT"
    run_on_instance "$INSTANCE_ID" "$SETUP_SCRIPT" "Running full setup"
    rm -f "$SETUP_SCRIPT"
    ;;

  redeploy)
    # Pull latest + rebuild + restart
    INSTANCE_ID=$(terraform output -raw ec2_instance_id)
    CF_URL=$(terraform output -raw cloudfront_url)

    # Create a temporary redeploy script
    REDEPLOY_SCRIPT=$(mktemp /tmp/redeploy-XXXXX.sh)
    cat > "$REDEPLOY_SCRIPT" <<SCRIPT
#!/bin/bash
set -euo pipefail
export PATH="/root/.local/bin:/usr/local/bin:\$PATH"
export HOME="\${HOME:-/root}"
export UV_PYTHON_INSTALL_DIR=/opt/uv-python
git config --global --add safe.directory /opt/agenticops

cd /opt/agenticops
git fetch origin ${GIT_BRANCH}:refs/remotes/origin/${GIT_BRANCH}
git checkout ${GIT_BRANCH} 2>/dev/null || git checkout -b ${GIT_BRANCH} origin/${GIT_BRANCH}
git reset --hard origin/${GIT_BRANCH}

# Backend — lockfile-first install (prevents dependency drift)
source .venv/bin/activate
uv pip install -r requirements.txt
uv pip install -e ".[im,files,reports]" --no-deps

# Frontend
cd src/agenticops/web/frontend
npm install --silent
npm run build
cd /opt/agenticops

chmod -R +x .venv/bin/
chown -R agenticops:agenticops /opt/agenticops
# Ensure uvx exists (needed by MCP servers)
if [ ! -f /usr/local/bin/uvx ] || ! /usr/local/bin/uvx --version &>/dev/null; then
  sudo -u agenticops bash -c 'curl -LsSf https://astral.sh/uv/install.sh | sh' 2>/dev/null
  cp /home/agenticops/.local/bin/uvx /usr/local/bin/uvx 2>/dev/null || true
fi
# Update systemd unit (workers/timeout may have changed)
sed -i 's/--workers [0-9]*/--workers 4/' /etc/systemd/system/agenticops.service
grep -q -- '--timeout-keep-alive' /etc/systemd/system/agenticops.service || \
  sed -i 's/--workers 4/--workers 4 --timeout-keep-alive 30/' /etc/systemd/system/agenticops.service
systemctl daemon-reload
systemctl restart agenticops
# Wait for 4 workers to start (each ~2s)
for i in 1 2 3 4 5 6; do
  sleep 3
  if curl -sf http://localhost:8000/api/health; then
    echo " HEALTH OK"
    exit 0
  fi
done
echo "HEALTH FAILED"
journalctl -u agenticops --no-pager -n 20
exit 1
SCRIPT

    run_on_instance "$INSTANCE_ID" "$REDEPLOY_SCRIPT" "Redeploying (git pull + rebuild)"
    rm -f "$REDEPLOY_SCRIPT"
    ;;

  *)
    err "Unknown action: $ACTION. Use: apply|destroy|plan|setup|redeploy"
    ;;
esac

# -----------------------------------------------------------------------------
# Output
# -----------------------------------------------------------------------------

INSTANCE_ID=${INSTANCE_ID:-$(terraform output -raw ec2_instance_id 2>/dev/null || echo "unknown")}
CF_URL=${CF_URL:-$(terraform output -raw cloudfront_url 2>/dev/null || echo "unknown")}
PUBLIC_IP=$(terraform output -raw ec2_public_ip 2>/dev/null || echo "unknown")

echo ""
echo "============================================"
echo -e "${GREEN}  AgenticOps${NC}"
echo "============================================"
echo ""
echo "  URL:         $CF_URL"
echo "  Login:       admin / aiops2026"
echo "  Instance:    $INSTANCE_ID"
echo "  Public IP:   $PUBLIC_IP"
echo "  Region:      $REGION"
echo ""
echo "  SSH:         ssh ubuntu@$PUBLIC_IP"
echo "  SSM Access:  aws ssm start-session --target $INSTANCE_ID --region $REGION"
echo "  Logs:        journalctl -u agenticops -f"
echo ""
echo "  Redeploy:    ./deploy.sh redeploy [branch]"
echo "  Full setup:  ./deploy.sh setup"
echo ""
echo "============================================"
