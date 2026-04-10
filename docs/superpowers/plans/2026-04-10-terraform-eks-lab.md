# Terraform EKS Lab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provision a complete EKS lab environment in us-west-2 via a single `terraform apply` — VPC, EKS cluster, Karpenter, monitoring stack, and Online Boutique workload.

**Architecture:** Community Terraform modules (`terraform-aws-modules/vpc/aws`, `terraform-aws-modules/eks/aws`) for infrastructure, Helm provider for application stack. All nodes in private subnets, internal ALB only, single NAT gateway for cost savings.

**Tech Stack:** Terraform >= 1.5, AWS provider, Helm provider, Kubernetes provider, kubectl provider, Karpenter v1.x, kube-prometheus-stack, Jaeger, OTEL Collector, AWS LB Controller, Online Boutique.

**Spec:** `docs/superpowers/specs/2026-04-09-terraform-eks-lab-design.md`

---

## File Structure

```
infra/eks-lab-tf/
├── versions.tf          # Terraform block, required providers, provider configs
├── variables.tf         # All input variables with defaults
├── locals.tf            # Computed values, tags, AZ list
├── data.tf              # Data sources (AWS caller identity, EKS cluster auth)
├── vpc.tf               # VPC module
├── eks.tf               # EKS module (cluster + managed node groups + addons)
├── karpenter.tf         # Karpenter IAM module + Helm + NodePool + EC2NodeClass
├── helm-monitoring.tf   # Helm releases: prometheus-stack, jaeger, otel-collector
├── helm-infra.tf        # Helm release: aws-load-balancer-controller
├── helm-workload.tf     # Online Boutique via kubectl_manifest
├── outputs.tf           # Cluster endpoint, kubeconfig command, key ARNs
├── terraform.tfvars     # Lab defaults
├── values/              # Helm values files (kept separate for readability)
│   ├── prometheus.yaml
│   ├── jaeger.yaml
│   ├── otel-collector.yaml
│   └── online-boutique.yaml
└── README.md            # Ops manual
```

Split rationale: `helm.tf` is split into 3 files by concern (monitoring / infra / workload) because each has independent dependencies and distinct update cadence. Values files are extracted to `values/` to keep HCL files focused on resource wiring.

---

### Task 1: Scaffold — versions.tf, variables.tf, locals.tf, data.tf

**Files:**
- Create: `infra/eks-lab-tf/versions.tf`
- Create: `infra/eks-lab-tf/variables.tf`
- Create: `infra/eks-lab-tf/locals.tf`
- Create: `infra/eks-lab-tf/data.tf`

- [ ] **Step 1: Create `versions.tf`**

```hcl
terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    helm = {
      source  = "hashicorp/helm"
      version = "~> 2.17"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.36"
    }
    kubectl = {
      source  = "gavinbunney/kubectl"
      version = "~> 1.19"
    }
  }
}

provider "aws" {
  region = var.region
}

provider "kubernetes" {
  host                   = module.eks.cluster_endpoint
  cluster_ca_certificate = base64decode(module.eks.cluster_certificate_authority_data)

  exec {
    api_version = "client.authentication.k8s.io/v1beta1"
    command     = "aws"
    args        = ["eks", "get-token", "--cluster-name", module.eks.cluster_name, "--region", var.region]
  }
}

provider "helm" {
  kubernetes {
    host                   = module.eks.cluster_endpoint
    cluster_ca_certificate = base64decode(module.eks.cluster_certificate_authority_data)

    exec {
      api_version = "client.authentication.k8s.io/v1beta1"
      command     = "aws"
      args        = ["eks", "get-token", "--cluster-name", module.eks.cluster_name, "--region", var.region]
    }
  }
}

provider "kubectl" {
  host                   = module.eks.cluster_endpoint
  cluster_ca_certificate = base64decode(module.eks.cluster_certificate_authority_data)
  load_config_file       = false

  exec {
    api_version = "client.authentication.k8s.io/v1beta1"
    command     = "aws"
    args        = ["eks", "get-token", "--cluster-name", module.eks.cluster_name, "--region", var.region]
  }
}
```

- [ ] **Step 2: Create `variables.tf`**

```hcl
# -----------------------------------------------------
# General
# -----------------------------------------------------
variable "cluster_name" {
  description = "EKS cluster name"
  type        = string
  default     = "agenticops-lab"
}

variable "region" {
  description = "AWS region"
  type        = string
  default     = "us-west-2"
}

variable "cluster_version" {
  description = "Kubernetes version"
  type        = string
  default     = "1.30"
}

# -----------------------------------------------------
# Network
# -----------------------------------------------------
variable "vpc_cidr" {
  description = "VPC CIDR block"
  type        = string
  default     = "10.0.0.0/16"
}

variable "private_subnets" {
  description = "Private subnet CIDRs"
  type        = list(string)
  default     = ["10.0.101.0/24", "10.0.102.0/24", "10.0.103.0/24"]
}

variable "public_subnets" {
  description = "Public subnet CIDRs (NAT GW only)"
  type        = list(string)
  default     = ["10.0.1.0/24", "10.0.2.0/24", "10.0.3.0/24"]
}

# -----------------------------------------------------
# Node Groups
# -----------------------------------------------------
variable "workload_instance_type" {
  description = "Instance type for workload node group"
  type        = string
  default     = "t3.large"
}

variable "workload_desired_size" {
  description = "Desired number of workload nodes"
  type        = number
  default     = 3
}

variable "workload_min_size" {
  description = "Minimum number of workload nodes"
  type        = number
  default     = 2
}

variable "workload_max_size" {
  description = "Maximum number of workload nodes"
  type        = number
  default     = 5
}

variable "monitoring_instance_type" {
  description = "Instance type for monitoring node group"
  type        = string
  default     = "t3.large"
}

variable "monitoring_desired_size" {
  description = "Desired number of monitoring nodes"
  type        = number
  default     = 2
}

variable "monitoring_min_size" {
  description = "Minimum number of monitoring nodes"
  type        = number
  default     = 1
}

variable "monitoring_max_size" {
  description = "Maximum number of monitoring nodes"
  type        = number
  default     = 3
}

# -----------------------------------------------------
# Karpenter
# -----------------------------------------------------
variable "karpenter_node_cpu_limit" {
  description = "Max vCPU Karpenter can provision"
  type        = number
  default     = 32
}

variable "karpenter_node_memory_limit" {
  description = "Max memory (Gi) Karpenter can provision"
  type        = string
  default     = "64Gi"
}

# -----------------------------------------------------
# Optional Addons
# -----------------------------------------------------
variable "enable_guardduty" {
  description = "Enable GuardDuty EKS Runtime Monitoring addon (requires GuardDuty enabled at account level)"
  type        = bool
  default     = false
}

# -----------------------------------------------------
# Monitoring
# -----------------------------------------------------
variable "grafana_admin_password" {
  description = "Grafana admin password"
  type        = string
  default     = "agenticops-lab"
  sensitive   = true
}

variable "alertmanager_webhook_url" {
  description = "AlertManager webhook URL for AgenticOps (empty = disabled)"
  type        = string
  default     = ""
}

# -----------------------------------------------------
# Tags
# -----------------------------------------------------
variable "tags" {
  description = "Additional tags for all resources"
  type        = map(string)
  default     = {}
}
```

- [ ] **Step 3: Create `locals.tf`**

```hcl
locals {
  azs = ["${var.region}a", "${var.region}b", "${var.region}c"]

  tags = merge(var.tags, {
    Project     = "agenticops"
    Environment = "lab"
    ManagedBy   = "terraform"
  })

  # AlertManager receiver config — conditionally include AgenticOps webhook
  alertmanager_receivers = var.alertmanager_webhook_url != "" ? [
    {
      name = "null"
    },
    {
      name = "agenticops"
      webhook_configs = [{
        url            = var.alertmanager_webhook_url
        send_resolved  = true
      }]
    }
  ] : [
    {
      name = "null"
    },
    {
      name = "agenticops"
    }
  ]
}
```

- [ ] **Step 4: Create `data.tf`**

```hcl
data "aws_caller_identity" "current" {}
```

- [ ] **Step 5: Validate syntax**

Run: `cd infra/eks-lab-tf && terraform fmt -check && terraform validate`
Expected: Files formatted, validation may warn about missing modules (OK at this stage)

- [ ] **Step 6: Commit**

```bash
git add infra/eks-lab-tf/versions.tf infra/eks-lab-tf/variables.tf infra/eks-lab-tf/locals.tf infra/eks-lab-tf/data.tf
git commit -m "feat(infra): scaffold terraform eks-lab — providers, variables, locals"
```

---

### Task 2: VPC — vpc.tf

**Files:**
- Create: `infra/eks-lab-tf/vpc.tf`

- [ ] **Step 1: Create `vpc.tf`**

```hcl
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
```

- [ ] **Step 2: Run `terraform fmt`**

Run: `cd infra/eks-lab-tf && terraform fmt`

- [ ] **Step 3: Commit**

```bash
git add infra/eks-lab-tf/vpc.tf
git commit -m "feat(infra): add VPC module — 3 AZs, private subnets, single NAT GW"
```

---

### Task 3: EKS Cluster — eks.tf

**Files:**
- Create: `infra/eks-lab-tf/eks.tf`

- [ ] **Step 1: Create `eks.tf`**

```hcl
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
```

- [ ] **Step 2: Run `terraform fmt`**

Run: `cd infra/eks-lab-tf && terraform fmt`

- [ ] **Step 3: Commit**

```bash
git add infra/eks-lab-tf/eks.tf
git commit -m "feat(infra): add EKS cluster — v1.30, 2 node groups, addons, IRSA"
```

---

### Task 4: Karpenter — karpenter.tf

**Files:**
- Create: `infra/eks-lab-tf/karpenter.tf`

- [ ] **Step 1: Create `karpenter.tf`**

```hcl
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
          "eks.amazonaws.com/role-arn" = module.karpenter.irsa_arn
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
```

- [ ] **Step 2: Run `terraform fmt`**

Run: `cd infra/eks-lab-tf && terraform fmt`

- [ ] **Step 3: Commit**

```bash
git add infra/eks-lab-tf/karpenter.tf
git commit -m "feat(infra): add Karpenter — controller, EC2NodeClass, NodePool (t/m families)"
```

---

### Task 5: AWS Load Balancer Controller — helm-infra.tf

**Files:**
- Create: `infra/eks-lab-tf/helm-infra.tf`

- [ ] **Step 1: Create `helm-infra.tf`**

```hcl
# ----- IRSA for AWS Load Balancer Controller -----
module "lb_controller_irsa" {
  source  = "terraform-aws-modules/iam/aws//modules/iam-role-for-service-accounts-eks"
  version = "~> 5.0"

  role_name                              = "${var.cluster_name}-lb-controller"
  attach_load_balancer_controller_policy = true

  oidc_providers = {
    main = {
      provider_arn               = module.eks.oidc_provider_arn
      namespace_service_accounts = ["kube-system:aws-load-balancer-controller"]
    }
  }

  tags = local.tags
}

# ----- AWS Load Balancer Controller Helm -----
resource "helm_release" "lb_controller" {
  namespace  = "kube-system"
  name       = "aws-load-balancer-controller"
  repository = "https://aws.github.io/eks-charts"
  chart      = "aws-load-balancer-controller"
  version    = "1.11.0"

  wait = true

  set {
    name  = "clusterName"
    value = module.eks.cluster_name
  }

  set {
    name  = "serviceAccount.create"
    value = "true"
  }

  set {
    name  = "serviceAccount.name"
    value = "aws-load-balancer-controller"
  }

  set {
    name  = "serviceAccount.annotations.eks\\.amazonaws\\.com/role-arn"
    value = module.lb_controller_irsa.iam_role_arn
  }

  set {
    name  = "region"
    value = var.region
  }

  set {
    name  = "vpcId"
    value = module.vpc.vpc_id
  }

  # Default to internal scheme
  set {
    name  = "defaultTargetType"
    value = "ip"
  }

  depends_on = [module.eks]
}
```

- [ ] **Step 2: Run `terraform fmt`**

Run: `cd infra/eks-lab-tf && terraform fmt`

- [ ] **Step 3: Commit**

```bash
git add infra/eks-lab-tf/helm-infra.tf
git commit -m "feat(infra): add AWS Load Balancer Controller — internal ALB only"
```

---

### Task 6: Monitoring Stack — helm-monitoring.tf + values/

**Files:**
- Create: `infra/eks-lab-tf/helm-monitoring.tf`
- Create: `infra/eks-lab-tf/values/prometheus.yaml`
- Create: `infra/eks-lab-tf/values/jaeger.yaml`
- Create: `infra/eks-lab-tf/values/otel-collector.yaml`

- [ ] **Step 1: Create `values/prometheus.yaml`**

Copy from `infra/eks-lab/monitoring/prometheus-values.yaml` with these changes:
- Remove the `<BASTION_PRIVATE_IP>` placeholder — AlertManager webhook URL comes from Terraform variable
- Keep all nodeSelector, tolerations, storage, resource settings identical

```yaml
prometheus:
  prometheusSpec:
    retention: 15d
    storageSpec:
      volumeClaimTemplate:
        spec:
          accessModes: ["ReadWriteOnce"]
          storageClassName: gp3
          resources:
            requests:
              storage: 50Gi
    nodeSelector:
      role: monitoring
    tolerations:
      - key: dedicated
        operator: Equal
        value: monitoring
        effect: NoSchedule
    resources:
      requests:
        cpu: 500m
        memory: 2Gi
      limits:
        cpu: "2"
        memory: 4Gi
    enableRemoteWriteReceiver: true
    serviceMonitorSelectorNilUsesHelmValues: false
    podMonitorSelectorNilUsesHelmValues: false

grafana:
  enabled: true
  service:
    type: ClusterIP
  persistence:
    enabled: true
    size: 10Gi
    storageClassName: gp3
  nodeSelector:
    role: monitoring
  tolerations:
    - key: dedicated
      operator: Equal
      value: monitoring
      effect: NoSchedule
  defaultDashboardsEnabled: true
  defaultDashboardsTimezone: utc

alertmanager:
  alertmanagerSpec:
    nodeSelector:
      role: monitoring
    tolerations:
      - key: dedicated
        operator: Equal
        value: monitoring
        effect: NoSchedule
    resources:
      requests:
        cpu: 100m
        memory: 256Mi
  config:
    global:
      resolve_timeout: 5m
    receivers:
      - name: "null"
      - name: agenticops
    route:
      group_by: ["alertname", "namespace"]
      group_wait: 30s
      group_interval: 5m
      repeat_interval: 4h
      receiver: agenticops
      routes:
        - matchers:
            - alertname = "Watchdog"
          receiver: "null"
        - matchers:
            - severity = "critical"
          group_wait: 10s
          group_interval: 1m
          repeat_interval: 1h
          receiver: agenticops

nodeExporter:
  enabled: true

kube-state-metrics:
  nodeSelector:
    role: monitoring
  tolerations:
    - key: dedicated
      operator: Equal
      value: monitoring
      effect: NoSchedule

prometheusOperator:
  nodeSelector:
    role: monitoring
  tolerations:
    - key: dedicated
      operator: Equal
      value: monitoring
      effect: NoSchedule
```

- [ ] **Step 2: Create `values/jaeger.yaml`**

Copy directly from `infra/eks-lab/monitoring/jaeger-values.yaml` — no changes needed.

```yaml
provisionDataStore:
  cassandra: false

allInOne:
  enabled: true
  extraEnv:
    - name: COLLECTOR_OTLP_ENABLED
      value: "true"
  resources:
    requests:
      cpu: 200m
      memory: 256Mi
    limits:
      cpu: "1"
      memory: 1Gi
  nodeSelector:
    role: monitoring
  tolerations:
    - key: dedicated
      operator: Equal
      value: monitoring
      effect: NoSchedule

storage:
  type: memory

query:
  service:
    type: ClusterIP

collector:
  service:
    otlp:
      grpc:
        name: otlp-grpc
        port: 4317
      http:
        name: otlp-http
        port: 4318
```

- [ ] **Step 3: Create `values/otel-collector.yaml`**

Copy from `infra/eks-lab/monitoring/otel-collector-values.yaml` — no changes needed.

```yaml
image:
  repository: otel/opentelemetry-collector-contrib

command:
  name: otelcol-contrib

mode: deployment
replicaCount: 1

resources:
  requests:
    cpu: 200m
    memory: 256Mi
  limits:
    cpu: "1"
    memory: 512Mi

nodeSelector:
  role: monitoring
tolerations:
  - key: dedicated
    operator: Equal
    value: monitoring
    effect: NoSchedule

service:
  type: ClusterIP

ports:
  otlp:
    enabled: true
    containerPort: 4317
    servicePort: 4317
    protocol: TCP
  otlp-http:
    enabled: true
    containerPort: 4318
    servicePort: 4318
    protocol: TCP

config:
  receivers:
    otlp:
      protocols:
        grpc:
          endpoint: 0.0.0.0:4317
        http:
          endpoint: 0.0.0.0:4318

  processors:
    batch:
      send_batch_size: 1024
      timeout: 5s
    memory_limiter:
      check_interval: 5s
      limit_mib: 400
      spike_limit_mib: 100

  exporters:
    prometheusremotewrite:
      endpoint: "http://prometheus-kube-prometheus-prometheus.monitoring:9090/api/v1/write"
      tls:
        insecure: true
      resource_to_telemetry_conversion:
        enabled: true
    otlp/jaeger:
      endpoint: "jaeger.monitoring:4317"
      tls:
        insecure: true
    debug:
      verbosity: basic
      sampling_initial: 5
      sampling_thereafter: 200

  service:
    pipelines:
      metrics:
        receivers: [otlp]
        processors: [memory_limiter, batch]
        exporters: [prometheusremotewrite, debug]
      traces:
        receivers: [otlp]
        processors: [memory_limiter, batch]
        exporters: [otlp/jaeger, debug]
      logs:
        receivers: [otlp]
        processors: [memory_limiter, batch]
        exporters: [debug]
```

- [ ] **Step 4: Create `helm-monitoring.tf`**

```hcl
# ----- Namespaces -----
resource "kubernetes_namespace" "monitoring" {
  metadata {
    name = "monitoring"
    labels = {
      project = "agenticops"
    }
  }

  depends_on = [module.eks]
}

resource "kubernetes_namespace" "online_boutique" {
  metadata {
    name = "online-boutique"
    labels = {
      project = "agenticops"
    }
  }

  depends_on = [module.eks]
}

# ----- gp3 StorageClass -----
resource "kubernetes_storage_class" "gp3" {
  metadata {
    name = "gp3"
  }

  storage_provisioner    = "ebs.csi.aws.com"
  reclaim_policy         = "Delete"
  volume_binding_mode    = "WaitForFirstConsumer"
  allow_volume_expansion = true

  parameters = {
    type   = "gp3"
    fsType = "ext4"
  }

  depends_on = [module.eks]
}

# ----- kube-prometheus-stack -----
resource "helm_release" "prometheus" {
  namespace  = kubernetes_namespace.monitoring.metadata[0].name
  name       = "prometheus"
  repository = "https://prometheus-community.github.io/helm-charts"
  chart      = "kube-prometheus-stack"
  version    = "72.3.0"

  timeout = 600
  wait    = true

  values = [file("${path.module}/values/prometheus.yaml")]

  # Inject Grafana password from variable
  set_sensitive {
    name  = "grafana.adminPassword"
    value = var.grafana_admin_password
  }

  # Conditionally inject AlertManager webhook
  dynamic "set" {
    for_each = var.alertmanager_webhook_url != "" ? [1] : []
    content {
      name  = "alertmanager.config.receivers[1].webhook_configs[0].url"
      value = var.alertmanager_webhook_url
    }
  }

  dynamic "set" {
    for_each = var.alertmanager_webhook_url != "" ? [1] : []
    content {
      name  = "alertmanager.config.receivers[1].webhook_configs[0].send_resolved"
      value = "true"
    }
  }

  depends_on = [kubernetes_storage_class.gp3]
}

# ----- Jaeger -----
resource "helm_release" "jaeger" {
  namespace  = kubernetes_namespace.monitoring.metadata[0].name
  name       = "jaeger"
  repository = "https://jaegertracing.github.io/helm-charts"
  chart      = "jaeger"
  version    = "3.4.1"

  timeout = 300
  wait    = true

  values = [file("${path.module}/values/jaeger.yaml")]

  depends_on = [helm_release.prometheus]
}

# ----- OpenTelemetry Collector -----
resource "helm_release" "otel_collector" {
  namespace  = kubernetes_namespace.monitoring.metadata[0].name
  name       = "otel-collector"
  repository = "https://open-telemetry.github.io/opentelemetry-helm-charts"
  chart      = "opentelemetry-collector"
  version    = "0.115.0"

  timeout = 300
  wait    = true

  values = [file("${path.module}/values/otel-collector.yaml")]

  depends_on = [helm_release.prometheus, helm_release.jaeger]
}
```

- [ ] **Step 5: Run `terraform fmt`**

Run: `cd infra/eks-lab-tf && terraform fmt`

- [ ] **Step 6: Commit**

```bash
git add infra/eks-lab-tf/helm-monitoring.tf infra/eks-lab-tf/values/
git commit -m "feat(infra): add monitoring stack — prometheus, jaeger, otel-collector"
```

---

### Task 7: Online Boutique Workload — helm-workload.tf + values/online-boutique.yaml

**Files:**
- Create: `infra/eks-lab-tf/helm-workload.tf`
- Create: `infra/eks-lab-tf/values/online-boutique.yaml`

- [ ] **Step 1: Create `values/online-boutique.yaml`**

```yaml
frontend:
  externalService: false
  service:
    type: ClusterIP

loadGenerator:
  create: true

opentelemetryCollector:
  create: false
  projectId: "agenticops-lab"

cartservice:
  env:
    - name: OTEL_EXPORTER_OTLP_ENDPOINT
      value: "http://otel-collector-opentelemetry-collector.monitoring:4317"

productcatalogservice:
  env:
    - name: OTEL_EXPORTER_OTLP_ENDPOINT
      value: "http://otel-collector-opentelemetry-collector.monitoring:4317"

currencyservice:
  env:
    - name: OTEL_EXPORTER_OTLP_ENDPOINT
      value: "http://otel-collector-opentelemetry-collector.monitoring:4317"

paymentservice:
  env:
    - name: OTEL_EXPORTER_OTLP_ENDPOINT
      value: "http://otel-collector-opentelemetry-collector.monitoring:4317"

shippingservice:
  env:
    - name: OTEL_EXPORTER_OTLP_ENDPOINT
      value: "http://otel-collector-opentelemetry-collector.monitoring:4317"

emailservice:
  env:
    - name: OTEL_EXPORTER_OTLP_ENDPOINT
      value: "http://otel-collector-opentelemetry-collector.monitoring:4317"

checkoutservice:
  env:
    - name: OTEL_EXPORTER_OTLP_ENDPOINT
      value: "http://otel-collector-opentelemetry-collector.monitoring:4317"

recommendationservice:
  env:
    - name: OTEL_EXPORTER_OTLP_ENDPOINT
      value: "http://otel-collector-opentelemetry-collector.monitoring:4317"

adservice:
  env:
    - name: OTEL_EXPORTER_OTLP_ENDPOINT
      value: "http://otel-collector-opentelemetry-collector.monitoring:4317"
```

- [ ] **Step 2: Create `helm-workload.tf`**

```hcl
resource "helm_release" "online_boutique" {
  namespace  = kubernetes_namespace.online_boutique.metadata[0].name
  name       = "online-boutique"
  repository = "oci://us-docker.pkg.dev/online-boutique-ci/charts"
  chart      = "onlineboutique"
  version    = "0.10.1"

  timeout = 600
  wait    = true

  values = [file("${path.module}/values/online-boutique.yaml")]

  depends_on = [helm_release.otel_collector]
}
```

- [ ] **Step 3: Run `terraform fmt`**

Run: `cd infra/eks-lab-tf && terraform fmt`

- [ ] **Step 4: Commit**

```bash
git add infra/eks-lab-tf/helm-workload.tf infra/eks-lab-tf/values/online-boutique.yaml
git commit -m "feat(infra): add Online Boutique workload with OTEL integration"
```

---

### Task 8: Outputs + tfvars — outputs.tf, terraform.tfvars

**Files:**
- Create: `infra/eks-lab-tf/outputs.tf`
- Create: `infra/eks-lab-tf/terraform.tfvars`

- [ ] **Step 1: Create `outputs.tf`**

```hcl
output "cluster_name" {
  description = "EKS cluster name"
  value       = module.eks.cluster_name
}

output "cluster_endpoint" {
  description = "EKS cluster API endpoint"
  value       = module.eks.cluster_endpoint
}

output "cluster_version" {
  description = "EKS cluster Kubernetes version"
  value       = module.eks.cluster_version
}

output "configure_kubectl" {
  description = "Command to configure kubectl"
  value       = "aws eks update-kubeconfig --name ${module.eks.cluster_name} --region ${var.region}"
}

output "vpc_id" {
  description = "VPC ID"
  value       = module.vpc.vpc_id
}

output "private_subnet_ids" {
  description = "Private subnet IDs"
  value       = module.vpc.private_subnets
}

output "karpenter_node_iam_role_name" {
  description = "IAM role name for Karpenter-provisioned nodes"
  value       = module.karpenter.node_iam_role_name
}

output "karpenter_irsa_arn" {
  description = "Karpenter controller IRSA ARN"
  value       = module.karpenter.irsa_arn
}
```

- [ ] **Step 2: Create `terraform.tfvars`**

```hcl
# AgenticOps EKS Lab — us-west-2
cluster_name    = "agenticops-lab"
region          = "us-west-2"
cluster_version = "1.30"

# Network
vpc_cidr        = "10.0.0.0/16"
private_subnets = ["10.0.101.0/24", "10.0.102.0/24", "10.0.103.0/24"]
public_subnets  = ["10.0.1.0/24", "10.0.2.0/24", "10.0.3.0/24"]

# Node Groups
workload_instance_type   = "t3.large"
workload_desired_size    = 3
workload_min_size        = 2
workload_max_size        = 5

monitoring_instance_type = "t3.large"
monitoring_desired_size  = 2
monitoring_min_size      = 1
monitoring_max_size      = 3

# Karpenter
karpenter_node_cpu_limit    = 32
karpenter_node_memory_limit = "64Gi"

# Optional
enable_guardduty = false

# Monitoring
grafana_admin_password   = "agenticops-lab"
alertmanager_webhook_url = ""

# Tags
tags = {
  Team = "agenticops"
}
```

- [ ] **Step 3: Run `terraform fmt`**

Run: `cd infra/eks-lab-tf && terraform fmt`

- [ ] **Step 4: Commit**

```bash
git add infra/eks-lab-tf/outputs.tf infra/eks-lab-tf/terraform.tfvars
git commit -m "feat(infra): add outputs and terraform.tfvars defaults"
```

---

### Task 9: README — ops manual

**Files:**
- Create: `infra/eks-lab-tf/README.md`

- [ ] **Step 1: Create `README.md`**

```markdown
# AgenticOps EKS Lab (Terraform)

Terraform-managed EKS lab in us-west-2 with Karpenter autoscaling, monitoring stack, and Online Boutique workload.

## Prerequisites

- Terraform >= 1.5
- AWS CLI configured with appropriate credentials
- kubectl >= 1.28
- helm >= 3.14

## Deploy

```bash
cd infra/eks-lab-tf

terraform init
terraform plan
terraform apply
```

Deployment takes ~20-25 minutes (EKS control plane ~10 min, node groups ~5 min, Helm releases ~5 min).

## Configure kubectl

```bash
$(terraform output -raw configure_kubectl)
```

## Access Services

All services are internal (ClusterIP). Access via port-forward:

```bash
# Grafana (admin / <grafana_admin_password>)
kubectl port-forward svc/prometheus-grafana -n monitoring 3000:80

# Prometheus
kubectl port-forward svc/prometheus-kube-prometheus-prometheus -n monitoring 9090:9090

# Jaeger UI
kubectl port-forward svc/jaeger-query -n monitoring 16686:16686

# Online Boutique
kubectl port-forward svc/frontend -n online-boutique 8080:80
```

## GuardDuty (Optional)

1. Enable GuardDuty with EKS Runtime Monitoring in the AWS Console for us-west-2
2. Set `enable_guardduty = true` in `terraform.tfvars`
3. Run `terraform apply`

## AlertManager Webhook (Optional)

To connect AgenticOps alert pipeline, set in `terraform.tfvars`:

```hcl
alertmanager_webhook_url = "http://<agenticops-host>:8000/api/webhooks/alert/prometheus"
```

Then run `terraform apply`.

## Karpenter

Karpenter auto-provisions nodes from t3/t3a/m5/m5a/m6i/m7i families (medium/large/xlarge) using on-demand or spot capacity.

Check Karpenter status:

```bash
kubectl get nodepools
kubectl get ec2nodeclasses
kubectl get nodeclaims
```

## Teardown

```bash
terraform destroy
```

This removes all resources including the EKS cluster, VPC, and NAT Gateway.

## Cost

~$8-12/day (3x t3.large workload + 2x t3.large monitoring + NAT GW + EKS control plane + Karpenter nodes on-demand).
```

- [ ] **Step 2: Commit**

```bash
git add infra/eks-lab-tf/README.md
git commit -m "docs(infra): add EKS lab Terraform ops manual"
```

---

### Task 10: Validate full configuration

- [ ] **Step 1: Run `terraform init`**

Run: `cd infra/eks-lab-tf && terraform init`
Expected: Providers and modules downloaded successfully

- [ ] **Step 2: Run `terraform fmt -recursive`**

Run: `cd infra/eks-lab-tf && terraform fmt -recursive -check`
Expected: No formatting issues

- [ ] **Step 3: Run `terraform validate`**

Run: `cd infra/eks-lab-tf && terraform validate`
Expected: `Success! The configuration is valid.`

- [ ] **Step 4: Run `terraform plan` (dry run)**

Run: `cd infra/eks-lab-tf && terraform plan`
Expected: Shows ~30-40 resources to create, no errors

- [ ] **Step 5: Final commit (if any fmt fixes)**

```bash
git add -A infra/eks-lab-tf/
git commit -m "fix(infra): terraform fmt and validation fixes"
```
