# Internal Monitoring — Grafana + Prometheus (chaos-lab)

`kube-prometheus-stack` (Prometheus + Grafana + Alertmanager + node-exporter +
kube-state-metrics + default dashboards) on `agenticops-chaos-lab`, **internal-only**.

## Access (private — no public endpoint)

Everything is `ClusterIP`. Reach the UIs via `kubectl port-forward`:

```bash
# Grafana  → http://localhost:3000   (admin / <install password>)
kubectl port-forward svc/kps-grafana -n monitoring 3000:80

# Prometheus → http://localhost:9090
kubectl port-forward svc/kps-kube-prometheus-stack-prometheus -n monitoring 9090:9090

# Alertmanager → http://localhost:9093
kubectl port-forward svc/kps-kube-prometheus-stack-alertmanager -n monitoring 9093:9093
```

Get the Grafana admin password:
```bash
kubectl get secret kps-grafana -n monitoring -o jsonpath="{.data.admin-password}" | base64 -d; echo
```

## Prerequisites (already applied on the live cluster)

1. **EBS CSI driver** (for gp3 persistence):
   ```bash
   eksctl create iamserviceaccount --name ebs-csi-controller-sa --namespace kube-system \
     --cluster agenticops-chaos-lab --region us-east-1 \
     --role-name AmazonEKS_EBS_CSI_DriverRole_chaoslab \
     --attach-policy-arn arn:aws:iam::aws:policy/service-role/AmazonEBSCSIDriverPolicy \
     --approve --override-existing-serviceaccounts
   aws eks create-addon --cluster-name agenticops-chaos-lab --region us-east-1 \
     --addon-name aws-ebs-csi-driver \
     --service-account-role-arn arn:aws:iam::533267047935:role/AmazonEKS_EBS_CSI_DriverRole_chaoslab \
     --resolve-conflicts OVERWRITE
   ```
2. **gp3 default StorageClass** (provisioner `ebs.csi.aws.com`, encrypted).

## Install / upgrade

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm upgrade --install kps prometheus-community/kube-prometheus-stack \
  --namespace monitoring --create-namespace \
  -f infra/eks-chaos-lab/monitoring/kube-prometheus-stack-values.yaml \
  --set grafana.adminPassword='<your-password>'   # kept out of git
```

## Notes

- Sized for a 2× t3.medium test cluster; scheduled on the `chaos-lab` nodes
  (the `agenticops-app` node is tainted/dedicated). node-exporter tolerates all
  nodes for full coverage.
- Persistence: gp3 — Prometheus 20Gi (3-day retention), Grafana 5Gi, Alertmanager 2Gi.
- ServiceMonitor/PodMonitor auto-discovery is on across all namespaces, so any
  workload that exposes a `ServiceMonitor` is scraped automatically.
- Verified live: Grafana healthy with Prometheus + Alertmanager datasources
  auto-wired; Prometheus 28/28 targets up.
