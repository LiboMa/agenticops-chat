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
  source           = "../modules/iam"
  project_name     = var.project_name
  service          = "ecs"
  kms_key_arn      = var.kms_key_arn
  target_role_arns = var.target_role_arns
  tags             = local.tags
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
    name         = var.project_name
    image        = local.image_uri
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
        "awslogs-group"         = "/${var.project_name}"
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
