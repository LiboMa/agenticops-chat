# AgenticOps — EC2 Docker Deployment

Deploy AgenticOps as a Docker container on a single EC2 instance with ALB (HTTPS 443).

## Prerequisites

- AWS CLI configured (`aws sts get-caller-identity` works)
- Terraform >= 1.5
- Docker
- ACM certificate in the deployment region (or domain + Route53 zone for auto-creation)

## Deploy

```bash
# 1. Configure
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars: region, admin_password, acm_cert_arn

# 2. Create ECR (image registry)
terraform init
terraform apply -target=module.ecr -auto-approve

# 3. Build and push Docker image
ECR_REPO=$(terraform output -raw ecr_repository_url)
REGISTRY=$(echo $ECR_REPO | cut -d'/' -f1)
aws ecr get-login-password --region ap-southeast-1 | docker login --username AWS --password-stdin $REGISTRY
docker build -f ../../docker/Dockerfile -t agenticops:latest ../../
docker tag agenticops:latest $ECR_REPO:latest
docker push $ECR_REPO:latest

# 4. Deploy all infrastructure
terraform apply -auto-approve

# 5. Verify
terraform output
```

## Update (code changes)

```bash
ECR_REPO=$(terraform output -raw ecr_repository_url)
REGISTRY=$(echo $ECR_REPO | cut -d'/' -f1)
aws ecr get-login-password --region ap-southeast-1 | docker login --username AWS --password-stdin $REGISTRY
docker build -f ../../docker/Dockerfile -t agenticops:latest ../../
docker tag agenticops:latest $ECR_REPO:latest
docker push $ECR_REPO:latest

# SSH into EC2 and restart container:
ssh ubuntu@$(terraform output -raw public_ip) \
  "docker pull $ECR_REPO:latest && docker restart agenticops"
```

## Destroy

```bash
terraform destroy -auto-approve
```

## Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `region` | Yes | `ap-southeast-1` | AWS deployment region |
| `admin_password` | Yes | — | Web UI admin password |
| `acm_cert_arn` | Yes* | — | ACM cert for HTTPS. *Auto-created if domain+zone set |
| `project_name` | No | `agenticops` | Resource naming prefix |
| `instance_type` | No | `c5.xlarge` | EC2 instance type |
| `alb_internal` | No | `false` | `true` = VPC internal only |
| `vpc_id` | No | `""` | Existing VPC (creates new if empty) |
| `domain_name` | No | `""` | Custom domain for DNS record |
| `route53_zone_id` | No | `""` | Route53 zone for DNS + auto-cert |
| `db_backend` | No | `sqlite` | `sqlite` or `rds` |
| `ssh_enabled` | No | `false` | Open port 22 |

## Architecture

```
Internet → ALB (443 HTTPS) → EC2 (Docker container :8000)
                                    ↓
                              SQLite /app/data (EBS volume)
                              or RDS PostgreSQL (optional)
```

All resources created: VPC, subnets, IGW, NAT, ALB, EC2, SG, IAM, ECR.
Set `vpc_id` to use an existing VPC instead.
Set `alb_internal = true` for VPC-only access (no public exposure).
