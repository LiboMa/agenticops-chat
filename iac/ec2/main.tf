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
  owners      = ["099720109477"]

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
