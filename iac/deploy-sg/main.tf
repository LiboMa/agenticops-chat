# -----------------------------------------------------------------------------
# Data Sources
# -----------------------------------------------------------------------------

data "aws_availability_zones" "available" {
  state = "available"
}

data "aws_ec2_managed_prefix_list" "cloudfront" {
  name = "com.amazonaws.global.cloudfront.origin-facing"
}

# Ubuntu 24.04 LTS AMI
data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"] # Canonical

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

# -----------------------------------------------------------------------------
# Locals
# -----------------------------------------------------------------------------

locals {
  azs = slice(data.aws_availability_zones.available.names, 0, 2)

  # Resolve VPC/subnet IDs — either from new VPC or existing
  vpc_id             = var.vpc_id != "" ? var.vpc_id : module.vpc[0].vpc_id
  public_subnet_ids  = var.vpc_id != "" ? var.public_subnet_ids : module.vpc[0].public_subnets
  private_subnet_ids = var.vpc_id != "" ? var.private_subnet_ids : module.vpc[0].private_subnets

  tags = merge(var.extra_tags, {
    Project     = var.project_name
    Environment = var.environment
  })
}
