# AgenticOps — AWS Singapore Deployment

One-click deployment of AgenticOps to AWS ap-southeast-1 using Terraform.

## Architecture

```
User → agenticops.tinyboat.blog (Route53)
     → CloudFront (SSL: *.tinyboat.blog ACM cert)
     → ALB (HTTP, CloudFront-only ingress)
     → EC2 c5.xlarge (public subnet, SSH enabled)
         ├── uvicorn (port 8000, 2 workers)
         ├── Feishu WebSocket bot
         └── Slack Socket Mode bot
```

## Prerequisites

- AWS CLI configured (`aws configure` or `AWS_PROFILE`)
- Terraform >= 1.5
- SSH key at `~/.ssh/id_rsa.pub` (auto-imported as AWS key pair)

## Quick Start

```bash
cd iac/deploy-sg

# First time: initialize Terraform
terraform init

# Deploy everything (infra + app setup)
./deploy.sh apply

# Subsequent code updates
./deploy.sh redeploy [branch]
```

## Commands

| Command | Description |
|---------|-------------|
| `./deploy.sh apply` | Create all infrastructure + run initial app setup |
| `./deploy.sh plan` | Preview Terraform changes (dry run) |
| `./deploy.sh setup` | Re-run full setup on existing instance |
| `./deploy.sh redeploy [branch]` | Git pull + rebuild + restart (default: main) |
| `./deploy.sh destroy` | Tear down all AWS resources |

## Access

| Method | Command |
|--------|---------|
| Web (CloudFront, always reachable) | `terraform output -raw cloudfront_url` (e.g. `https://d1o50vxhknqf6d.cloudfront.net`) |
| Web (custom domain, optional) | https://agenticops.tinyboat.blog — requires a **live** domain + DNS pointing at CloudFront |
| SSH | `ssh ubuntu@$(terraform output -raw ec2_public_ip)` |
| SSM | `aws ssm start-session --target $(terraform output -raw ec2_instance_id) --region ap-southeast-1` |
| Logs | `journalctl -u agenticops -f` |
| Login | admin / aiops2026 |

> The EC2 public IP is **auto-assigned and changes on stop/start** — always derive it from `terraform output` (run `terraform apply -refresh-only -auto-approve` first if the instance was restarted), never hard-code it. Drive redeploys via `./deploy.sh redeploy` (SSM + instance ID), which doesn't depend on the IP. The custom domain currently depends on an external domain registration being live; until then use the CloudFront URL.

## Infrastructure Components

| Resource | Details |
|----------|---------|
| VPC | 10.0.0.0/16, 2 AZs, public + private subnets, single NAT GW |
| EC2 | c5.xlarge, Ubuntu 24.04, public subnet, EBS 30GB gp3 |
| ALB | Internal, CloudFront-only ingress (managed prefix list) |
| CloudFront | PriceClass_200, custom domain + ACM wildcard cert |
| Route53 | A ALIAS record → CloudFront |
| Security Groups | ALB: port 80 from CF; EC2: port 8000 from ALB + port 22 SSH |
| IAM Role | SSM, ReadOnlyAccess, Bedrock, SES, SNS, STS AssumeRole |

## Configuration

Key variables in `variables.tf` (override with `terraform.tfvars` or `-var`):

| Variable | Default | Description |
|----------|---------|-------------|
| `instance_type` | c5.xlarge | EC2 instance type |
| `domain_name` | agenticops.tinyboat.blog | Custom domain |
| `acm_certificate_arn` | *.tinyboat.blog wildcard | ACM cert (must be us-east-1) |
| `bedrock_region` | us-east-1 | Bedrock LLM region |
| `bedrock_model_id` | claude-opus-4-6 | Default model |
| `git_branch` | main | Branch to deploy |
| `ssh_allowed_cidrs` | ["0.0.0.0/0"] | Restrict SSH access |
| `app_port` | 8000 | Application port |

## App Stack on Instance

| Component | Version | Path |
|-----------|---------|------|
| Python | 3.12 | `/opt/uv-python/` |
| uv / uvx | latest | `/usr/local/bin/` |
| Node.js | 20.x | system |
| App code | git clone | `/opt/agenticops/` |
| Venv | uv managed | `/opt/agenticops/.venv/` |
| Service | systemd | `agenticops.service` |
| Config | env file | `/etc/agenticops.env` |
| Database | SQLite | `/opt/agenticops/data/agenticops.db` |

## Service User

- User: `agenticops` (runs the systemd service)
- Sudo: passwordless (`/etc/sudoers.d/agenticops`)
- AWS credentials: `/home/agenticops/.aws/credentials` (if configured)

## Troubleshooting

```bash
# Service status
sudo systemctl status agenticops

# Application logs
sudo journalctl -u agenticops -f

# Restart service
sudo systemctl restart agenticops

# Check MCP servers config
cat /opt/agenticops/config/mcp-servers.json

# Manual health check
curl http://localhost:8000/api/health | jq .
```
