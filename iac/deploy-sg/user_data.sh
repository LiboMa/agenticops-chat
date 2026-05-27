#!/bin/bash
set -euo pipefail

# -----------------------------------------------------------------------------
# AgenticOps EC2 Bootstrap — Ubuntu 24.04
# Python: uv | Frontend: Node.js 20 | Code: git clone
#
# Can be invoked by:
#   1. Terraform templatefile (variables injected at plan time)
#   2. deploy.sh setup/redeploy (uses env var defaults below)
# -----------------------------------------------------------------------------

# Variables injected by Terraform templatefile
APP_PORT="${app_port}"
BEDROCK_REGION="${bedrock_region}"
BEDROCK_MODEL="${bedrock_model}"
ADMIN_PASSWORD="${admin_password}"
GIT_BRANCH="${git_branch}"
APP_DIR="/opt/agenticops"
GIT_REPO="https://github.com/LiboMa/agenticops-chat.git"

# Ensure HOME is set (SSM agent may not set it)
export HOME="$${HOME:-/root}"

echo "=== AgenticOps Setup Started: $(date) ==="
echo "Branch: $GIT_BRANCH | Port: $APP_PORT | Region: $BEDROCK_REGION"

# Force apt to use IPv4 (NAT Gateway does not support IPv6)
echo 'Acquire::ForceIPv4 "true";' > /etc/apt/apt.conf.d/99force-ipv4

# System packages
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y \
  git curl unzip jq \
  build-essential libffi-dev libssl-dev \
  ca-certificates gnupg

# -----------------------------------------------------------------------------
# Install AWS CLI v2
# -----------------------------------------------------------------------------
if ! command -v aws &>/dev/null; then
  curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o /tmp/awscliv2.zip
  unzip -qo /tmp/awscliv2.zip -d /tmp
  /tmp/aws/install
  rm -rf /tmp/awscliv2.zip /tmp/aws
fi

# Create app user with sudo privileges
useradd -r -m -s /bin/bash agenticops 2>/dev/null || true
usermod -aG sudo agenticops 2>/dev/null || true
echo "agenticops ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/agenticops
chmod 0440 /etc/sudoers.d/agenticops

# -----------------------------------------------------------------------------
# Install uv (Python package manager)
# -----------------------------------------------------------------------------
if ! command -v uv &>/dev/null && [ ! -f /root/.local/bin/uv ]; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
export PATH="/root/.local/bin:/usr/local/bin:$PATH"

# Install Python 3.12 via uv (to shared location accessible by service user)
UV_PYTHON_INSTALL_DIR=/opt/uv-python uv python install 3.12
chmod -R a+rx /opt/uv-python

# -----------------------------------------------------------------------------
# Install Node.js 20 (for frontend build)
# -----------------------------------------------------------------------------
if ! command -v node &>/dev/null; then
  curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
  apt-get install -y nodejs
fi

# -----------------------------------------------------------------------------
# Clone / Update repository
# -----------------------------------------------------------------------------
git config --global --add safe.directory "$APP_DIR"

if [ -d "$APP_DIR/.git" ]; then
  cd "$APP_DIR"
  git fetch origin
  git reset --hard "origin/$GIT_BRANCH"
else
  git clone --depth 1 --branch "$GIT_BRANCH" "$GIT_REPO" "$APP_DIR"
fi

cd "$APP_DIR"

# -----------------------------------------------------------------------------
# Backend: Python environment via uv
# -----------------------------------------------------------------------------
# Recreate venv to ensure correct Python path
rm -rf .venv
UV_PYTHON_INSTALL_DIR=/opt/uv-python uv venv .venv --python 3.12
source .venv/bin/activate
uv pip install -e ".[im,files,reports]"

# -----------------------------------------------------------------------------
# Frontend: Build React SPA
# -----------------------------------------------------------------------------
cd "$APP_DIR/src/agenticops/web/frontend"
npm install --silent
npm run build
cd "$APP_DIR"

# -----------------------------------------------------------------------------
# Permissions
# -----------------------------------------------------------------------------
mkdir -p "$APP_DIR/data"
chmod -R +x "$APP_DIR/.venv/bin/"
chown -R agenticops:agenticops "$APP_DIR"
cp /root/.local/bin/uv /usr/local/bin/uv 2>/dev/null || true
# NOTE: uvx (uv tool run) is NOT supported in cloud deployment.
# The uvx binary is a multi-call binary that cannot be simply copied —
# doing so causes infinite recursive subprocess spawning (uv tool uvx tool uvx...).
# MCP stdio servers requiring uvx are disabled in cloud; use SSE transport instead.

# -----------------------------------------------------------------------------
# Clear MCP servers config (avoid startup failures from stale local configs)
# -----------------------------------------------------------------------------
mkdir -p "$APP_DIR/config"
echo '{"mcpServers": {}}' > "$APP_DIR/config/mcp-servers.json"

# -----------------------------------------------------------------------------
# Environment config
# -----------------------------------------------------------------------------
cat > /etc/agenticops.env <<ENVEOF
AIOPS_BEDROCK_REGION=$BEDROCK_REGION
AIOPS_BEDROCK_MODEL_ID=$BEDROCK_MODEL
AIOPS_DATABASE_URL=sqlite:///$APP_DIR/data/agenticops.db
AIOPS_API_AUTH_ENABLED=true
AIOPS_ADMIN_PASSWORD=$ADMIN_PASSWORD
AIOPS_DEPLOYMENT_PROFILE=cloud
PATH=$APP_DIR/.venv/bin:/usr/local/bin:/usr/bin:/bin
ENVEOF

# -----------------------------------------------------------------------------
# Systemd service
# -----------------------------------------------------------------------------
cat > /etc/systemd/system/agenticops.service <<SVCEOF
[Unit]
Description=AgenticOps Web Service
After=network.target

[Service]
Type=simple
User=agenticops
Group=agenticops
WorkingDirectory=$APP_DIR
EnvironmentFile=/etc/agenticops.env
ExecStart=$APP_DIR/.venv/bin/uvicorn agenticops.web.app:app --host 0.0.0.0 --port $APP_PORT --workers 4 --timeout-keep-alive 30
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
SVCEOF

systemctl daemon-reload
systemctl enable agenticops
systemctl restart agenticops

# Wait and verify
sleep 3
if curl -sf "http://localhost:$APP_PORT/api/health" > /dev/null; then
  echo "=== AgenticOps Setup Complete: $(date) ==="
  echo "Health check: OK"
else
  echo "=== WARNING: Health check failed ==="
  journalctl -u agenticops --no-pager -n 20
fi

echo "Python: $(.venv/bin/python --version)"
echo "uv: $(uv --version)"
echo "Node: $(node --version)"
