module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.0"

  name = "${var.cluster_name}-vpc"
  cidr = var.vpc_cidr

  azs             = local.azs
  private_subnets = var.private_subnets
  public_subnets  = var.public_subnets

  # Single NAT GW for cost savings (lab environment)
  enable_nat_gateway = true
  single_nat_gateway = true

  # DNS support required for EKS
  enable_dns_hostnames = true
  enable_dns_support   = true

  # Subnet tags for EKS and AWS LB Controller discovery
  public_subnet_tags = {
    "kubernetes.io/cluster/${var.cluster_name}" = "shared"
    # No kubernetes.io/role/elb — prevents public ALB creation
  }

  private_subnet_tags = {
    "kubernetes.io/cluster/${var.cluster_name}" = "shared"
    "kubernetes.io/role/internal-elb"           = 1
    "karpenter.sh/discovery"                    = var.cluster_name
  }

  tags = local.tags
}
