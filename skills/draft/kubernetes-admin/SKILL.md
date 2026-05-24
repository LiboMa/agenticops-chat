---
name: kubernetes-admin
description: "Kubernetes administration and troubleshooting — covers pod debugging (CrashLoopBackOff, OOMKilled, ImagePullBackOff, Pending), node issues, CNI/networking, CoreDNS, PVC/storage, HPA/VPA autoscaling, and EKS-specific patterns. Includes decision trees for common failure modes."
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
   - Check readiness probe: `kubectl get pod POD -o jsonpath='{.spec.containers[*].readinessProbe}'`
   - Exec into pod: `kubectl exec -it POD -- curl localhost:PORT/health`

### OOMKilled Remediation (Idempotent)

When a pod is OOMKilled (Exit Code 137), follow this sequence to safely adjust memory limits without duplicate patching:

1. **Confirm OOMKilled**:
   ```bash
   # Check termination reason (lightweight, avoids full describe)
   kubectl get pod POD -n NAMESPACE -o jsonpath='{range .status.containerStatuses[*]}{.name}{": reason="}{.lastState.terminated.reason}{", exitCode="}{.lastState.terminated.exitCode}{"\n"}{end}'
   ```

2. **Read current resource requests and limits BEFORE making changes**:
   ```bash
   # Get current memory requests and limits for all containers
   kubectl get pod POD -n NAMESPACE -o jsonpath='{range .spec.containers[*]}{.name}{": requests.memory="}{.resources.requests.memory}{", limits.memory="}{.resources.limits.memory}{"\n"}{end}'

   # If managed by a Deployment/StatefulSet, check the template (source of truth):
   kubectl get deployment DEPLOY -n NAMESPACE -o jsonpath='{range .spec.template.spec.containers[*]}{.name}{": requests.memory="}{.resources.requests.memory}{", limits.memory="}{.resources.limits.memory}{"\n"}{end}'
   ```

3. **Idempotency check — determine if patching is needed**:
   - Compare the current limit against the desired new limit
   - **If current limit already equals or exceeds the target value, do NOT apply the patch** — log that the resource is already at the desired state and skip
   - **If no limit is set**, treat current as unbounded and apply the patch
   - **If a VPA is managing resources**, check VPA recommendations first:
     ```bash
     kubectl get vpa -n NAMESPACE -o jsonpath='{range .items[*]}{.metadata.name}{": "}{.status.recommendation.containerRecommendations[*].upperBound.memory}{"\n"}{end}'
     ```

4. **Apply the memory adjustment (only if idempotency check passes)**:
   ```bash
   # Patch deployment with new memory limits
   kubectl patch deployment DEPLOY -n NAMESPACE --type='json' -p='[
     {"op": "replace", "path": "/spec/template/spec/containers/0/resources/limits/memory", "value": "NEW_LIMIT"},
     {"op": "replace", "path": "/spec/template/spec/containers/0/resources/requests/memory", "value": "NEW_REQUEST"}
   ]'
   ```

5. **Verify the patch was applied correctly**:
   ```bash
   # Confirm the new values match the intended target
   kubectl get deployment DEPLOY -n NAMESPACE -o jsonpath='{range .spec.template.spec.containers[*]}{.name}{": requests.memory="}{.resources.requests.memory}{", limits.memory="}{.resources.limits.memory}{"\n"}{end}'
   ```

6. **Monitor rollout**:
   ```bash
   kubectl rollout status deployment DEPLOY -n NAMESPACE --timeout=120s
   ```

**Sizing guidance for OOMKilled**:
- Start by increasing the memory limit by 25–50% above peak observed usage
- Check actual memory usage history: `kubectl top pod POD -n NAMESPACE --containers`
- If metrics-server is available, compare usage to limits to right-size rather than blindly doubling

### Node Issues

1. `kubectl get nodes` -- check STATUS (Ready/NotReady)
2. `kubectl describe node NODE` -- check Conditions section
   - MemoryPressure, DiskPressure, PIDPressure -> resource exhaustion
   - NetworkUnavailable -> CNI issue
3. `kubectl top node NODE` -- current CPU/memory usage
4. Node capacity: `kubectl get node NODE -o jsonpath='{.status.allocatable}' | jq .`
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
2. PVC Pending -> check Events with targeted output:
   ```bash
   kubectl get events -n NAMESPACE --field-selector involvedObject.name=PVC --sort-by='.lastTimestamp'
   ```
   - StorageClass not found -> `kubectl get sc`
   - Provisioner failed -> check CSI driver pods: `kubectl get pods -n kube-system | grep csi`
3. Access mode conflicts: check ReadWriteOnce vs ReadWriteMany
4. EBS: check AZ affinity (EBS volumes are AZ-bound)
5. Mount failures: check pod events:
   ```bash
   kubectl get events -n NAMESPACE --field-selector involvedObject.name=POD --sort-by='.lastTimestamp' | grep -i mount
   ```

### HPA/VPA Issues

1. `kubectl get hpa` -- check TARGETS column (current/target)
2. "unknown" targets -> metrics-server issue: `kubectl get pods -n kube-system | grep metrics-server`
3. Not scaling: check min/max replicas, check metrics: `kubectl get hpa HPA -o jsonpath='{.status.conditions[*].message}'`
4. Scaling too slow: check `--horizontal-pod-autoscaler-sync-period` and stabilization window

## Output Size Management

**CRITICAL**: Always prefer targeted queries over `kubectl describe` to avoid tool-result-too-large errors. Use `--field-selector`, `-o jsonpath`, and label selectors to narrow output.

### Preferred Patterns (Small Output)

```bash
# Instead of: kubectl describe pod POD
# Use targeted queries:

# Pod status and conditions
kubectl get pod POD -n NAMESPACE -o jsonpath='{.status.phase}{"\n"}{range .status.conditions[*]}{.type}{"="}{.status}{" "}{.message}{"\n"}{end}'

# Container statuses only
kubectl get pod POD -n NAMESPACE -o jsonpath='{range .status.containerStatuses[*]}{.name}{": ready="}{.ready}{", restarts="}{.restartCount}{", state="}{.state}{"\n"}{end}'

# Pod events only (instead of full describe)
kubectl get events -n NAMESPACE --field-selector involvedObject.name=POD --sort-by='.lastTimestamp'

# Instead of: kubectl describe node NODE
# Use targeted queries:

# Node conditions only
kubectl get node NODE -o jsonpath='{range .status.conditions[*]}{.type}{"="}{.status}{" "}{.message}{"\n"}{end}'

# Node allocatable resources
kubectl get node NODE -o jsonpath='{"cpu: "}{.status.allocatable.cpu}{"\nmemory: "}{.status.allocatable.memory}{"\npods: "}{.status.allocatable.pods}{"\n"}'

# Instead of: kubectl get pods --all-namespaces
# Use field selectors to filter:

# Only non-running pods
kubectl get pods --all-namespaces --field-selector 'status.phase!=Running,status.phase!=Succeeded'

# Only pods on a specific node
kubectl get pods --all-namespaces --field-selector spec.nodeName=NODE

# Only pods in a specific namespace with label
kubectl get pods -n NAMESPACE -l app=APPNAME -o wide
```

### Handling Large Outputs

```bash
# Limit events to recent (last hour)
kubectl get events -n NAMESPACE --sort-by='.lastTimestamp' | tail -20

# Get only pod names and statuses (minimal columns)
kubectl get pods -n NAMESPACE -o custom-columns='NAME:.metadata.name,STATUS:.status.phase,RESTARTS:.status.containerStatuses[0].restartCount,NODE:.spec.nodeName'

# For logs, limit line count
kubectl logs POD -n NAMESPACE --tail=100

# For logs with timestamps (narrow time window)
kubectl logs POD -n NAMESPACE --since=10m --tail=50

# Get resource requests/limits across all pods in namespace (compact)
kubectl get pods -n NAMESPACE -o custom-columns='POD:.metadata.name,CONTAINER:.spec.containers[0].name,CPU_REQ:.spec.containers[0].resources.requests.cpu,CPU_LIM:.spec.containers[0].resources.limits.cpu,MEM_REQ:.spec.containers[0].resources.requests.memory,MEM_LIM:.spec.containers[0].resources.limits.memory'
```

### When `describe` Is Necessary

If you must use `kubectl describe`, narrow the scope first:
1. Identify the specific field you need
2. Try jsonpath first
3. If describe is the only option, pipe through grep:
   ```bash
   # Only events section from describe
   kubectl describe pod POD -n NAMESPACE | grep -A 20 "^Events:"
   
   # Only conditions from node describe
   kubectl describe node NODE | grep -A 20 "^Conditions:"
   ```

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
kubectl get pods --all-namespaces --sort-by='.status.containerStatuses[0].restartCount' | tail -20

# Events timeline for a namespace (recent only)
kubectl get events --sort-by='.lastTimestamp' -n NAMESPACE | tail -30

# Resource usage sorted by CPU
kubectl top pods -n NAMESPACE --sort-by=cpu

# Resource usage sorted by memory
kubectl top pods -n NAMESPACE --sort-by=memory

# Find pods in non-Running state across all namespaces
kubectl get pods --all-namespaces --field-selector 'status.phase!=Running,status.phase!=Succeeded'

# Get all pods with their resource requests and limits (compact format)
kubectl get pods -n NAMESPACE -o custom-columns='POD:.metadata.name,CPU_REQ:.spec.containers[0].resources.requests.cpu,CPU_LIM:.spec.containers[0].resources.limits.cpu,MEM_REQ:.spec.containers[0].resources.requests.memory,MEM_LIM:.spec.containers[0].resources.limits.memory'

# Check OOMKilled across all pods in a namespace
kubectl get pods -n NAMESPACE -o jsonpath='{range .items[*]}{range .status.containerStatuses[*]}{.name}{" lastState.reason="}{.lastState.terminated.reason}{" restarts="}{.restartCount}{"\n"}{end}{end}' | grep -i oom
```

### Idempotent Remediation Checklist

Before applying **any** resource change (memory, CPU, replica count), always:

1. **Read current state** — query the exact field you intend to change using jsonpath
2. **Compare to desired state** — if already at target, skip and report "no change needed"
3. **Apply the change** — use `kubectl patch` with precise JSON path
4. **Verify post-change** — re-read the field to confirm it matches the target
5. **Monitor rollout** — ensure new pods start successfully after the change

This prevents:
- Duplicate patches that trigger unnecessary rollouts
- Drift from unexpected double-application (e.g., doubling memory twice)
- Unnecessary pod restarts in production environments
