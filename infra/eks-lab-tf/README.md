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
