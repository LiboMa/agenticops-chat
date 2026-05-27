# AgenticOps — ECS Fargate Deployment

Deploy AgenticOps as a Fargate task with ALB (HTTPS 443).

## Prerequisites

- AWS CLI configured
- Terraform >= 1.5
- Docker
- ACM certificate in the deployment region

## Deploy

```bash
# 1. Configure
cp terraform.tfvars.example terraform.tfvars
# Edit: region, admin_password, acm_cert_arn

# 2. Create ECR
terraform init
terraform apply -target=module.ecr -auto-approve

# 3. Build and push Docker image
ECR_REPO=$(terraform output -raw ecr_repository_url)
aws ecr get-login-password --region ap-southeast-1 | docker login --username AWS --password-stdin $ECR_REPO
docker build -t agenticops ../../
docker tag agenticops:latest $ECR_REPO:latest
docker push $ECR_REPO:latest

# 4. Deploy all
terraform apply -auto-approve

# 5. Verify
terraform output
```

## Update

```bash
ECR_REPO=$(terraform output -raw ecr_repository_url)
docker build -t agenticops ../../
docker tag agenticops:latest $ECR_REPO:latest
docker push $ECR_REPO:latest

# Force new deployment to pull latest image
aws ecs update-service --cluster $(terraform output -raw cluster_name) \
  --service $(terraform output -raw service_name) --force-new-deployment --region ap-southeast-1
```

## Destroy

```bash
terraform destroy -auto-approve
```

## Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `region` | Yes | `ap-southeast-1` | AWS region |
| `admin_password` | Yes | — | Web UI admin password |
| `acm_cert_arn` | Yes* | — | ACM cert for HTTPS |
| `cpu` | No | `2048` | Fargate vCPU (1024=1 core) |
| `memory` | No | `4096` | Fargate memory MB |
| `desired_count` | No | `1` | Task replicas |
| `alb_internal` | No | `false` | `true` = VPC internal only |
| `vpc_id` | No | `""` | Existing VPC |
| `db_backend` | No | `sqlite` | `sqlite` or `rds` |

## Architecture

```
Internet → ALB (443 HTTPS) → ECS Fargate Task (:8000)
                                    ↓
                              SQLite (ephemeral) or RDS
```

Note: With `db_backend=sqlite`, data is lost on task restart. Use `rds` for persistence.
