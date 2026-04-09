# Terraform EKS Lab — Design Spec

**Date:** 2026-04-09
**Status:** Approved
**Location:** `infra/eks-lab-tf/`

## Goal

Convert the existing `infra/eks-lab/` (eksctl + shell scripts) into a fully Terraform-managed EKS lab environment in us-west-2. Single `terraform apply` provisions VPC, EKS cluster, Karpenter, monitoring stack, and workloads.

## Approach

Community modules (`terraform-aws-modules/vpc/aws`, `terraform-aws-modules/eks/aws`) + Helm provider for application stack. Chosen for reduced boilerplate, battle-tested IAM handling, and maintainability.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│ VPC 10.0.0.0/16  (us-west-2)                            │
│                                                         │
│  Public Subnets (3 AZs)         Private Subnets (3 AZs)│
│  10.0.1-3.0/24                  10.0.101-103.0/24       │
│  ┌──────────┐                   ┌─────────────────────┐ │
│  │ NAT GW   │                   │ EKS Nodes           │ │
│  │ (single) │                   │  - workload (3)     │ │
│  └──────────┘                   │  - monitoring (2)   │ │
│                                 │  - karpenter (auto)  │ │
│                                 │                     │ │
│                                 │ Internal ALB only   │ │
│                                 └─────────────────────┘ │
└─────────────────────────────────────────────────────────┘
         │
    EKS Public API Endpoint (kubectl access from local)
```

## Network (vpc.tf)

- **Module:** `terraform-aws-modules/vpc/aws`
- **CIDR:** `10.0.0.0/16`
- **AZs:** us-west-2a, us-west-2b, us-west-2c
- **Private subnets:** `10.0.101.0/24`, `10.0.102.0/24`, `10.0.103.0/24` — all nodes here
- **Public subnets:** `10.0.1.0/24`, `10.0.2.0/24`, `10.0.3.0/24` — NAT GW only
- **NAT Gateway:** single (cost savings for lab)
- **Subnet tags:**
  - Private: `kubernetes.io/role/internal-elb = 1` (internal ALB discovery)
  - No `kubernetes.io/role/elb` on public subnets (prevents public ALB)
  - Both: `kubernetes.io/cluster/agenticops-lab = shared`

## EKS Cluster (eks.tf)

- **Module:** `terraform-aws-modules/eks/aws`
- **Name:** `agenticops-lab`
- **Version:** `1.30`
- **API endpoint:** public + private (public for local kubectl, private for in-cluster)
- **OIDC:** enabled (required for IRSA — Karpenter, EBS CSI, LB Controller)
- **CloudWatch logging:** api, audit, authenticator, controllerManager, scheduler
- **Managed addons:** vpc-cni, coredns, kube-proxy, aws-ebs-csi-driver (with IRSA)

### Managed Node Groups

| Group | Instance | Min/Desired/Max | Volume | Labels | Taints |
|-------|----------|-----------------|--------|--------|--------|
| workload | t3.large | 2 / 3 / 5 | 50GB gp3 | `role=workload` | none |
| monitoring | t3.large | 1 / 2 / 3 | 80GB gp3 | `role=monitoring` | `dedicated=monitoring:NoSchedule` |

## Karpenter (karpenter.tf)

- **Module:** `terraform-aws-modules/eks/aws//modules/karpenter`
- **Controller:** Helm chart `karpenter/karpenter` in `kube-system`
- **IRSA:** dedicated role with SQS, EC2, pricing, SSM permissions
- **SQS queue:** for spot interruption handling

### EC2NodeClass

- AMI family: `AL2023`
- Subnets: private only (via discovery tags)
- Security groups: EKS cluster node SG
- Volume: 50GB gp3
- Tags: `project=agenticops`, `environment=lab`

### NodePool

- Instance families: `t3`, `t3a`, `m5`, `m5a`, `m6i`, `m7i`
- Sizes: `medium`, `large`, `xlarge`
- Capacity types: `on-demand`, `spot`
- Architecture: `amd64`
- Limits: 32 vCPU / 64 GiB memory
- Consolidation: `WhenEmptyOrUnderutilized`
- TTL: 24h expiry (forces node rotation)

## Helm Releases (helm.tf)

All deployed via `helm_release` Terraform resources.

### Monitoring Stack (namespace: `monitoring`)

All monitoring pods use tolerations for `dedicated=monitoring:NoSchedule` and nodeSelector `role=monitoring`.

| Chart | Repo | Notes |
|-------|------|-------|
| `kube-prometheus-stack` | prometheus-community | Prometheus + Grafana + AlertManager |
| `jaeger` (all-in-one) | jaegertracing | In-memory storage, query on 16686 |
| `opentelemetry-collector` | open-telemetry | OTLP receiver, exports to Prometheus + Jaeger |

### Infrastructure (namespace: `kube-system`)

| Chart | Repo | Notes |
|-------|------|-------|
| `aws-load-balancer-controller` | eks | IRSA role, internal scheme only |

### Workload (namespace: `online-boutique`)

| Resource | Method | Notes |
|----------|--------|-------|
| Online Boutique | `kubectl_manifest` from upstream YAML | 11 microservices, OTEL env vars patched |

### Dependency Chain

```
VPC → EKS → Node Groups ready → Karpenter
                               → LB Controller
                               → Monitoring stack → OTEL Collector
                               → Online Boutique (after OTEL ready)
```

## File Structure

```
infra/eks-lab-tf/
├── versions.tf        # terraform 1.5+, providers: aws, helm, kubernetes, kubectl
├── variables.tf       # cluster_name, region, vpc_cidr, instance types, Karpenter limits
├── locals.tf          # tags, AZ list, computed values
├── vpc.tf             # VPC module
├── eks.tf             # EKS module + managed node groups + addons
├── karpenter.tf       # Karpenter module + controller Helm + NodePool + EC2NodeClass
├── helm.tf            # Helm releases: monitoring, LB controller, Online Boutique
├── outputs.tf         # cluster endpoint, kubeconfig command, node group ARNs
├── terraform.tfvars   # lab defaults
└── README.md          # ops manual: prereqs, deploy, access, teardown
```

## Access Pattern

- All services internal only (private ALB, ClusterIP)
- Access via `kubectl port-forward` through public API endpoint
- No bastion required
- README.md documents port-forward commands for Grafana, Prometheus, Jaeger, Online Boutique

## Cost Estimate

~$8-12/day:
- 3x t3.large (workload): ~$7.50/day
- 2x t3.large (monitoring): ~$5/day
- NAT Gateway: ~$1/day
- Karpenter nodes: on-demand as needed
- EKS control plane: $0.10/hr = $2.40/day

## Decisions Log

| Decision | Choice | Rationale |
|----------|--------|-----------|
| VPC | Self-contained, new | Clean isolation in us-west-2, no external dependencies |
| Bastion | None | kubectl via public API endpoint, port-forward for services |
| ALB | Internal only | No public-facing services for lab |
| Node sizing | t3.large | Cost savings vs m5.large, sufficient for lab workloads |
| Karpenter instances | t + m families | Broad flexibility for autoscaling tests |
| NAT Gateway | Single | Cost savings, acceptable for lab (not HA) |
| Modules | terraform-aws-modules | Reduced boilerplate, battle-tested |
| Helm in TF | Yes | Single terraform apply for full stack |
