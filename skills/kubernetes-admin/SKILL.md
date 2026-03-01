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

## Fix/Remediation Decision Trees

Automated fix patterns for common Kubernetes failures. The SRE agent uses these to generate
fix plans with appropriate risk levels, rollback procedures, and sizing guidance.

### OOMKilled Fix Path

**Symptom:** Exit code 137, CrashLoopBackOff, `kubectl describe pod` shows OOMKilled in
container last state.

**Investigation:**

```bash
# Confirm OOMKilled
kubectl get pod POD -n NAMESPACE -o jsonpath='{.status.containerStatuses[*].lastState.terminated.reason}'

# Get current memory limit
kubectl get pod POD -n NAMESPACE -o jsonpath='{.spec.containers[*].resources.limits.memory}'

# Get observed peak memory usage
kubectl top pod POD -n NAMESPACE --containers
```

**Fix:**

```bash
# Set new memory limit to 2x the observed peak memory usage from kubectl top pod
kubectl set resources deploy/DEPLOY -n NAMESPACE --limits=memory=NEW_LIMIT
```

**Sizing guidance:** Set the memory limit to 2x the observed peak memory usage from
`kubectl top pod`. For example, if peak usage is 400Mi, set the limit to 800Mi. For JVM
apps, set `-Xmx` to 75% of the container memory limit.

**Risk:** L1 (low-risk, pods restart gracefully via rolling update)

**Rollback:**

```bash
kubectl rollout undo deploy/DEPLOY -n NAMESPACE
```

### ImagePullBackOff Fix Path

**Symptom:** ImagePullBackOff status. Events show "image not found", "manifest unknown",
or "unauthorized".

**Investigation:**

```bash
# Check the image reference
kubectl get pod POD -n NAMESPACE -o jsonpath='{.spec.containers[*].image}'

# Check events for the specific error
kubectl describe pod POD -n NAMESPACE | grep -A5 "Events"

# Check imagePullSecrets
kubectl get pod POD -n NAMESPACE -o jsonpath='{.spec.imagePullSecrets}'
```

**Fix option 1 (bad tag/image name):** Roll back to the last known good image.

```bash
kubectl rollout undo deploy/DEPLOY -n NAMESPACE
```

**Fix option 2 (ECR auth expired):** Refresh the ECR authentication token. ECR tokens
expire every 12 hours.

```bash
# Refresh ECR token and update pull secret
aws ecr get-login-password --region REGION | kubectl create secret docker-registry ecr-secret \
  --docker-server=ACCOUNT.dkr.ecr.REGION.amazonaws.com \
  --docker-username=AWS \
  --docker-password-stdin \
  -n NAMESPACE --dry-run=client -o yaml | kubectl apply -f -
```

**Risk:** L1

**Rollback:** Fix option 1 is already a rollback. For fix option 2, no rollback needed
(authentication is additive).

### Deployment ReplicasMismatch Fix Path

**Symptom:** Desired replicas != available replicas. `kubectl get deploy DEPLOY` shows
mismatch in READY column.

**Investigation:**

```bash
# Check deployment status
kubectl get deploy DEPLOY -n NAMESPACE

# Check pod events for the unhealthy replicas
kubectl describe deploy DEPLOY -n NAMESPACE

# Check if pods are pending (node capacity)
kubectl get pods -n NAMESPACE -l app=APP_LABEL --field-selector 'status.phase=Pending'

# Check node capacity
kubectl top nodes
kubectl describe nodes | grep -A5 "Allocated resources"
```

**Fix:** Depends on root cause:
- **Resource limits too tight:** `kubectl set resources deploy/DEPLOY -n NAMESPACE --limits=cpu=NEW_CPU --limits=memory=NEW_MEM`
- **Node capacity exhausted:** Scale the node group (EKS: `aws eks update-nodegroup-config --cluster-name CLUSTER --nodegroup-name NG --scaling-config minSize=N,maxSize=M,desiredSize=D`)
- **Scheduling constraints:** Check taints/tolerations and node affinity rules
- **Readiness probe failing:** Fix the health check or adjust probe parameters

**Risk:** Varies by root cause (L1 for resource adjustments, L2 for node scaling)

**Rollback:**

```bash
kubectl rollout undo deploy/DEPLOY -n NAMESPACE
```

### Node NotReady Fix Path

**Symptom:** `kubectl get nodes` shows one or more nodes in NotReady status.

**Investigation:**

```bash
# Check which nodes are NotReady
kubectl get nodes | grep NotReady

# Check node conditions (DiskPressure, MemoryPressure, PIDPressure, NetworkUnavailable)
kubectl describe node NODE | grep -A10 "Conditions"

# Check kubelet status on the node (requires host access)
# run_on_host: systemctl status kubelet
```

**Fix (DiskPressure):** Clean disk space on the node, then uncordon if needed.

```bash
# Via run_on_host: clean unused container images and logs
# run_on_host: crictl rmi --prune
# run_on_host: journalctl --vacuum-size=500M

# Uncordon the node after recovery
kubectl uncordon NODE
```

**Fix (MemoryPressure):** Drain the node, restart kubelet.

```bash
# Drain workloads off the node (respects PDBs)
kubectl drain NODE --ignore-daemonsets --delete-emptydir-data

# Via run_on_host: restart kubelet
# run_on_host: systemctl restart kubelet

# Uncordon after recovery
kubectl uncordon NODE
```

**Risk:** L2 (affects workloads on that node; drain moves pods but causes disruption)

**Rollback:** Uncordon the node to allow scheduling again:

```bash
kubectl uncordon NODE
```

### CoreDNS Recovery

**Symptom:** DNS resolution failures cluster-wide. Pods cannot resolve service names or
external domains.

**Investigation:**

```bash
# Check CoreDNS pod status
kubectl get pods -n kube-system -l k8s-app=kube-dns

# Check CoreDNS logs for errors
kubectl logs -n kube-system -l k8s-app=kube-dns --tail=50

# Verify CoreDNS service endpoint
kubectl get endpoints -n kube-system kube-dns
```

**Fix:** CoreDNS usually self-recovers via its ReplicaSet. If pods are stuck in
CrashLoopBackOff or not responding:

```bash
kubectl rollout restart deploy/coredns -n kube-system
```

**Risk:** L1 (brief DNS disruption during restart, typically < 30 seconds with multiple
replicas)

**Rollback:** CoreDNS is managed by EKS/the cluster; a rollout restart uses the same
image and config. If a config change caused the issue, restore the ConfigMap:

```bash
kubectl get configmap coredns -n kube-system -o yaml > coredns-backup.yaml
# Edit and reapply: kubectl apply -f coredns-backup.yaml
```

### HPA Not Scaling Fix Path

**Symptom:** HPA shows `<unknown>` in TARGETS column, or refuses to scale beyond current
replica count.

**Investigation:**

```bash
# Check HPA status and targets
kubectl get hpa HPA -n NAMESPACE

# Check HPA events for errors
kubectl describe hpa HPA -n NAMESPACE

# Verify metrics-server is running
kubectl get pods -n kube-system | grep metrics-server

# Check if metrics-server can reach the kubelet
kubectl top pods -n NAMESPACE
```

**Fix (unknown targets -- metrics-server issue):**

```bash
# Restart metrics-server
kubectl rollout restart deploy/metrics-server -n kube-system
```

**Fix (maxReplicas too low):**

```bash
kubectl patch hpa HPA -n NAMESPACE -p '{"spec":{"maxReplicas":NEW_MAX}}'
```

**Risk:** L1

**Rollback:**

```bash
# Restore original maxReplicas
kubectl patch hpa HPA -n NAMESPACE -p '{"spec":{"maxReplicas":ORIGINAL_MAX}}'
```

### PVC Pending Fix Path

**Symptom:** PVC stuck in Pending state. Pods that mount the PVC are also Pending.

**Investigation:**

```bash
# Check PVC status and events
kubectl describe pvc PVC -n NAMESPACE

# List available StorageClasses
kubectl get sc

# Check CSI driver pods
kubectl get pods -n kube-system | grep csi
```

**Fix (wrong StorageClass):** PVC storageClassName is immutable after creation. Must
delete and recreate:

```bash
# Export the PVC spec
kubectl get pvc PVC -n NAMESPACE -o yaml > pvc-backup.yaml
# Edit storageClassName in the file, then:
kubectl delete pvc PVC -n NAMESPACE
kubectl apply -f pvc-backup.yaml
```

**Fix (CSI driver not running):**

```bash
# Restart the CSI driver (e.g., EBS CSI)
kubectl rollout restart deploy/ebs-csi-controller -n kube-system
```

**Risk:** L2 (may affect data if PVC is deleted; ensure no data loss before deleting)

**Rollback:** Recreate the PVC with the original StorageClass from the backup YAML.

### Service Crash (Missing Deployment) Fix Path

**Symptom:** 5xx errors from a service. The backing deployment or pods are missing or
have zero ready replicas.

**Investigation:**

```bash
# Check if deployment exists
kubectl get deploy -n NAMESPACE

# Check if pods exist for the service
kubectl get endpoints SVC -n NAMESPACE

# Check recent events for deletions
kubectl get events -n NAMESPACE --sort-by='.lastTimestamp' | grep -i "delete\|kill"
```

**Fix:** Reapply the Kubernetes manifests from source control or backup.

```bash
kubectl apply -f kubernetes-manifests.yaml -n NAMESPACE
```

If manifests are not available, scale the deployment back up:

```bash
kubectl scale deploy/DEPLOY -n NAMESPACE --replicas=DESIRED_COUNT
```

**Risk:** L1 (restoring a deployment is a standard operation)

**Rollback:**

```bash
kubectl rollout undo deploy/DEPLOY -n NAMESPACE
```
