# Docker + Terraform Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Docker image as the sole deployment artifact, with three independent Terraform modules (EC2/ECS/EKS) that each deploy the image with a single `terraform apply`.

**Architecture:** Multi-stage Dockerfile builds frontend + backend into one image, pushed to ECR. Three Terraform root modules in `iac/ec2/`, `iac/ecs/`, `iac/eks/` share reusable sub-modules (`iac/modules/`). All use "bring your own" pattern for VPC/domain/cluster.

**Tech Stack:** Docker, Terraform >= 1.5, AWS (ECR, EC2, ECS Fargate, EKS, ALB, Route53, ACM, RDS, IAM)

---

## File Structure

```
# New files (root)
Dockerfile                          # Multi-stage: node build + python runtime
.dockerignore                       # Exclude .git, node_modules, .venv, etc.
Makefile                            # build / push / deploy-ec2 / deploy-ecs / deploy-eks

# Shared Terraform modules
iac/modules/ecr/main.tf             # ECR repo + lifecycle policy
iac/modules/ecr/variables.tf
iac/modules/ecr/outputs.tf
iac/modules/vpc/main.tf             # VPC (create or bring-your-own)
iac/modules/vpc/variables.tf
iac/modules/vpc/outputs.tf
iac/modules/alb/main.tf             # ALB + HTTPS + target group
iac/modules/alb/variables.tf
iac/modules/alb/outputs.tf
iac/modules/rds/main.tf             # RDS PostgreSQL (conditional)
iac/modules/rds/variables.tf
iac/modules/rds/outputs.tf
iac/modules/iam/main.tf             # IAM role + policies
iac/modules/iam/variables.tf
iac/modules/iam/outputs.tf
iac/modules/dns/main.tf             # Route53 record (conditional)
iac/modules/dns/variables.tf
iac/modules/dns/outputs.tf

# EC2 deployment
iac/ec2/main.tf                     # Orchestrates modules + EC2 instance
iac/ec2/variables.tf                # Shared + EC2-specific vars
iac/ec2/outputs.tf
iac/ec2/versions.tf                 # Provider requirements
iac/ec2/templates/user-data.sh.tpl  # Install docker, pull image, compose up
iac/ec2/templates/docker-compose.yml.tpl
iac/ec2/templates/env.tpl
iac/ec2/terraform.tfvars.example

# ECS deployment
iac/ecs/main.tf                     # Orchestrates modules + ECS cluster/service
iac/ecs/variables.tf
iac/ecs/outputs.tf
iac/ecs/versions.tf
iac/ecs/terraform.tfvars.example

# EKS deployment
iac/eks/main.tf                     # Orchestrates modules + K8s resources
iac/eks/variables.tf
iac/eks/outputs.tf
iac/eks/versions.tf
iac/eks/terraform.tfvars.example
```

---

### Task 1: Dockerfile + .dockerignore

**Files:**
- Modify: `Dockerfile`
- Create: `.dockerignore`

- [ ] **Step 1: Create .dockerignore**

```
.git
.github
.venv
__pycache__
*.pyc
node_modules
.terraform
*.tfstate*
.env
.hypothesis
.playwright-mcp
data/
infra/
iac/
docs/
tests/
*.md
!skills/**/*.md
!agent-memory/**/*.md
!config/settings.yaml
```

- [ ] **Step 2: Rewrite Dockerfile (multi-stage with frontend build)**

```dockerfile
# =============================================================================
# AgenticOps — Production Container (multi-stage)
# =============================================================================

# Stage 1: Frontend build
FROM node:20-alpine AS frontend
WORKDIR /build
COPY src/agenticops/web/frontend/package*.json ./
RUN npm ci --silent
COPY src/agenticops/web/frontend/ ./
RUN npm run build

# Stage 2: Python runtime
FROM python:3.12-slim AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Install uv for fast pip
RUN pip install --no-cache-dir uv

# Create non-root user
RUN useradd -r -m -s /bin/bash agenticops

WORKDIR /app

# Install Python dependencies (cached layer)
COPY pyproject.toml ./
RUN uv pip install --system ".[im,files,reports]"

# Copy application code
COPY src/ ./src/
COPY config/settings.yaml ./config/settings.yaml
COPY skills/ ./skills/
COPY agent-memory/ ./agent-memory/

# Copy frontend build from stage 1
COPY --from=frontend /build/dist ./src/agenticops/web/frontend/dist

# Create data directory
RUN mkdir -p /app/data && chown -R agenticops:agenticops /app

# Empty MCP config (cloud mode — no stdio MCP)
RUN mkdir -p /app/config && echo '{"mcpServers": {}}' > /app/config/mcp-servers.json

USER agenticops

# Environment defaults
ENV AIOPS_DEPLOYMENT_PROFILE=cloud \
    AIOPS_DATABASE_URL=sqlite:////app/data/agenticops.db \
    AIOPS_API_AUTH_ENABLED=true

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -sf http://localhost:8000/api/health || exit 1

CMD ["python", "-m", "uvicorn", "agenticops.web.app:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "4", "--timeout-keep-alive", "30"]
```

- [ ] **Step 3: Build locally to verify**

Run: `docker build -t agenticops:test .`
Expected: Successful build, image ~1.5-2GB

- [ ] **Step 4: Test the image runs**

Run: `docker run --rm -p 8000:8000 -e AIOPS_ADMIN_PASSWORD=test123 agenticops:test`
Expected: Health check passes at http://localhost:8000/api/health

- [ ] **Step 5: Commit**

```bash
git add Dockerfile .dockerignore
git commit -m "feat(docker): multi-stage Dockerfile with frontend build"
```

---

### Task 2: Makefile

**Files:**
- Create: `Makefile`

- [ ] **Step 1: Create Makefile**

```makefile
# AgenticOps — Build & Deploy
REGION     ?= ap-southeast-1
PROJECT    ?= agenticops
TAG        ?= $(shell git rev-parse --short HEAD)
ECR_REPO   ?= $(shell cd iac/ec2 && terraform output -raw ecr_repository_url 2>/dev/null || echo "")

.PHONY: build push deploy-ec2 deploy-ecs deploy-eks clean

# --- Docker ---
build:
	docker build -t $(PROJECT):$(TAG) -t $(PROJECT):latest .

push:
	@if [ -z "$(ECR_REPO)" ]; then echo "ERROR: ECR_REPO not set. Run terraform apply first."; exit 1; fi
	aws ecr get-login-password --region $(REGION) | docker login --username AWS --password-stdin $(ECR_REPO)
	docker tag $(PROJECT):$(TAG) $(ECR_REPO):$(TAG)
	docker tag $(PROJECT):latest $(ECR_REPO):latest
	docker push $(ECR_REPO):$(TAG)
	docker push $(ECR_REPO):latest
	@echo "Pushed: $(ECR_REPO):$(TAG)"

# --- Terraform Deploy ---
deploy-ec2:
	cd iac/ec2 && terraform init -upgrade && terraform apply

deploy-ecs:
	cd iac/ecs && terraform init -upgrade && terraform apply

deploy-eks:
	cd iac/eks && terraform init -upgrade && terraform apply

# --- Cleanup ---
clean:
	docker rmi $(PROJECT):$(TAG) $(PROJECT):latest 2>/dev/null || true
```

- [ ] **Step 2: Commit**

```bash
git add Makefile
git commit -m "feat: add Makefile for build/push/deploy"
```

---

### Task 3: Shared Module — ECR

**Files:**
- Create: `iac/modules/ecr/main.tf`
- Create: `iac/modules/ecr/variables.tf`
- Create: `iac/modules/ecr/outputs.tf`

- [ ] **Step 1: Create iac/modules/ecr/variables.tf**

```hcl
variable "name" {
  description = "ECR repository name"
  type        = string
}

variable "tags" {
  description = "Resource tags"
  type        = map(string)
  default     = {}
}
```

- [ ] **Step 2: Create iac/modules/ecr/main.tf**

```hcl
resource "aws_ecr_repository" "this" {
  name                 = var.name
  image_tag_mutability = "MUTABLE"
  force_delete         = true

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = var.tags
}

resource "aws_ecr_lifecycle_policy" "this" {
  repository = aws_ecr_repository.this.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep last 10 images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = { type = "expire" }
    }]
  })
}
```

- [ ] **Step 3: Create iac/modules/ecr/outputs.tf**

```hcl
output "repository_url" {
  value = aws_ecr_repository.this.repository_url
}

output "registry_id" {
  value = aws_ecr_repository.this.registry_id
}

output "arn" {
  value = aws_ecr_repository.this.arn
}
```

- [ ] **Step 4: Commit**

```bash
git add iac/modules/ecr/
git commit -m "feat(iac): add ECR shared module"
```

---

### Task 4: Shared Module — VPC (bring-your-own or create)

**Files:**
- Create: `iac/modules/vpc/main.tf`
- Create: `iac/modules/vpc/variables.tf`
- Create: `iac/modules/vpc/outputs.tf`

- [ ] **Step 1: Create iac/modules/vpc/variables.tf**

```hcl
variable "project_name" {
  type = string
}

variable "vpc_id" {
  description = "Existing VPC ID. Empty = create new."
  type        = string
  default     = ""
}

variable "public_subnet_ids" {
  description = "Existing public subnet IDs (required if vpc_id set)"
  type        = list(string)
  default     = []
}

variable "private_subnet_ids" {
  description = "Existing private subnet IDs (required if vpc_id set)"
  type        = list(string)
  default     = []
}

variable "vpc_cidr" {
  description = "CIDR for new VPC"
  type        = string
  default     = "10.0.0.0/16"
}

variable "azs" {
  description = "Availability zones (auto-detected if empty)"
  type        = list(string)
  default     = []
}

variable "tags" {
  type    = map(string)
  default = {}
}
```

- [ ] **Step 2: Create iac/modules/vpc/main.tf**

```hcl
locals {
  create_vpc = var.vpc_id == ""
  azs        = length(var.azs) > 0 ? var.azs : slice(data.aws_availability_zones.available.names, 0, 2)
}

data "aws_availability_zones" "available" {
  state = "available"
}

# --- Use existing VPC ---
data "aws_vpc" "existing" {
  count = local.create_vpc ? 0 : 1
  id    = var.vpc_id
}

data "aws_subnets" "public" {
  count = local.create_vpc ? 0 : (length(var.public_subnet_ids) > 0 ? 0 : 1)
  filter {
    name   = "vpc-id"
    values = [var.vpc_id]
  }
  filter {
    name   = "map-public-ip-on-launch"
    values = ["true"]
  }
}

data "aws_subnets" "private" {
  count = local.create_vpc ? 0 : (length(var.private_subnet_ids) > 0 ? 0 : 1)
  filter {
    name   = "vpc-id"
    values = [var.vpc_id]
  }
  filter {
    name   = "map-public-ip-on-launch"
    values = ["false"]
  }
}

# --- Create new VPC ---
resource "aws_vpc" "this" {
  count                = local.create_vpc ? 1 : 0
  cidr_block           = var.vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true
  tags                 = merge(var.tags, { Name = "${var.project_name}-vpc" })
}

resource "aws_internet_gateway" "this" {
  count  = local.create_vpc ? 1 : 0
  vpc_id = aws_vpc.this[0].id
  tags   = merge(var.tags, { Name = "${var.project_name}-igw" })
}

resource "aws_subnet" "public" {
  count                   = local.create_vpc ? 2 : 0
  vpc_id                  = aws_vpc.this[0].id
  cidr_block              = cidrsubnet(var.vpc_cidr, 8, count.index)
  availability_zone       = local.azs[count.index]
  map_public_ip_on_launch = true
  tags                    = merge(var.tags, { Name = "${var.project_name}-public-${count.index}" })
}

resource "aws_subnet" "private" {
  count             = local.create_vpc ? 2 : 0
  vpc_id            = aws_vpc.this[0].id
  cidr_block        = cidrsubnet(var.vpc_cidr, 8, count.index + 10)
  availability_zone = local.azs[count.index]
  tags              = merge(var.tags, { Name = "${var.project_name}-private-${count.index}" })
}

resource "aws_route_table" "public" {
  count  = local.create_vpc ? 1 : 0
  vpc_id = aws_vpc.this[0].id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.this[0].id
  }
  tags = merge(var.tags, { Name = "${var.project_name}-public-rt" })
}

resource "aws_route_table_association" "public" {
  count          = local.create_vpc ? 2 : 0
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public[0].id
}

# NAT Gateway for private subnets
resource "aws_eip" "nat" {
  count  = local.create_vpc ? 1 : 0
  domain = "vpc"
  tags   = merge(var.tags, { Name = "${var.project_name}-nat-eip" })
}

resource "aws_nat_gateway" "this" {
  count         = local.create_vpc ? 1 : 0
  allocation_id = aws_eip.nat[0].id
  subnet_id     = aws_subnet.public[0].id
  tags          = merge(var.tags, { Name = "${var.project_name}-nat" })
}

resource "aws_route_table" "private" {
  count  = local.create_vpc ? 1 : 0
  vpc_id = aws_vpc.this[0].id
  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.this[0].id
  }
  tags = merge(var.tags, { Name = "${var.project_name}-private-rt" })
}

resource "aws_route_table_association" "private" {
  count          = local.create_vpc ? 2 : 0
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private[0].id
}
```

- [ ] **Step 3: Create iac/modules/vpc/outputs.tf**

```hcl
output "vpc_id" {
  value = local.create_vpc ? aws_vpc.this[0].id : var.vpc_id
}

output "public_subnet_ids" {
  value = local.create_vpc ? aws_subnet.public[*].id : (
    length(var.public_subnet_ids) > 0 ? var.public_subnet_ids : try(data.aws_subnets.public[0].ids, [])
  )
}

output "private_subnet_ids" {
  value = local.create_vpc ? aws_subnet.private[*].id : (
    length(var.private_subnet_ids) > 0 ? var.private_subnet_ids : try(data.aws_subnets.private[0].ids, [])
  )
}
```

- [ ] **Step 4: Commit**

```bash
git add iac/modules/vpc/
git commit -m "feat(iac): add VPC shared module (create or bring-your-own)"
```

---

### Task 5: Shared Module — IAM

**Files:**
- Create: `iac/modules/iam/main.tf`
- Create: `iac/modules/iam/variables.tf`
- Create: `iac/modules/iam/outputs.tf`

- [ ] **Step 1: Create iac/modules/iam/variables.tf**

```hcl
variable "project_name" {
  type = string
}

variable "service" {
  description = "Service type: ec2, ecs, or eks"
  type        = string
}

variable "tags" {
  type    = map(string)
  default = {}
}
```

- [ ] **Step 2: Create iac/modules/iam/main.tf**

```hcl
locals {
  assume_role_service = {
    ec2 = "ec2.amazonaws.com"
    ecs = "ecs-tasks.amazonaws.com"
    eks = "eks.amazonaws.com"
  }
}

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

resource "aws_iam_role" "this" {
  name = "${var.project_name}-${var.service}-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = local.assume_role_service[var.service] }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = var.tags
}

resource "aws_iam_role_policy" "app" {
  name = "${var.project_name}-app-policy"
  role = aws_iam_role.this.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "Bedrock"
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel",
          "bedrock:InvokeModelWithResponseStream"
        ]
        Resource = "*"
      },
      {
        Sid    = "ECR"
        Effect = "Allow"
        Action = [
          "ecr:GetAuthorizationToken",
          "ecr:BatchGetImage",
          "ecr:GetDownloadUrlForLayer"
        ]
        Resource = "*"
      },
      {
        Sid    = "S3"
        Effect = "Allow"
        Action = ["s3:*"]
        Resource = [
          "arn:aws:s3:::${var.project_name}-*",
          "arn:aws:s3:::${var.project_name}-*/*"
        ]
      },
      {
        Sid      = "SES"
        Effect   = "Allow"
        Action   = ["ses:SendEmail", "ses:SendRawEmail"]
        Resource = "*"
      },
      {
        Sid    = "CloudWatch"
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents",
          "logs:DescribeLogGroups",
          "logs:DescribeLogStreams",
          "cloudwatch:GetMetricData",
          "cloudwatch:ListMetrics"
        ]
        Resource = "*"
      },
      {
        Sid    = "SSM"
        Effect = "Allow"
        Action = ["ssm:GetParameter", "ssm:GetParameters"]
        Resource = "arn:aws:ssm:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:parameter/${var.project_name}/*"
      },
      {
        Sid    = "STS"
        Effect = "Allow"
        Action = ["sts:AssumeRole", "sts:GetCallerIdentity"]
        Resource = "*"
      }
    ]
  })
}

# EC2 instance profile
resource "aws_iam_instance_profile" "this" {
  count = var.service == "ec2" ? 1 : 0
  name  = "${var.project_name}-${var.service}-profile"
  role  = aws_iam_role.this.name
}
```

- [ ] **Step 3: Create iac/modules/iam/outputs.tf**

```hcl
output "role_arn" {
  value = aws_iam_role.this.arn
}

output "role_name" {
  value = aws_iam_role.this.name
}

output "instance_profile_name" {
  value = var.service == "ec2" ? aws_iam_instance_profile.this[0].name : ""
}
```

- [ ] **Step 4: Commit**

```bash
git add iac/modules/iam/
git commit -m "feat(iac): add IAM shared module (ec2/ecs/eks)"
```

---

### Task 6: Shared Module — ALB

**Files:**
- Create: `iac/modules/alb/main.tf`
- Create: `iac/modules/alb/variables.tf`
- Create: `iac/modules/alb/outputs.tf`

- [ ] **Step 1: Create iac/modules/alb/variables.tf**

```hcl
variable "project_name" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "subnet_ids" {
  type = list(string)
}

variable "domain_name" {
  description = "Domain name. Empty = HTTP only."
  type        = string
  default     = ""
}

variable "acm_cert_arn" {
  description = "ACM certificate ARN. Empty + domain set = auto-create."
  type        = string
  default     = ""
}

variable "route53_zone_id" {
  description = "Route53 zone ID for ACM DNS validation"
  type        = string
  default     = ""
}

variable "internal" {
  description = "Internal ALB (true) or internet-facing (false)"
  type        = bool
  default     = false
}

variable "target_port" {
  type    = number
  default = 8000
}

variable "health_check_path" {
  type    = string
  default = "/api/health"
}

variable "tags" {
  type    = map(string)
  default = {}
}
```

- [ ] **Step 2: Create iac/modules/alb/main.tf**

```hcl
locals {
  enable_https = var.domain_name != ""
  create_cert  = local.enable_https && var.acm_cert_arn == ""
  cert_arn     = local.create_cert ? aws_acm_certificate.this[0].arn : var.acm_cert_arn
}

# --- Security Group ---
resource "aws_security_group" "alb" {
  name_prefix = "${var.project_name}-alb-"
  vpc_id      = var.vpc_id

  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  dynamic "ingress" {
    for_each = local.enable_https ? [1] : []
    content {
      from_port   = 443
      to_port     = 443
      protocol    = "tcp"
      cidr_blocks = ["0.0.0.0/0"]
    }
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = var.tags

  lifecycle { create_before_destroy = true }
}

# --- ALB ---
resource "aws_lb" "this" {
  name               = "${var.project_name}-alb"
  internal           = var.internal
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = var.subnet_ids
  tags               = var.tags
}

resource "aws_lb_target_group" "this" {
  name        = "${var.project_name}-tg"
  port        = var.target_port
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip"

  health_check {
    path                = var.health_check_path
    healthy_threshold   = 2
    unhealthy_threshold = 3
    interval            = 30
    timeout             = 5
  }

  tags = var.tags
}

# --- HTTP Listener ---
resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.this.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = local.enable_https ? "redirect" : "forward"

    dynamic "redirect" {
      for_each = local.enable_https ? [1] : []
      content {
        port        = "443"
        protocol    = "HTTPS"
        status_code = "HTTP_301"
      }
    }

    dynamic "forward" {
      for_each = local.enable_https ? [] : [1]
      content {
        target_group { arn = aws_lb_target_group.this.arn }
      }
    }
  }
}

# --- HTTPS Listener ---
resource "aws_lb_listener" "https" {
  count             = local.enable_https ? 1 : 0
  load_balancer_arn = aws_lb.this.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = local.cert_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.this.arn
  }
}

# --- ACM Certificate (auto-create) ---
resource "aws_acm_certificate" "this" {
  count             = local.create_cert ? 1 : 0
  domain_name       = var.domain_name
  validation_method = "DNS"
  tags              = var.tags

  lifecycle { create_before_destroy = true }
}

resource "aws_route53_record" "cert_validation" {
  for_each = local.create_cert ? {
    for dvo in aws_acm_certificate.this[0].domain_validation_options : dvo.domain_name => {
      name   = dvo.resource_record_name
      type   = dvo.resource_record_type
      record = dvo.resource_record_value
    }
  } : {}

  zone_id = var.route53_zone_id
  name    = each.value.name
  type    = each.value.type
  records = [each.value.record]
  ttl     = 60
}

resource "aws_acm_certificate_validation" "this" {
  count                   = local.create_cert ? 1 : 0
  certificate_arn         = aws_acm_certificate.this[0].arn
  validation_record_fqdns = [for r in aws_route53_record.cert_validation : r.fqdn]
}
```

- [ ] **Step 3: Create iac/modules/alb/outputs.tf**

```hcl
output "alb_dns" {
  value = aws_lb.this.dns_name
}

output "alb_zone_id" {
  value = aws_lb.this.zone_id
}

output "alb_arn" {
  value = aws_lb.this.arn
}

output "target_group_arn" {
  value = aws_lb_target_group.this.arn
}

output "security_group_id" {
  value = aws_security_group.alb.id
}
```

- [ ] **Step 4: Commit**

```bash
git add iac/modules/alb/
git commit -m "feat(iac): add ALB shared module (HTTP/HTTPS, auto-cert)"
```

---

### Task 7: Shared Module — RDS (conditional)

**Files:**
- Create: `iac/modules/rds/main.tf`
- Create: `iac/modules/rds/variables.tf`
- Create: `iac/modules/rds/outputs.tf`

- [ ] **Step 1: Create iac/modules/rds/variables.tf**

```hcl
variable "enabled" {
  type    = bool
  default = false
}

variable "project_name" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "subnet_ids" {
  type = list(string)
}

variable "instance_class" {
  type    = string
  default = "db.t3.medium"
}

variable "allocated_storage" {
  type    = number
  default = 20
}

variable "password" {
  description = "Master password. Empty = auto-generate."
  type        = string
  default     = ""
  sensitive   = true
}

variable "allowed_security_group_id" {
  description = "SG allowed to connect to RDS"
  type        = string
  default     = ""
}

variable "tags" {
  type    = map(string)
  default = {}
}
```

- [ ] **Step 2: Create iac/modules/rds/main.tf**

```hcl
locals {
  password = var.password != "" ? var.password : random_password.this[0].result
}

resource "random_password" "this" {
  count   = var.enabled && var.password == "" ? 1 : 0
  length  = 24
  special = false
}

resource "aws_db_subnet_group" "this" {
  count      = var.enabled ? 1 : 0
  name       = "${var.project_name}-db-subnet"
  subnet_ids = var.subnet_ids
  tags       = var.tags
}

resource "aws_security_group" "rds" {
  count       = var.enabled ? 1 : 0
  name_prefix = "${var.project_name}-rds-"
  vpc_id      = var.vpc_id

  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = var.allowed_security_group_id != "" ? [var.allowed_security_group_id] : []
    cidr_blocks     = var.allowed_security_group_id == "" ? ["10.0.0.0/8"] : []
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = var.tags
  lifecycle { create_before_destroy = true }
}

resource "aws_db_instance" "this" {
  count                  = var.enabled ? 1 : 0
  identifier             = "${var.project_name}-db"
  engine                 = "postgres"
  engine_version         = "16.4"
  instance_class         = var.instance_class
  allocated_storage      = var.allocated_storage
  db_name                = "agenticops"
  username               = "agenticops"
  password               = local.password
  db_subnet_group_name   = aws_db_subnet_group.this[0].name
  vpc_security_group_ids = [aws_security_group.rds[0].id]
  skip_final_snapshot    = true
  publicly_accessible    = false
  storage_encrypted      = true
  tags                   = var.tags
}
```

- [ ] **Step 3: Create iac/modules/rds/outputs.tf**

```hcl
output "endpoint" {
  value = var.enabled ? aws_db_instance.this[0].endpoint : ""
}

output "database_url" {
  value     = var.enabled ? "postgresql+psycopg2://agenticops:${local.password}@${aws_db_instance.this[0].endpoint}/agenticops" : ""
  sensitive = true
}

output "password" {
  value     = var.enabled ? local.password : ""
  sensitive = true
}
```

- [ ] **Step 4: Commit**

```bash
git add iac/modules/rds/
git commit -m "feat(iac): add RDS shared module (conditional creation)"
```

---

### Task 8: Shared Module — DNS

**Files:**
- Create: `iac/modules/dns/main.tf`
- Create: `iac/modules/dns/variables.tf`
- Create: `iac/modules/dns/outputs.tf`

- [ ] **Step 1: Create iac/modules/dns/variables.tf**

```hcl
variable "domain_name" {
  type    = string
  default = ""
}

variable "route53_zone_id" {
  type    = string
  default = ""
}

variable "target_dns" {
  description = "ALB DNS name to point to"
  type        = string
}

variable "target_zone_id" {
  description = "ALB hosted zone ID"
  type        = string
}
```

- [ ] **Step 2: Create iac/modules/dns/main.tf**

```hcl
locals {
  create = var.domain_name != "" && var.route53_zone_id != ""
}

resource "aws_route53_record" "this" {
  count   = local.create ? 1 : 0
  zone_id = var.route53_zone_id
  name    = var.domain_name
  type    = "A"

  alias {
    name                   = var.target_dns
    zone_id                = var.target_zone_id
    evaluate_target_health = true
  }
}
```

- [ ] **Step 3: Create iac/modules/dns/outputs.tf**

```hcl
output "fqdn" {
  value = local.create ? aws_route53_record.this[0].fqdn : ""
}
```

- [ ] **Step 4: Commit**

```bash
git add iac/modules/dns/
git commit -m "feat(iac): add DNS shared module (Route53 A record)"
```

---

### Task 9: EC2 Deployment Module

**Files:**
- Create: `iac/ec2/versions.tf`
- Create: `iac/ec2/variables.tf`
- Create: `iac/ec2/main.tf`
- Create: `iac/ec2/outputs.tf`
- Create: `iac/ec2/templates/user-data.sh.tpl`
- Create: `iac/ec2/templates/docker-compose.yml.tpl`
- Create: `iac/ec2/templates/env.tpl`
- Create: `iac/ec2/terraform.tfvars.example`

- [ ] **Step 1: Create iac/ec2/versions.tf**

```hcl
terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.region
}
```

- [ ] **Step 2: Create iac/ec2/variables.tf**

```hcl
# --- General ---
variable "region" {
  type    = string
  default = "ap-southeast-1"
}

variable "project_name" {
  type    = string
  default = "agenticops"
}

variable "image_tag" {
  type    = string
  default = "latest"
}

# --- Network (bring-your-own) ---
variable "vpc_id" {
  type    = string
  default = ""
}

variable "public_subnet_ids" {
  type    = list(string)
  default = []
}

variable "private_subnet_ids" {
  type    = list(string)
  default = []
}

# --- EC2 ---
variable "instance_type" {
  type    = string
  default = "c5.xlarge"
}

variable "ssh_public_key_path" {
  type    = string
  default = "~/.ssh/id_rsa.pub"
}

variable "ssh_enabled" {
  type    = bool
  default = true
}

variable "ssh_allowed_cidrs" {
  type    = list(string)
  default = ["0.0.0.0/0"]
}

# --- App ---
variable "bedrock_region" {
  type    = string
  default = "us-east-1"
}

variable "bedrock_model" {
  type    = string
  default = "global.anthropic.claude-sonnet-4-6"
}

variable "bedrock_model_strong" {
  type    = string
  default = "global.anthropic.claude-opus-4-6-v1"
}

variable "bedrock_model_cheap" {
  type    = string
  default = "global.anthropic.claude-haiku-4-5-20251001-v1:0"
}

variable "admin_password" {
  type      = string
  sensitive = true
}

# --- Database ---
variable "db_backend" {
  description = "sqlite or rds"
  type        = string
  default     = "sqlite"
}

# --- DNS/SSL ---
variable "domain_name" {
  type    = string
  default = ""
}

variable "acm_cert_arn" {
  type    = string
  default = ""
}

variable "route53_zone_id" {
  type    = string
  default = ""
}

variable "alb_internal" {
  type    = bool
  default = false
}
```

- [ ] **Step 3: Create iac/ec2/templates/env.tpl**

```
AIOPS_DEPLOYMENT_PROFILE=cloud
AIOPS_BEDROCK_REGION=${bedrock_region}
AIOPS_BEDROCK_MODEL_ID=${bedrock_model}
AIOPS_BEDROCK_MODEL_ID_STRONG=${bedrock_model_strong}
AIOPS_BEDROCK_MODEL_ID_CHEAP=${bedrock_model_cheap}
AIOPS_DATABASE_URL=${database_url}
AIOPS_API_AUTH_ENABLED=true
AIOPS_ADMIN_PASSWORD=${admin_password}
AIOPS_REPORT_STORAGE=s3
AIOPS_REPORT_S3_BUCKET=${project_name}-reports-${account_id}
AIOPS_S3_REGION=${region}
```

- [ ] **Step 4: Create iac/ec2/templates/docker-compose.yml.tpl**

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
        awslogs-group: /${project_name}
        awslogs-stream-prefix: app
        awslogs-create-group: "true"
```

- [ ] **Step 5: Create iac/ec2/templates/user-data.sh.tpl**

```bash
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
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" > /etc/apt/sources.list.d/docker.list
apt-get update -y
apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

# Install AWS CLI
if ! command -v aws &>/dev/null; then
  curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o /tmp/awscliv2.zip
  apt-get install -y unzip
  unzip -qo /tmp/awscliv2.zip -d /tmp && /tmp/aws/install && rm -rf /tmp/aws*
fi

# Prepare app directory
mkdir -p /opt/agenticops/data

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
```

- [ ] **Step 6: Create iac/ec2/main.tf**

```hcl
locals {
  tags = { Project = var.project_name, ManagedBy = "terraform" }
}

data "aws_caller_identity" "current" {}

# --- Shared Modules ---
module "ecr" {
  source = "../modules/ecr"
  name   = var.project_name
  tags   = local.tags
}

module "vpc" {
  source             = "../modules/vpc"
  project_name       = var.project_name
  vpc_id             = var.vpc_id
  public_subnet_ids  = var.public_subnet_ids
  private_subnet_ids = var.private_subnet_ids
  tags               = local.tags
}

module "iam" {
  source       = "../modules/iam"
  project_name = var.project_name
  service      = "ec2"
  tags         = local.tags
}

module "rds" {
  source        = "../modules/rds"
  enabled       = var.db_backend == "rds"
  project_name  = var.project_name
  vpc_id        = module.vpc.vpc_id
  subnet_ids    = module.vpc.private_subnet_ids
  tags          = local.tags
}

module "alb" {
  source          = "../modules/alb"
  project_name    = var.project_name
  vpc_id          = module.vpc.vpc_id
  subnet_ids      = module.vpc.public_subnet_ids
  domain_name     = var.domain_name
  acm_cert_arn    = var.acm_cert_arn
  route53_zone_id = var.route53_zone_id
  internal        = var.alb_internal
  tags            = local.tags
}

module "dns" {
  source          = "../modules/dns"
  domain_name     = var.domain_name
  route53_zone_id = var.route53_zone_id
  target_dns      = module.alb.alb_dns
  target_zone_id  = module.alb.alb_zone_id
}

# --- EC2 Security Group ---
resource "aws_security_group" "ec2" {
  name_prefix = "${var.project_name}-ec2-"
  vpc_id      = module.vpc.vpc_id

  ingress {
    from_port       = 8000
    to_port         = 8000
    protocol        = "tcp"
    security_groups = [module.alb.security_group_id]
  }

  dynamic "ingress" {
    for_each = var.ssh_enabled ? [1] : []
    content {
      from_port   = 22
      to_port     = 22
      protocol    = "tcp"
      cidr_blocks = var.ssh_allowed_cidrs
    }
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = local.tags
  lifecycle { create_before_destroy = true }
}

# --- SSH Key ---
resource "aws_key_pair" "this" {
  count      = var.ssh_enabled ? 1 : 0
  key_name   = "${var.project_name}-key"
  public_key = file(pathexpand(var.ssh_public_key_path))
  tags       = local.tags
}

# --- EC2 Instance ---
locals {
  database_url = var.db_backend == "rds" ? module.rds.database_url : "sqlite:////app/data/agenticops.db"
  image_uri    = "${module.ecr.repository_url}:${var.image_tag}"
  ecr_registry = split("/", module.ecr.repository_url)[0]

  env_content = templatefile("${path.module}/templates/env.tpl", {
    bedrock_region       = var.bedrock_region
    bedrock_model        = var.bedrock_model
    bedrock_model_strong = var.bedrock_model_strong
    bedrock_model_cheap  = var.bedrock_model_cheap
    database_url         = local.database_url
    admin_password       = var.admin_password
    project_name         = var.project_name
    region               = var.region
    account_id           = data.aws_caller_identity.current.account_id
  })

  compose_content = templatefile("${path.module}/templates/docker-compose.yml.tpl", {
    image_uri    = local.image_uri
    region       = var.region
    project_name = var.project_name
  })
}

data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"] # Canonical

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*"]
  }
}

resource "aws_instance" "this" {
  ami                         = data.aws_ami.ubuntu.id
  instance_type               = var.instance_type
  subnet_id                   = module.vpc.public_subnet_ids[0]
  vpc_security_group_ids      = [aws_security_group.ec2.id]
  iam_instance_profile        = module.iam.instance_profile_name
  key_name                    = var.ssh_enabled ? aws_key_pair.this[0].key_name : null
  associate_public_ip_address = true

  root_block_device {
    volume_size = 30
    volume_type = "gp3"
  }

  user_data = templatefile("${path.module}/templates/user-data.sh.tpl", {
    env_content     = local.env_content
    compose_content = local.compose_content
    region          = var.region
    ecr_registry    = local.ecr_registry
  })

  tags = merge(local.tags, { Name = var.project_name })
}

# --- ALB Target Attachment ---
resource "aws_lb_target_group_attachment" "this" {
  target_group_arn = module.alb.target_group_arn
  target_id        = aws_instance.this.private_ip
  port             = 8000
}
```

- [ ] **Step 7: Create iac/ec2/outputs.tf**

```hcl
output "ecr_repository_url" {
  value = module.ecr.repository_url
}

output "public_ip" {
  value = aws_instance.this.public_ip
}

output "app_url" {
  value = var.domain_name != "" ? "https://${var.domain_name}" : "http://${module.alb.alb_dns}"
}

output "ssh_command" {
  value = var.ssh_enabled ? "ssh ubuntu@${aws_instance.this.public_ip}" : "SSH disabled"
}

output "health_check" {
  value = var.domain_name != "" ? "curl https://${var.domain_name}/api/health" : "curl http://${module.alb.alb_dns}/api/health"
}
```

- [ ] **Step 8: Create iac/ec2/terraform.tfvars.example**

```hcl
# === Required ===
region         = "ap-southeast-1"
admin_password = "CHANGE_ME"

# === Optional (uncomment to customize) ===
# project_name       = "agenticops"
# image_tag          = "latest"
# instance_type      = "c5.xlarge"
# bedrock_region     = "us-east-1"
# bedrock_model      = "global.anthropic.claude-sonnet-4-6"

# === Bring Your Own (uncomment if using existing infra) ===
# vpc_id             = "vpc-0abc123def456"
# public_subnet_ids  = ["subnet-aaa", "subnet-bbb"]
# private_subnet_ids = ["subnet-ccc", "subnet-ddd"]

# === Domain + SSL (uncomment for HTTPS) ===
# domain_name     = "ops.example.com"
# acm_cert_arn    = "arn:aws:acm:ap-southeast-1:123456789:certificate/xxx"
# route53_zone_id = "Z1234567890ABC"

# === Database (default: sqlite) ===
# db_backend = "rds"
```

- [ ] **Step 9: Validate terraform**

Run: `cd iac/ec2 && terraform init && terraform validate`
Expected: "Success! The configuration is valid."

- [ ] **Step 10: Commit**

```bash
git add iac/ec2/
git commit -m "feat(iac): add EC2 Docker deployment module"
```

---

### Task 10: ECS Deployment Module

**Files:**
- Create: `iac/ecs/versions.tf`
- Create: `iac/ecs/variables.tf`
- Create: `iac/ecs/main.tf`
- Create: `iac/ecs/outputs.tf`
- Create: `iac/ecs/terraform.tfvars.example`

- [ ] **Step 1: Create iac/ecs/versions.tf**

```hcl
terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.region
}
```

- [ ] **Step 2: Create iac/ecs/variables.tf**

```hcl
# --- General ---
variable "region" { type = string; default = "ap-southeast-1" }
variable "project_name" { type = string; default = "agenticops" }
variable "image_tag" { type = string; default = "latest" }

# --- Network ---
variable "vpc_id" { type = string; default = "" }
variable "public_subnet_ids" { type = list(string); default = [] }
variable "private_subnet_ids" { type = list(string); default = [] }

# --- ECS ---
variable "cpu" { type = number; default = 2048 }
variable "memory" { type = number; default = 4096 }
variable "desired_count" { type = number; default = 1 }

# --- App ---
variable "bedrock_region" { type = string; default = "us-east-1" }
variable "bedrock_model" { type = string; default = "global.anthropic.claude-sonnet-4-6" }
variable "bedrock_model_strong" { type = string; default = "global.anthropic.claude-opus-4-6-v1" }
variable "bedrock_model_cheap" { type = string; default = "global.anthropic.claude-haiku-4-5-20251001-v1:0" }
variable "admin_password" { type = string; sensitive = true }

# --- Database ---
variable "db_backend" { type = string; default = "sqlite" }

# --- DNS/SSL ---
variable "domain_name" { type = string; default = "" }
variable "acm_cert_arn" { type = string; default = "" }
variable "route53_zone_id" { type = string; default = "" }
variable "alb_internal" { type = bool; default = false }
```

- [ ] **Step 3: Create iac/ecs/main.tf**

```hcl
locals {
  tags         = { Project = var.project_name, ManagedBy = "terraform" }
  database_url = var.db_backend == "rds" ? module.rds.database_url : "sqlite:////app/data/agenticops.db"
  image_uri    = "${module.ecr.repository_url}:${var.image_tag}"
}

data "aws_caller_identity" "current" {}

module "ecr" {
  source = "../modules/ecr"
  name   = var.project_name
  tags   = local.tags
}

module "vpc" {
  source             = "../modules/vpc"
  project_name       = var.project_name
  vpc_id             = var.vpc_id
  public_subnet_ids  = var.public_subnet_ids
  private_subnet_ids = var.private_subnet_ids
  tags               = local.tags
}

module "iam" {
  source       = "../modules/iam"
  project_name = var.project_name
  service      = "ecs"
  tags         = local.tags
}

module "rds" {
  source       = "../modules/rds"
  enabled      = var.db_backend == "rds"
  project_name = var.project_name
  vpc_id       = module.vpc.vpc_id
  subnet_ids   = module.vpc.private_subnet_ids
  tags         = local.tags
}

module "alb" {
  source          = "../modules/alb"
  project_name    = var.project_name
  vpc_id          = module.vpc.vpc_id
  subnet_ids      = module.vpc.public_subnet_ids
  domain_name     = var.domain_name
  acm_cert_arn    = var.acm_cert_arn
  route53_zone_id = var.route53_zone_id
  internal        = var.alb_internal
  tags            = local.tags
}

module "dns" {
  source          = "../modules/dns"
  domain_name     = var.domain_name
  route53_zone_id = var.route53_zone_id
  target_dns      = module.alb.alb_dns
  target_zone_id  = module.alb.alb_zone_id
}

# --- ECS Cluster ---
resource "aws_ecs_cluster" "this" {
  name = var.project_name
  setting {
    name  = "containerInsights"
    value = "enabled"
  }
  tags = local.tags
}

# --- CloudWatch Log Group ---
resource "aws_cloudwatch_log_group" "this" {
  name              = "/${var.project_name}"
  retention_in_days = 30
  tags              = local.tags
}

# --- Security Group ---
resource "aws_security_group" "ecs" {
  name_prefix = "${var.project_name}-ecs-"
  vpc_id      = module.vpc.vpc_id

  ingress {
    from_port       = 8000
    to_port         = 8000
    protocol        = "tcp"
    security_groups = [module.alb.security_group_id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = local.tags
  lifecycle { create_before_destroy = true }
}

# --- Task Definition ---
resource "aws_ecs_task_definition" "this" {
  family                   = var.project_name
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.cpu
  memory                   = var.memory
  execution_role_arn       = module.iam.role_arn
  task_role_arn            = module.iam.role_arn

  container_definitions = jsonencode([{
    name  = var.project_name
    image = local.image_uri
    portMappings = [{ containerPort = 8000, protocol = "tcp" }]
    environment = [
      { name = "AIOPS_DEPLOYMENT_PROFILE", value = "cloud" },
      { name = "AIOPS_BEDROCK_REGION", value = var.bedrock_region },
      { name = "AIOPS_BEDROCK_MODEL_ID", value = var.bedrock_model },
      { name = "AIOPS_BEDROCK_MODEL_ID_STRONG", value = var.bedrock_model_strong },
      { name = "AIOPS_BEDROCK_MODEL_ID_CHEAP", value = var.bedrock_model_cheap },
      { name = "AIOPS_DATABASE_URL", value = local.database_url },
      { name = "AIOPS_API_AUTH_ENABLED", value = "true" },
      { name = "AIOPS_ADMIN_PASSWORD", value = var.admin_password },
      { name = "AIOPS_REPORT_STORAGE", value = "s3" },
      { name = "AIOPS_REPORT_S3_BUCKET", value = "${var.project_name}-reports-${data.aws_caller_identity.current.account_id}" },
      { name = "AIOPS_S3_REGION", value = var.region },
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-region"        = var.region
        "awslogs-group"         = aws_cloudwatch_log_group.this.name
        "awslogs-stream-prefix" = "ecs"
      }
    }
    healthCheck = {
      command     = ["CMD-SHELL", "curl -sf http://localhost:8000/api/health || exit 1"]
      interval    = 30
      timeout     = 5
      retries     = 3
      startPeriod = 15
    }
  }])

  tags = local.tags
}

# --- ECS Service ---
resource "aws_ecs_service" "this" {
  name            = var.project_name
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.this.arn
  desired_count   = var.desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = module.vpc.private_subnet_ids
    security_groups  = [aws_security_group.ecs.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = module.alb.target_group_arn
    container_name   = var.project_name
    container_port   = 8000
  }

  depends_on = [module.alb]
  tags       = local.tags
}
```

- [ ] **Step 4: Create iac/ecs/outputs.tf**

```hcl
output "ecr_repository_url" {
  value = module.ecr.repository_url
}

output "cluster_name" {
  value = aws_ecs_cluster.this.name
}

output "service_name" {
  value = aws_ecs_service.this.name
}

output "app_url" {
  value = var.domain_name != "" ? "https://${var.domain_name}" : "http://${module.alb.alb_dns}"
}

output "health_check" {
  value = var.domain_name != "" ? "curl https://${var.domain_name}/api/health" : "curl http://${module.alb.alb_dns}/api/health"
}
```

- [ ] **Step 5: Create iac/ecs/terraform.tfvars.example**

```hcl
# === Required ===
region         = "ap-southeast-1"
admin_password = "CHANGE_ME"

# === Optional ===
# cpu           = 2048    # 2 vCPU
# memory        = 4096    # 4 GB
# desired_count = 1

# === Bring Your Own ===
# vpc_id             = "vpc-xxx"
# public_subnet_ids  = ["subnet-aaa", "subnet-bbb"]
# private_subnet_ids = ["subnet-ccc", "subnet-ddd"]

# === Domain + SSL ===
# domain_name     = "ops.example.com"
# acm_cert_arn    = "arn:aws:acm:..."
# route53_zone_id = "Z1234567890ABC"
```

- [ ] **Step 6: Validate**

Run: `cd iac/ecs && terraform init && terraform validate`
Expected: "Success! The configuration is valid."

- [ ] **Step 7: Commit**

```bash
git add iac/ecs/
git commit -m "feat(iac): add ECS Fargate deployment module"
```

---

### Task 11: EKS Deployment Module

**Files:**
- Create: `iac/eks/versions.tf`
- Create: `iac/eks/variables.tf`
- Create: `iac/eks/main.tf`
- Create: `iac/eks/outputs.tf`
- Create: `iac/eks/terraform.tfvars.example`

- [ ] **Step 1: Create iac/eks/versions.tf**

```hcl
terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.25"
    }
  }
}

provider "aws" {
  region = var.region
}

data "aws_eks_cluster" "this" {
  name = local.cluster_name
}

data "aws_eks_cluster_auth" "this" {
  name = local.cluster_name
}

provider "kubernetes" {
  host                   = data.aws_eks_cluster.this.endpoint
  cluster_ca_certificate = base64decode(data.aws_eks_cluster.this.certificate_authority[0].data)
  token                  = data.aws_eks_cluster_auth.this.token
}
```

- [ ] **Step 2: Create iac/eks/variables.tf**

```hcl
# --- General ---
variable "region" { type = string; default = "ap-southeast-1" }
variable "project_name" { type = string; default = "agenticops" }
variable "image_tag" { type = string; default = "latest" }

# --- Network ---
variable "vpc_id" { type = string; default = "" }
variable "public_subnet_ids" { type = list(string); default = [] }
variable "private_subnet_ids" { type = list(string); default = [] }

# --- EKS ---
variable "eks_cluster_name" {
  description = "Existing EKS cluster name. Empty = create new."
  type        = string
  default     = ""
}

variable "namespace" { type = string; default = "agenticops" }
variable "replicas" { type = number; default = 1 }

variable "node_selector" {
  type    = map(string)
  default = {}
}

# --- App ---
variable "bedrock_region" { type = string; default = "us-east-1" }
variable "bedrock_model" { type = string; default = "global.anthropic.claude-sonnet-4-6" }
variable "bedrock_model_strong" { type = string; default = "global.anthropic.claude-opus-4-6-v1" }
variable "bedrock_model_cheap" { type = string; default = "global.anthropic.claude-haiku-4-5-20251001-v1:0" }
variable "admin_password" { type = string; sensitive = true }

# --- Database ---
variable "db_backend" { type = string; default = "sqlite" }

# --- DNS/SSL ---
variable "domain_name" { type = string; default = "" }
variable "acm_cert_arn" { type = string; default = "" }
variable "route53_zone_id" { type = string; default = "" }
variable "alb_internal" { type = bool; default = false }
```

- [ ] **Step 3: Create iac/eks/main.tf**

```hcl
locals {
  tags         = { Project = var.project_name, ManagedBy = "terraform" }
  cluster_name = var.eks_cluster_name != "" ? var.eks_cluster_name : "${var.project_name}-cluster"
  create_cluster = var.eks_cluster_name == ""
  database_url = var.db_backend == "rds" ? module.rds.database_url : "sqlite:////app/data/agenticops.db"
  image_uri    = "${module.ecr.repository_url}:${var.image_tag}"
}

data "aws_caller_identity" "current" {}

module "ecr" {
  source = "../modules/ecr"
  name   = var.project_name
  tags   = local.tags
}

module "vpc" {
  source             = "../modules/vpc"
  project_name       = var.project_name
  vpc_id             = var.vpc_id
  public_subnet_ids  = var.public_subnet_ids
  private_subnet_ids = var.private_subnet_ids
  tags               = local.tags
}

module "rds" {
  source       = "../modules/rds"
  enabled      = var.db_backend == "rds"
  project_name = var.project_name
  vpc_id       = module.vpc.vpc_id
  subnet_ids   = module.vpc.private_subnet_ids
  tags         = local.tags
}

# --- EKS Cluster (only if not bring-your-own) ---
module "eks" {
  count   = local.create_cluster ? 1 : 0
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 20.0"

  cluster_name    = local.cluster_name
  cluster_version = "1.30"
  vpc_id          = module.vpc.vpc_id
  subnet_ids      = module.vpc.private_subnet_ids

  eks_managed_node_groups = {
    default = {
      instance_types = ["m5.large"]
      min_size       = 1
      max_size       = 3
      desired_size   = 2
    }
  }

  tags = local.tags
}

# --- Kubernetes Resources ---
resource "kubernetes_namespace" "this" {
  metadata {
    name = var.namespace
  }
}

resource "kubernetes_secret" "app" {
  metadata {
    name      = "${var.project_name}-env"
    namespace = kubernetes_namespace.this.metadata[0].name
  }

  data = {
    AIOPS_ADMIN_PASSWORD = var.admin_password
    AIOPS_DATABASE_URL   = local.database_url
  }
}

resource "kubernetes_config_map" "app" {
  metadata {
    name      = "${var.project_name}-config"
    namespace = kubernetes_namespace.this.metadata[0].name
  }

  data = {
    AIOPS_DEPLOYMENT_PROFILE     = "cloud"
    AIOPS_BEDROCK_REGION         = var.bedrock_region
    AIOPS_BEDROCK_MODEL_ID       = var.bedrock_model
    AIOPS_BEDROCK_MODEL_ID_STRONG = var.bedrock_model_strong
    AIOPS_BEDROCK_MODEL_ID_CHEAP = var.bedrock_model_cheap
    AIOPS_API_AUTH_ENABLED       = "true"
    AIOPS_REPORT_STORAGE         = "s3"
    AIOPS_REPORT_S3_BUCKET       = "${var.project_name}-reports-${data.aws_caller_identity.current.account_id}"
    AIOPS_S3_REGION              = var.region
  }
}

resource "kubernetes_deployment" "app" {
  metadata {
    name      = var.project_name
    namespace = kubernetes_namespace.this.metadata[0].name
    labels    = { app = var.project_name }
  }

  spec {
    replicas = var.replicas

    selector {
      match_labels = { app = var.project_name }
    }

    template {
      metadata {
        labels = { app = var.project_name }
      }

      spec {
        dynamic "node_selector" {
          for_each = length(var.node_selector) > 0 ? [var.node_selector] : []
          content {
            # node_selector is handled via the map below
          }
        }

        container {
          name  = var.project_name
          image = local.image_uri

          port {
            container_port = 8000
          }

          env_from {
            config_map_ref { name = kubernetes_config_map.app.metadata[0].name }
          }

          env_from {
            secret_ref { name = kubernetes_secret.app.metadata[0].name }
          }

          resources {
            requests = { cpu = "500m", memory = "1Gi" }
            limits   = { cpu = "2000m", memory = "4Gi" }
          }

          liveness_probe {
            http_get {
              path = "/api/health"
              port = 8000
            }
            initial_delay_seconds = 15
            period_seconds        = 30
          }

          readiness_probe {
            http_get {
              path = "/api/health"
              port = 8000
            }
            initial_delay_seconds = 10
            period_seconds        = 10
          }

          volume_mount {
            name       = "data"
            mount_path = "/app/data"
          }
        }

        volume {
          name = "data"
          empty_dir {}
        }
      }
    }
  }
}

resource "kubernetes_service" "app" {
  metadata {
    name      = var.project_name
    namespace = kubernetes_namespace.this.metadata[0].name
    annotations = var.domain_name != "" ? {
      "service.beta.kubernetes.io/aws-load-balancer-type"            = "external"
      "service.beta.kubernetes.io/aws-load-balancer-nlb-target-type" = "ip"
      "service.beta.kubernetes.io/aws-load-balancer-scheme"          = var.alb_internal ? "internal" : "internet-facing"
      "service.beta.kubernetes.io/aws-load-balancer-ssl-cert"        = var.acm_cert_arn
      "service.beta.kubernetes.io/aws-load-balancer-ssl-ports"       = "443"
    } : {}
  }

  spec {
    selector = { app = var.project_name }
    type     = var.domain_name != "" ? "LoadBalancer" : "ClusterIP"

    port {
      port        = var.domain_name != "" ? 443 : 8000
      target_port = 8000
      protocol    = "TCP"
    }
  }
}
```

- [ ] **Step 4: Create iac/eks/outputs.tf**

```hcl
output "ecr_repository_url" {
  value = module.ecr.repository_url
}

output "cluster_name" {
  value = local.cluster_name
}

output "namespace" {
  value = var.namespace
}

output "app_url" {
  value = var.domain_name != "" ? "https://${var.domain_name}" : "kubectl port-forward svc/${var.project_name} 8000:8000 -n ${var.namespace}"
}
```

- [ ] **Step 5: Create iac/eks/terraform.tfvars.example**

```hcl
# === Required ===
region         = "ap-southeast-1"
admin_password = "CHANGE_ME"

# === EKS (use existing cluster — recommended) ===
eks_cluster_name = "my-existing-cluster"
namespace        = "agenticops"
# replicas       = 1

# === Or create new cluster (leave eks_cluster_name empty) ===
# vpc_id             = "vpc-xxx"
# private_subnet_ids = ["subnet-aaa", "subnet-bbb"]

# === Domain + SSL (for LoadBalancer service) ===
# domain_name  = "ops.example.com"
# acm_cert_arn = "arn:aws:acm:..."
```

- [ ] **Step 6: Commit**

```bash
git add iac/eks/
git commit -m "feat(iac): add EKS deployment module (existing or new cluster)"
```

---

### Task 12: Validate and Final Commit

- [ ] **Step 1: Validate all modules**

```bash
cd /Users/malibo/MyDev/AgenticOps
for dir in iac/ec2 iac/ecs iac/eks; do
  echo "=== Validating $dir ==="
  cd $dir && terraform init -backend=false && terraform validate && cd -
done
```

Expected: All three show "Success! The configuration is valid."

- [ ] **Step 2: Test Docker build**

```bash
docker build -t agenticops:test .
docker run --rm -d -p 8000:8000 --name agenticops-test \
  -e AIOPS_ADMIN_PASSWORD=test123 agenticops:test
sleep 10
curl -sf http://localhost:8000/api/health | jq .status
docker stop agenticops-test
```

Expected: `"healthy"`

- [ ] **Step 3: Final commit with all remaining files**

```bash
git add Makefile .dockerignore Dockerfile iac/modules/ iac/ec2/ iac/ecs/ iac/eks/
git status
git commit -m "feat(iac): Docker + Terraform deployment (EC2/ECS/EKS)

- Multi-stage Dockerfile (Node frontend + Python runtime)
- Shared Terraform modules: ecr, vpc, alb, rds, iam, dns
- EC2 module: docker-compose on single instance
- ECS module: Fargate with ALB
- EKS module: K8s deployment (existing or new cluster)
- All support bring-your-own VPC, domain, certificates
- Makefile: build / push / deploy-ec2 / deploy-ecs / deploy-eks"
```

---

## Execution Summary

| Task | Component | Files |
|------|-----------|-------|
| 1 | Dockerfile + .dockerignore | 2 |
| 2 | Makefile | 1 |
| 3 | modules/ecr | 3 |
| 4 | modules/vpc | 3 |
| 5 | modules/iam | 3 |
| 6 | modules/alb | 3 |
| 7 | modules/rds | 3 |
| 8 | modules/dns | 3 |
| 9 | iac/ec2 (full module) | 8 |
| 10 | iac/ecs (full module) | 5 |
| 11 | iac/eks (full module) | 5 |
| 12 | Validate + final commit | — |
