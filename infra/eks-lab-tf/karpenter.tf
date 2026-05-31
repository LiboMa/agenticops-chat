# ----- Karpenter IAM + infrastructure -----
module "karpenter" {
  source  = "terraform-aws-modules/eks/aws//modules/karpenter"
  version = "~> 20.0"

  cluster_name = module.eks.cluster_name

  # Create IAM role for Karpenter controller (IRSA)
  enable_irsa                     = true
  irsa_oidc_provider_arn          = module.eks.oidc_provider_arn
  irsa_namespace_service_accounts = ["kube-system:karpenter"]

  # Create node IAM role for Karpenter-provisioned nodes
  create_node_iam_role = true
  node_iam_role_additional_policies = {
    ssm = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
  }

  tags = local.tags
}

# ----- Karpenter Helm chart -----
resource "helm_release" "karpenter" {
  namespace  = "kube-system"
  name       = "karpenter"
  repository = "oci://public.ecr.aws/karpenter"
  chart      = "karpenter"
  version    = "1.1.1"

  wait = true

  values = [
    yamlencode({
      settings = {
        clusterName       = module.eks.cluster_name
        clusterEndpoint   = module.eks.cluster_endpoint
        interruptionQueue = module.karpenter.queue_name
      }
      serviceAccount = {
        annotations = {
          "eks.amazonaws.com/role-arn" = module.karpenter.iam_role_arn
        }
      }
    })
  ]

  depends_on = [module.eks]
}

# ----- EC2NodeClass -----
resource "kubectl_manifest" "karpenter_node_class" {
  yaml_body = yamlencode({
    apiVersion = "karpenter.k8s.aws/v1"
    kind       = "EC2NodeClass"
    metadata = {
      name = "default"
    }
    spec = {
      amiSelectorTerms = [{
        alias = "al2023@latest"
      }]
      role = module.karpenter.node_iam_role_name
      subnetSelectorTerms = [{
        tags = {
          "karpenter.sh/discovery" = var.cluster_name
        }
      }]
      securityGroupSelectorTerms = [{
        tags = {
          "karpenter.sh/discovery" = var.cluster_name
        }
      }]
      blockDeviceMappings = [{
        deviceName = "/dev/xvda"
        ebs = {
          volumeSize          = "50Gi"
          volumeType          = "gp3"
          deleteOnTermination = true
        }
      }]
      tags = merge(local.tags, {
        "karpenter.sh/discovery" = var.cluster_name
      })
    }
  })

  depends_on = [helm_release.karpenter]
}

# ----- NodePool -----
resource "kubectl_manifest" "karpenter_node_pool" {
  yaml_body = yamlencode({
    apiVersion = "karpenter.sh/v1"
    kind       = "NodePool"
    metadata = {
      name = "default"
    }
    spec = {
      template = {
        spec = {
          nodeClassRef = {
            group = "karpenter.k8s.aws"
            kind  = "EC2NodeClass"
            name  = "default"
          }
          requirements = [
            {
              key      = "kubernetes.io/arch"
              operator = "In"
              values   = ["amd64"]
            },
            {
              key      = "karpenter.sh/capacity-type"
              operator = "In"
              values   = ["on-demand", "spot"]
            },
            {
              key      = "node.kubernetes.io/instance-type"
              operator = "In"
              values = [
                "t3.medium", "t3.large", "t3.xlarge",
                "t3a.medium", "t3a.large", "t3a.xlarge",
                "m5.medium", "m5.large", "m5.xlarge",
                "m5a.medium", "m5a.large", "m5a.xlarge",
                "m6i.medium", "m6i.large", "m6i.xlarge",
                "m7i.medium", "m7i.large", "m7i.xlarge",
              ]
            },
          ]
        }
      }
      limits = {
        cpu    = tostring(var.karpenter_node_cpu_limit)
        memory = var.karpenter_node_memory_limit
      }
      disruption = {
        consolidationPolicy = "WhenEmptyOrUnderutilized"
        consolidateAfter    = "30s"
        expireAfter         = "24h"
      }
    }
  })

  depends_on = [kubectl_manifest.karpenter_node_class]
}
