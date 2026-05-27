# AgenticOps Docker + Terraform Deployment Design

**Date**: 2026-05-27
**Status**: Approved
**Goal**: 一个 Docker Image，三种 Terraform 部署模式（EC2/ECS/EKS），用户只需填 `terraform.tfvars` 即可完成部署。

---

## 设计原则

1. **Docker Image 是唯一交付物** — 不再在目标机器上跑 git clone + pip install
2. **Bring Your Own** — VPC、EKS 集群、域名、ACM 证书均可外部传入
3. **零交互部署** — `terraform init && terraform apply` 一条链路完成
4. **渐进复杂度** — 默认值覆盖 80% 场景，高级用户通过变量覆盖

---

## 架构总览

```
┌─────────────────────────────────────────────────────┐
│  Dockerfile (multi-stage)                           │
│  Node build → Python runtime → agenticops:tag       │
└──────────────────────┬──────────────────────────────┘
                       │ docker push
                       ▼
              ┌─────────────────┐
              │   AWS ECR       │
              │   (Terraform    │
              │    自动创建)     │
              └────────┬────────┘
                       │ docker pull
          ┌────────────┼────────────┐
          ▼            ▼            ▼
   iac/ec2/       iac/ecs/      iac/eks/
   docker-compose  Fargate       Helm/K8s
   on EC2          Task          Deployment
```

---

## 目录结构

```
iac/
├── modules/                     # 共享子模块（按需引用）
│   ├── ecr/                     # ECR repo + lifecycle
│   ├── vpc/                     # VPC（仅当用户不提供时创建）
│   ├── rds/                     # RDS PostgreSQL（可选）
│   ├── alb/                     # ALB + listener + TG
│   ├── dns/                     # Route53 A/ALIAS record
│   └── iam/                     # IAM role/policy（Bedrock + S3 + SES）
├── ec2/                         # EC2 Docker 部署
│   ├── main.tf
│   ├── variables.tf
│   ├── outputs.tf
│   ├── templates/
│   │   ├── user-data.sh.tpl    # 安装 docker + pull image + compose up
│   │   ├── docker-compose.yml.tpl
│   │   └── env.tpl             # .env 模板
│   └── terraform.tfvars.example
├── ecs/                         # ECS Fargate 部署
│   ├── main.tf
│   ├── variables.tf
│   ├── outputs.tf
│   ├── templates/
│   │   └── task-definition.json.tpl
│   └── terraform.tfvars.example
├── eks/                         # EKS 部署（支持已有集群）
│   ├── main.tf
│   ├── variables.tf
│   ├── outputs.tf
│   ├── templates/
│   │   └── helm-values.yaml.tpl
│   └── terraform.tfvars.example
├── Makefile                     # make build / make push / make deploy-ec2
└── Dockerfile                   # 项目根目录的 Dockerfile
```

---

## Dockerfile

```dockerfile
# Stage 1: Frontend
FROM node:20-alpine AS frontend
WORKDIR /build
COPY src/agenticops/web/frontend/package*.json ./
RUN npm ci --silent
COPY src/agenticops/web/frontend/ ./
RUN npm run build

# Stage 2: Runtime
FROM python:3.12-slim AS runtime
RUN apt-get update && apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir uv

WORKDIR /app
COPY pyproject.toml ./
RUN uv pip install --system ".[im,files,reports]"
COPY src/ ./src/
COPY config/settings.yaml ./config/settings.yaml
COPY skills/ ./skills/
COPY agent-memory/ ./agent-memory/
COPY --from=frontend /build/dist ./src/agenticops/web/frontend/dist

# MCP: 不安装 uvx，cloud 模式下仅支持 SSE transport
ENV AIOPS_DEPLOYMENT_PROFILE=cloud
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD curl -sf http://localhost:8000/api/health || exit 1

CMD ["python", "-m", "uvicorn", "agenticops.web.app:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "4", "--timeout-keep-alive", "30"]
```

---

## 共享变量接口

三个部署模块共享相同的核心变量名，用户切换 target 时只需换目录，tfvars 可复用。

### 必填（无合理默认值）

| 变量 | 说明 | 示例 |
|------|------|------|
| `region` | 部署区域 | `ap-southeast-1` |
| `admin_password` | Web UI 管理员密码 | `MySecure123!` |

### 可选（有默认值）

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `project_name` | `agenticops` | 资源命名前缀 |
| `image_tag` | `latest` | Docker image tag |
| `bedrock_region` | `us-east-1` | Bedrock API 区域 |
| `bedrock_model` | `global.anthropic.claude-sonnet-4-6` | 主模型 |
| `bedrock_model_strong` | `global.anthropic.claude-opus-4-6-v1` | RCA/SRE 模型 |
| `bedrock_model_cheap` | `global.anthropic.claude-haiku-4-5-20251001-v1:0` | 经济模型 |

### Bring Your Own（传入则用，不传则创建）

| 变量 | 默认值 | 行为 |
|------|--------|------|
| `vpc_id` | `""` | 空 = 创建新 VPC；非空 = 使用已有 |
| `subnet_ids` | `[]` | 空 = 自动选 VPC 内子网；非空 = 指定 |
| `eks_cluster_name` | `""` | 仅 eks/ 模块：空 = 创建新集群；非空 = 部署到已有集群 |
| `domain_name` | `""` | 空 = 不配域名；非空 = 创建 ALB + DNS |
| `acm_cert_arn` | `""` | 空 = 自动申请（需 Route53）；非空 = 使用已有 |
| `route53_zone_id` | `""` | 空 = 不创建 DNS 记录；非空 = 创建 A record |
| `alb_internal` | `false` | `true` = 内网 ALB，`false` = 外网 |

### 数据库

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `db_backend` | `sqlite` | `sqlite` 或 `rds` |
| `rds_instance_class` | `db.t3.medium` | RDS 实例规格 |
| `rds_allocated_storage` | `20` | GB |
| `rds_password` | `""` | 空 = 自动生成存 SSM Parameter |

### EC2 专有

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `instance_type` | `c5.xlarge` | EC2 实例类型 |
| `ssh_public_key_path` | `~/.ssh/id_rsa.pub` | SSH 公钥路径 |
| `ssh_enabled` | `true` | 是否开放 22 端口 |

### ECS 专有

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `cpu` | `2048` | Fargate vCPU（1024=1核） |
| `memory` | `4096` | Fargate 内存 MB |
| `desired_count` | `1` | 任务副本数 |

### EKS 专有

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `namespace` | `agenticops` | K8s namespace |
| `replicas` | `1` | Pod 副本数 |
| `node_selector` | `{}` | 节点选择器 |

---

## 部署流程

### 用户最小操作（EC2 为例）

```bash
# 1. 配置 AWS 凭证（已有则跳过）
export AWS_PROFILE=my-profile

# 2. 填写配置
cd iac/ec2
cp terraform.tfvars.example terraform.tfvars
# 编辑: region, admin_password（其余全用默认值）

# 3. 构建并推送 image（首次）
make build push

# 4. 部署
terraform init
terraform apply

# 5. 输出
# => URL: https://agenticops.example.com
# => SSH: ssh ubuntu@1.2.3.4
# => Health: curl https://agenticops.example.com/api/health
```

### 已有 VPC + 域名的场景

```hcl
# terraform.tfvars
region           = "ap-southeast-1"
admin_password   = "MyPassword123"
vpc_id           = "vpc-0abc123def456"     # 已有 VPC
subnet_ids       = ["subnet-aaa", "subnet-bbb"]
domain_name      = "ops.company.com"       # 已有域名
acm_cert_arn     = "arn:aws:acm:..."       # 已有证书
route53_zone_id  = "Z1234567890"           # 已有 hosted zone
```

### 已有 EKS 集群的场景

```hcl
# iac/eks/terraform.tfvars
region            = "ap-southeast-1"
admin_password    = "MyPassword123"
eks_cluster_name  = "my-existing-cluster"  # 已有集群
namespace         = "ops"
domain_name       = "ops.company.com"
```

---

## 共享模块设计

### modules/ecr/

```hcl
# 输入: project_name, region
# 输出: repository_url, registry_id
# 逻辑: 创建 ECR repo + lifecycle policy (保留最近 10 个 image)
```

### modules/vpc/

```hcl
# 输入: project_name, vpc_id (可选)
# 输出: vpc_id, public_subnet_ids, private_subnet_ids
# 逻辑: 
#   vpc_id == "" → 创建 VPC + 2 public + 2 private subnets + NAT
#   vpc_id != "" → data source 读取已有 VPC，自动发现 subnets
#                  若 subnet_ids 也传了则直接使用
```

### modules/alb/

```hcl
# 输入: vpc_id, subnet_ids, domain_name, acm_cert_arn, internal, target_port
# 输出: alb_dns, alb_arn, target_group_arn, listener_arn
# 逻辑:
#   domain_name == "" → 只创建 HTTP ALB
#   domain_name != "" && acm_cert_arn == "" → 自动申请 ACM + DNS 验证
#   domain_name != "" && acm_cert_arn != "" → 使用已有证书
#   internal = true → scheme = internal
```

### modules/rds/ (条件创建)

```hcl
# 输入: enabled, vpc_id, subnet_ids, instance_class, password
# 输出: endpoint, database_url
# 逻辑: enabled=false 时不创建任何资源 (count=0)
```

### modules/iam/

```hcl
# 输入: project_name, services (ec2/ecs/eks)
# 输出: role_arn, instance_profile_name
# 逻辑: 创建 IAM Role with policies:
#   - Bedrock InvokeModel
#   - ECR Pull
#   - S3 (reports bucket)
#   - SES SendEmail
#   - CloudWatch Logs
#   - SSM GetParameter (if RDS password in SSM)
```

---

## EC2 模块细节

**user-data.sh.tpl** 做的事（极简）：

```bash
#!/bin/bash
# 1. 安装 Docker + docker-compose
# 2. ECR login
# 3. 写入 .env 和 docker-compose.yml（Terraform templatefile 渲染）
# 4. docker compose up -d
# 5. 等待 health check
```

不再有 git clone、pip install、npm build、systemd unit 等步骤。

**docker-compose.yml.tpl**：

```yaml
services:
  agenticops:
    image: ${image_uri}
    env_file: /opt/agenticops/.env
    ports:
      - "8000:8000"
    volumes:
      - /opt/agenticops/data:/app/data
    restart: always
    logging:
      driver: awslogs
      options:
        awslogs-region: ${region}
        awslogs-group: /agenticops
        awslogs-stream-prefix: app
```

---

## ECS 模块细节

- ECS Cluster (Fargate)
- Task Definition: image from ECR, env vars, log config
- Service: desired_count, ALB target group attachment
- Auto Scaling (可选): target tracking on CPU

---

## EKS 模块细节

- 已有集群: `data "aws_eks_cluster"` + `kubernetes` provider
- 新集群: `module "eks"` (terraform-aws-modules/eks)
- 部署方式: Helm chart 或直接 `kubernetes_deployment` resource
- Namespace + ServiceAccount + IRSA (IAM Roles for Service Accounts)

---

## Makefile

```makefile
REGION     ?= ap-southeast-1
PROJECT    ?= agenticops
TAG        ?= $(shell git rev-parse --short HEAD)
ECR_REPO   = $(shell terraform -chdir=iac/ec2 output -raw ecr_repository_url 2>/dev/null)

.PHONY: build push deploy-ec2 deploy-ecs deploy-eks

build:
	docker build -t $(PROJECT):$(TAG) -t $(PROJECT):latest .

push: build
	aws ecr get-login-password --region $(REGION) | docker login --username AWS --password-stdin $(ECR_REPO)
	docker tag $(PROJECT):$(TAG) $(ECR_REPO):$(TAG)
	docker tag $(PROJECT):latest $(ECR_REPO):latest
	docker push $(ECR_REPO):$(TAG)
	docker push $(ECR_REPO):latest

deploy-ec2:
	cd iac/ec2 && terraform init && terraform apply -auto-approve

deploy-ecs:
	cd iac/ecs && terraform init && terraform apply -auto-approve

deploy-eks:
	cd iac/eks && terraform init && terraform apply -auto-approve
```

---

## 配置注入（.env）

Terraform 使用 `templatefile()` 生成 `.env`，内容：

```bash
AIOPS_DEPLOYMENT_PROFILE=cloud
AIOPS_BEDROCK_REGION=${bedrock_region}
AIOPS_BEDROCK_MODEL_ID=${bedrock_model}
AIOPS_BEDROCK_MODEL_ID_STRONG=${bedrock_model_strong}
AIOPS_BEDROCK_MODEL_ID_CHEAP=${bedrock_model_cheap}
AIOPS_DATABASE_URL=${database_url}
AIOPS_API_AUTH_ENABLED=true
AIOPS_ADMIN_PASSWORD=${admin_password}
AIOPS_REPORT_STORAGE=s3
AIOPS_REPORT_S3_BUCKET=${s3_bucket}
AIOPS_S3_REGION=${region}
```

EC2: 写入文件 `/opt/agenticops/.env`
ECS: Task Definition `environment` block
EKS: ConfigMap/Secret → env injection

---

## 迁移策略

1. 保留 `iac/deploy-sg/` 不动（当前生产，后续废弃）
2. 新建 `iac/modules/`、`iac/ec2/`、`iac/ecs/`、`iac/eks/`
3. 根目录新建 `Dockerfile`、更新 `Makefile`
4. 新部署验证通过后，旧 `iac/deploy-sg/` 标记 deprecated

---

## 不做的事

- 不做 CI/CD pipeline 定义（用户自行 GitHub Actions / CodePipeline）
- 不做多租户/多环境 workspace（用户按需复制 tfvars）
- 不做 Helm chart 发布到 chart repo（直接 Terraform helm_release）
- 不做 CloudFormation 兼容（全 Terraform）
- 不做 MCP stdio transport in cloud（只支持 SSE）
