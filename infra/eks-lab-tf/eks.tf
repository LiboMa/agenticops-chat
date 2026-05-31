module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 20.0"

  cluster_name    = var.cluster_name
  cluster_version = var.cluster_version

  # Network
  vpc_id     = module.vpc.vpc_id
  subnet_ids = module.vpc.private_subnets

  # API endpoint: public for local kubectl, private for in-cluster
  cluster_endpoint_public_access  = true
  cluster_endpoint_private_access = true

  # Enable IRSA
  enable_irsa = true

  # CloudWatch logging
  cluster_enabled_log_types = ["api", "audit", "authenticator", "controllerManager", "scheduler"]

  # Allow current caller + nodes to manage cluster
  enable_cluster_creator_admin_permissions = true

  # EKS Managed Addons
  cluster_addons = merge(
    {
      vpc-cni = {
        most_recent = true
      }
      coredns = {
        most_recent = true
      }
      kube-proxy = {
        most_recent = true
      }
      aws-ebs-csi-driver = {
        most_recent              = true
        service_account_role_arn = module.ebs_csi_irsa.iam_role_arn
      }
    },
    var.enable_guardduty ? {
      aws-guardduty-agent = {
        most_recent = true
      }
    } : {}
  )

  # ----- Managed Node Groups -----
  eks_managed_node_groups = {
    workload = {
      name           = "workload"
      instance_types = [var.workload_instance_type]
      min_size       = var.workload_min_size
      desired_size   = var.workload_desired_size
      max_size       = var.workload_max_size

      disk_size = 50

      labels = {
        role = "workload"
      }

      iam_role_additional_policies = {
        ssm = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
      }

      tags = local.tags
    }

    monitoring = {
      name           = "monitoring"
      instance_types = [var.monitoring_instance_type]
      min_size       = var.monitoring_min_size
      desired_size   = var.monitoring_desired_size
      max_size       = var.monitoring_max_size

      disk_size = 80

      labels = {
        role = "monitoring"
      }

      taints = [
        {
          key    = "dedicated"
          value  = "monitoring"
          effect = "NO_SCHEDULE"
        }
      ]

      iam_role_additional_policies = {
        ssm = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
      }

      tags = local.tags
    }
  }

  # Tag nodes for Karpenter discovery
  node_security_group_tags = {
    "karpenter.sh/discovery" = var.cluster_name
  }

  tags = local.tags
}

# ----- IRSA for EBS CSI Driver -----
module "ebs_csi_irsa" {
  source  = "terraform-aws-modules/iam/aws//modules/iam-role-for-service-accounts-eks"
  version = "~> 5.0"

  role_name             = "${var.cluster_name}-ebs-csi"
  attach_ebs_csi_policy = true

  oidc_providers = {
    main = {
      provider_arn               = module.eks.oidc_provider_arn
      namespace_service_accounts = ["kube-system:ebs-csi-controller-sa"]
    }
  }

  tags = local.tags
}
