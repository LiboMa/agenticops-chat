# -----------------------------------------------------------------------------
# VPC — created only when var.vpc_id is empty
# -----------------------------------------------------------------------------

module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.0"

  count = var.vpc_id == "" ? 1 : 0

  name = "${var.project_name}-vpc"
  cidr = var.vpc_cidr

  azs             = local.azs
  public_subnets  = [for i, az in local.azs : cidrsubnet(var.vpc_cidr, 8, i)]
  private_subnets = [for i, az in local.azs : cidrsubnet(var.vpc_cidr, 8, i + 10)]

  enable_nat_gateway = true
  single_nat_gateway = true # Cost savings — single AZ NAT

  enable_dns_hostnames = true
  enable_dns_support   = true

  public_subnet_tags = {
    "Type" = "public"
  }

  private_subnet_tags = {
    "Type" = "private"
  }

  tags = local.tags
}
