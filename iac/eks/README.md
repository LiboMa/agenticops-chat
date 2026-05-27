# AgenticOps — EKS Deployment

Deploy AgenticOps to an EKS cluster (existing or new).

## Prerequisites

- AWS CLI configured
- Terraform >= 1.5
- Docker
- kubectl configured for target cluster (if using existing)
- ACM certificate for HTTPS LoadBalancer

## Deploy (Existing Cluster)

```bash
# 1. Configure
cp terraform.tfvars.example terraform.tfvars
# Edit: region, admin_password, acm_cert_arn, eks_cluster_name

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
kubectl get pods -n $(terraform output -raw namespace)
terraform output
```

## Update

```bash
ECR_REPO=$(terraform output -raw ecr_repository_url)
docker build -t agenticops ../../
docker tag agenticops:latest $ECR_REPO:latest
docker push $ECR_REPO:latest

# Rollout restart
kubectl rollout restart deployment/agenticops -n $(terraform output -raw namespace)
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
| `acm_cert_arn` | Yes | — | ACM cert for LoadBalancer HTTPS |
| `eks_cluster_name` | No | `""` | Existing cluster (creates new if empty) |
| `namespace` | No | `agenticops` | K8s namespace |
| `replicas` | No | `1` | Pod replicas |
| `alb_internal` | No | `false` | `true` = internal LB |
| `vpc_id` | No | `""` | Existing VPC (for new cluster) |
| `db_backend` | No | `sqlite` | `sqlite` or `rds` |

## Architecture

```
Internet → NLB (443 HTTPS, AWS LB Controller) → K8s Service → Pod (:8000)
                                                                  ↓
                                                            emptyDir or RDS
```

For production with SQLite, mount a PersistentVolumeClaim (EBS CSI) instead of emptyDir.
