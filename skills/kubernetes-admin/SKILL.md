---
name: kubernetes-admin
description: "Kubernetes administration and troubleshooting — covers pod debugging (CrashLoopBackOff, OOMKilled, ImagePullBackOff, Pending), node issues, CNI/networking, CoreDNS, PVC/storage, HPA/VPA autoscaling, and EKS-specific patterns. Includes decision trees for common failure modes."
metadata:
  author: agenticops
  version: "1.0"
  domain: containers
---

# Kubernetes Admin Skill

## Quick Decision Trees

### Pod Not Running

1. `kubectl get pod POD -o wide` -- check STATUS column
2. **Pending**: `kubectl describe pod POD` -> check Events section
   - "Insufficient cpu/memory" -> node capacity issue, check `kubectl top nodes`
   - "no nodes available" -> check node taints/tolerations, affinity rules
   - "Unschedulable" -> `kubectl get nodes` check for cordoned nodes
   - PVC pending -> `kubectl get pvc` check storage class
3. **CrashLoopBackOff**:
   - `kubectl logs POD -c CONTAINER --previous` -- check last crash logs
   - Common: OOMKilled, config errors, missing dependencies, health check failures
   - `kubectl describe pod POD` -> check Exit Code (137=OOM, 1=app error, 127=binary not found)
4. **ImagePullBackOff**:
   - Check image name/tag: `kubectl get pod POD -o jsonpath='{.spec.containers[*].image}'`
   - Check pull secret: `kubectl get pod POD -o jsonpath='{.spec.imagePullSecrets}'`
   - ECR token expiry: tokens expire every 12 hours
5. **Running but not Ready**:
   - Check readiness probe: `kubectl describe pod POD | grep -A5 Readiness`
   - Exec into pod: `kubectl exec -it POD -- curl localhost:PORT/health`

### Node Issues

1. `kubectl get nodes` -- check STATUS (Ready/NotReady)
2. `kubectl describe node NODE` -- check Conditions section
   - MemoryPressure, DiskPressure, PIDPressure -> resource exhaustion
   - NetworkUnavailable -> CNI issue
3. `kubectl top node NODE` -- current CPU/memory usage
4. Node capacity: `kubectl describe node NODE | grep -A10 "Allocated resources"`
5. Pods on node: `kubectl get pods --all-namespaces --field-selector spec.nodeName=NODE`

### Service/Networking Issues

1. `kubectl get svc SERVICE` -- check TYPE, CLUSTER-IP, EXTERNAL-IP, PORTS
2. `kubectl get endpoints SERVICE` -- verify backends exist
3. No endpoints -> check selector matches pod labels: `kubectl get pods -l key=value`
4. DNS: `kubectl exec -it debug-pod -- nslookup SERVICE.NAMESPACE.svc.cluster.local`
5. CoreDNS: `kubectl get pods -n kube-system -l k8s-app=kube-dns`
6. Network Policy: `kubectl get networkpolicy -n NAMESPACE`

### Storage Issues

1. `kubectl get pvc -n NAMESPACE` -- check STATUS (Bound/Pending)
2. PVC Pending -> `kubectl describe pvc PVC` -> check Events
   - StorageClass not found -> `kubectl get sc`
   - Provisioner failed -> check CSI driver pods: `kubectl get pods -n kube-system | grep csi`
3. Access mode conflicts: check ReadWriteOnce vs ReadWriteMany
4. EBS: check AZ affinity (EBS volumes are AZ-bound)
5. Mount failures: `kubectl describe pod POD` -> look for mount timeout events

### HPA/VPA Issues

1. `kubectl get hpa` -- check TARGETS column (current/target)
2. "unknown" targets -> metrics-server issue: `kubectl get pods -n kube-system | grep metrics-server`
3. Not scaling: check min/max replicas, check metrics: `kubectl describe hpa HPA`
4. Scaling too slow: check `--horizontal-pod-autoscaler-sync-period` and stabilization window

## Common Patterns

### Debug Containers

```bash
# Ephemeral debug container attached to a running pod
kubectl debug -it POD --image=busybox --target=CONTAINER

# Standalone network debugging pod
kubectl run debug --image=nicolaka/netshoot --rm -it -- /bin/bash

# Copy a running pod with debug image for investigation
kubectl debug POD --copy-to=debug-pod --image=ubuntu --share-processes
```

### Resource Investigation

```bash
# All pods by restart count (high restarts = recurring failures)
kubectl get pods --all-namespaces --sort-by='.status.containerStatuses[0].restartCount'

# Events timeline for a namespace
kubectl get events --sort-by='.lastTimestamp' -n NAMESPACE

# Resource usage sorted by CPU
kubectl top pods -n NAMESPACE --sort-by=cpu

# Resource usage sorted by memory
kubectl top pods -n NAMESPACE --sort-by=memory

# Find pods in non-Running state across all namespaces
kubectl get pods --all-namespaces --field-selector 'status.phase!=Running'

# Get all pods with their resource requests and limits
kubectl get pods -n NAMESPACE -o custom-columns='NAME:.metadata.name,CPU_REQ:.spec.containers[*].resources.requests.cpu,CPU_LIM:.spec.containers[*].resources.limits.cpu,MEM_REQ:.spec.containers[*].resources.requests.memory,MEM_LIM:.spec.containers[*].resources.limits.memory'
```

### Log Collection

```bash
# Stream logs from all pods with a label
kubectl logs -l app=myapp -f --all-containers

# Logs from previous container instance (after crash)
kubectl logs POD -c CONTAINER --previous

# Logs with timestamps (useful for correlation)
kubectl logs POD --timestamps=true --since=1h

# Logs from all containers in a pod
kubectl logs POD --all-containers=true
```

### Rollout Management

```bash
# Check rollout status
kubectl rollout status deployment/DEPLOY -n NAMESPACE

# View rollout history
kubectl rollout history deployment/DEPLOY

# Rollback to previous revision
kubectl rollout undo deployment/DEPLOY

# Rollback to specific revision
kubectl rollout undo deployment/DEPLOY --to-revision=3

# Pause/resume rollout for canary-style deployment
kubectl rollout pause deployment/DEPLOY
kubectl rollout resume deployment/DEPLOY
```

### ConfigMap and Secret Debugging

```bash
# Check if configmap exists and view contents
kubectl get configmap CM -n NAMESPACE -o yaml

# Check if secret exists (values are base64 encoded)
kubectl get secret SECRET -n NAMESPACE -o jsonpath='{.data}'

# Decode a secret value
kubectl get secret SECRET -n NAMESPACE -o jsonpath='{.data.password}' | base64 -d

# Verify environment variables in running pod
kubectl exec POD -- env | sort

# Check mounted volumes
kubectl exec POD -- ls -la /path/to/mount
```

## EKS-Specific Patterns

### IAM/IRSA Issues

```bash
# Verify IRSA annotation on service account
kubectl get sa SERVICE_ACCOUNT -n NAMESPACE -o jsonpath='{.metadata.annotations}'

# Check if the pod has the expected AWS identity
kubectl exec POD -- aws sts get-caller-identity

# Verify OIDC provider is configured
aws eks describe-cluster --name CLUSTER --query 'cluster.identity.oidc'
```

### EKS Node Group Troubleshooting

```bash
# Check managed node group status
aws eks describe-nodegroup --cluster-name CLUSTER --nodegroup-name NG

# Check ASG health for managed node groups
aws autoscaling describe-auto-scaling-groups --auto-scaling-group-names ASG_NAME

# Check for failed instance launches in ASG activity
aws autoscaling describe-scaling-activities --auto-scaling-group-name ASG_NAME --max-items 10
```

### CoreDNS Troubleshooting

```bash
# Check CoreDNS pod status and logs
kubectl get pods -n kube-system -l k8s-app=kube-dns
kubectl logs -n kube-system -l k8s-app=kube-dns

# Verify CoreDNS config
kubectl get configmap coredns -n kube-system -o yaml

# Test DNS resolution from inside a pod
kubectl run dns-test --image=busybox:1.36 --rm -it -- nslookup kubernetes.default.svc.cluster.local

# Check if CoreDNS is overloaded (high latency)
kubectl top pods -n kube-system -l k8s-app=kube-dns
```

## Monitoring Queries

### Key Metrics to Watch

| Metric | Source | Threshold |
|--------|--------|-----------|
| Pod restart count | kube_pod_container_status_restarts_total | > 5 in 1h |
| Node CPU | node_cpu_seconds_total | > 80% sustained |
| Node memory | node_memory_MemAvailable_bytes | < 10% available |
| PVC usage | kubelet_volume_stats_used_bytes | > 85% |
| API server latency | apiserver_request_duration_seconds | p99 > 1s |
| etcd latency | etcd_request_duration_seconds | p99 > 100ms |
| Pending pods | kube_pod_status_phase{phase="Pending"} | > 0 for 5m |
| Failed jobs | kube_job_status_failed | > 0 |

### Capacity Planning

```bash
# Cluster-wide resource allocation summary
kubectl describe nodes | grep -A5 "Allocated resources"

# Namespace resource quotas
kubectl get resourcequota -n NAMESPACE

# Namespace limit ranges
kubectl get limitrange -n NAMESPACE

# Pod density per node (check against max-pods limit)
kubectl get nodes -o custom-columns='NAME:.metadata.name,PODS:.status.allocatable.pods'
```
