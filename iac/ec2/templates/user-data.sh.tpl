#!/bin/bash
set -euo pipefail
echo "=== AgenticOps Docker Setup: $(date) ==="

# Force IPv4
echo 'Acquire::ForceIPv4 "true";' > /etc/apt/apt.conf.d/99force-ipv4

# Install Docker
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y ca-certificates curl
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$${VERSION_CODENAME}") stable" > /etc/apt/sources.list.d/docker.list
apt-get update -y
apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

# Install AWS CLI
if ! command -v aws &>/dev/null; then
  curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o /tmp/awscliv2.zip
  apt-get install -y unzip
  unzip -qo /tmp/awscliv2.zip -d /tmp && /tmp/aws/install && rm -rf /tmp/aws*
fi

# Prepare app directory
# Prepare data dir with correct ownership (container runs as uid 1000)
mkdir -p /opt/agenticops/data
chown -R 1000:1000 /opt/agenticops/data

# Write .env
cat > /opt/agenticops/.env << 'ENVEOF'
${env_content}
ENVEOF

# Write docker-compose.yml
cat > /opt/agenticops/docker-compose.yml << 'COMPEOF'
${compose_content}
COMPEOF

# ECR login and pull
aws ecr get-login-password --region ${region} | docker login --username AWS --password-stdin ${ecr_registry}
docker compose -f /opt/agenticops/docker-compose.yml pull

# Start
docker compose -f /opt/agenticops/docker-compose.yml up -d

# Health check
echo "Waiting for health check..."
for i in $(seq 1 30); do
  if curl -sf http://localhost:8000/api/health > /dev/null 2>&1; then
    echo "=== AgenticOps Running: $(date) ==="
    exit 0
  fi
  sleep 2
done
echo "WARNING: Health check timed out"
docker compose -f /opt/agenticops/docker-compose.yml logs --tail 20
