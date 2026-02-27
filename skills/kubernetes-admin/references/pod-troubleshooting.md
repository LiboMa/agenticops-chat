# Pod Troubleshooting Deep Dive

## Exit Codes Reference

Exit codes tell you exactly how a container terminated. Understanding them is the fastest
path to root cause.

| Exit Code | Signal | Meaning | Common Cause |
|-----------|--------|---------|--------------|
| 0 | - | Success | Normal completion (expected for Jobs, not for long-running pods) |
| 1 | - | Application error | Unhandled exception, assertion failure, misconfiguration |
| 2 | - | Misuse of shell builtin | Shell script syntax error in entrypoint |
| 126 | - | Command not executable | Permission denied on entrypoint binary |
| 127 | - | Command not found | Binary missing in image, wrong entrypoint path |
| 128+N | Signal N | Killed by signal N | See signal table below |
| 137 | SIGKILL (9) | Killed forcefully | OOMKilled, `kubectl delete --force`, liveness probe failure after grace period |
| 143 | SIGTERM (15) | Terminated gracefully | Normal shutdown, rolling update, pod eviction |

### Signal-Based Exit Codes (128 + signal number)

```
128 + 1  = 129  (SIGHUP)   - Terminal hangup
128 + 2  = 130  (SIGINT)   - Ctrl+C / interrupt
128 + 6  = 134  (SIGABRT)  - Abort (core dump)
128 + 9  = 137  (SIGKILL)  - Force kill (OOM or force delete)
128 + 11 = 139  (SIGSEGV)  - Segfault (null pointer, buffer overflow)
128 + 15 = 143  (SIGTERM)  - Graceful termination
```

### Diagnosing Exit Code 137 (OOMKilled)

The most common cause of exit code 137 is the kernel OOM killer. Verify with:

```bash
# Check if the container was OOMKilled
kubectl get pod POD -o jsonpath='{.status.containerStatuses[*].lastState.terminated.reason}'
# Output: OOMKilled

# Check the container's memory limit vs actual usage
kubectl describe pod POD | grep -A3 "Limits"

# Check node-level OOM events
kubectl describe node NODE | grep -i oom

# Check kernel OOM killer logs on the node (if accessible)
dmesg | grep -i "oom\|killed process"
```

**Fix strategies for OOMKilled:**
1. Increase memory limits in the pod spec
2. Fix memory leaks in the application (check heap dumps, profiling)
3. Tune JVM heap for Java apps: `-Xmx` should be 75% of container memory limit
4. For Go apps: check goroutine leaks with `runtime.NumGoroutine()`

## Init Container Failures

Init containers run sequentially before the main containers start. If any init container
fails, the pod stays in `Init:CrashLoopBackOff`.

```bash
# Check init container status
kubectl get pod POD -o jsonpath='{.status.initContainerStatuses[*].name}'
kubectl get pod POD -o jsonpath='{.status.initContainerStatuses[*].state}'

# Logs from a specific init container
kubectl logs POD -c INIT_CONTAINER_NAME

# Common init container patterns and failure modes:
# 1. wait-for-db: fails because DB is not ready -> check DB service endpoint
# 2. migration: fails because schema conflict -> check migration logs
# 3. config-fetcher: fails because secret not available -> check RBAC
# 4. volume-permission: fails because PVC not bound -> check PVC status
```

### Init Container Debugging Workflow

```bash
# Step 1: identify which init container is failing
kubectl describe pod POD | grep -A20 "Init Containers"

# Step 2: check the init container logs
kubectl logs POD -c init-container-name

# Step 3: if the init container exits too quickly to capture logs,
# override the command to keep it running
kubectl debug POD --copy-to=debug-pod --container=init-container-name -- sleep 3600
kubectl exec -it debug-pod -c init-container-name -- /bin/sh
```

## Sidecar Patterns and Failures

Sidecars (additional containers in the same pod) share network and optionally storage.
Failures in sidecars can cause subtle issues.

### Common Sidecar Issues

| Sidecar | Issue | Symptom | Fix |
|---------|-------|---------|-----|
| Istio envoy | Sidecar not ready | Connection refused on port 15001 | Check istio-proxy logs, verify mTLS config |
| Fluentd/Fluent Bit | Log shipping fails | Logs missing in destination | Check output plugin config, buffer overflow |
| Vault agent | Secret injection fails | App gets empty env vars | Check Vault policy, service account token |
| CloudSQL proxy | DB connection fails | Connection refused on localhost:5432 | Check IAM permissions, instance connection name |

```bash
# Check all container statuses in a multi-container pod
kubectl get pod POD -o jsonpath='{range .status.containerStatuses[*]}{.name}: {.state}{"\n"}{end}'

# Logs from a specific sidecar container
kubectl logs POD -c sidecar-name

# Check if sidecar is consuming too many resources
kubectl top pod POD --containers
```

## Resource Requests vs Limits

Understanding the difference is critical for scheduling and stability.

### How They Work

| Property | Requests | Limits |
|----------|----------|--------|
| Purpose | Scheduling guarantee | Runtime ceiling |
| Scheduler uses | Yes (to find a node) | No |
| Enforced by | kubelet (admission) | cgroup (runtime) |
| CPU over-limit | N/A (throttled, not killed) | CPU throttled |
| Memory over-limit | N/A | OOMKilled |

### Best Practices

```yaml
resources:
  requests:
    cpu: "250m"       # 0.25 CPU cores guaranteed
    memory: "256Mi"   # 256 MiB guaranteed
  limits:
    cpu: "500m"       # Throttled above 0.5 cores (not killed)
    memory: "512Mi"   # OOMKilled above 512 MiB
```

**Rules of thumb:**
- Always set memory limits (prevents node-level OOM that kills random pods)
- Set CPU requests but consider NOT setting CPU limits (throttling causes latency spikes)
- requests.memory should be close to actual usage (prevents overcommit)
- requests.cpu should reflect average usage, not peak

### Diagnosing Resource Issues

```bash
# Check if pod is being CPU-throttled
# Look for nr_throttled and throttled_time in cgroup stats
kubectl exec POD -- cat /sys/fs/cgroup/cpu/cpu.stat

# Check memory usage vs limit
kubectl exec POD -- cat /sys/fs/cgroup/memory/memory.usage_in_bytes
kubectl exec POD -- cat /sys/fs/cgroup/memory/memory.limit_in_bytes

# Check VPA recommendations (if VPA is installed)
kubectl get vpa -n NAMESPACE
kubectl describe vpa VPA_NAME -n NAMESPACE
```

## QoS Classes

Kubernetes assigns a QoS class to each pod based on resource specs. This affects
eviction priority when the node is under pressure.

| QoS Class | Criteria | Eviction Priority |
|-----------|----------|-------------------|
| **Guaranteed** | All containers have requests == limits for both CPU and memory | Last (lowest priority for eviction) |
| **Burstable** | At least one container has a request or limit set | Middle |
| **BestEffort** | No containers have any requests or limits | First (highest priority for eviction) |

```bash
# Check a pod's QoS class
kubectl get pod POD -o jsonpath='{.status.qosClass}'
```

**Production recommendation:** All production workloads should be Guaranteed or Burstable.
Never run BestEffort in production -- they will be the first evicted under memory pressure.

## Eviction Thresholds

The kubelet evicts pods when node resources cross these thresholds:

| Resource | Soft Threshold (default) | Hard Threshold (default) | Grace Period |
|----------|-------------------------|-------------------------|--------------|
| Memory | memory.available < 100Mi | memory.available < 100Mi | 0s (immediate) |
| Disk (nodefs) | nodefs.available < 10% | nodefs.available < 5% | 0s |
| Disk (imagefs) | imagefs.available < 15% | imagefs.available < 5% | 0s |
| PID | pid.available < 10% | pid.available < 5% | 0s |

```bash
# Check kubelet eviction configuration
kubectl get node NODE -o jsonpath='{.status.conditions}' | python3 -m json.tool

# Check for eviction events
kubectl get events --field-selector reason=Evicted -n NAMESPACE
```

## Pod Priority and Preemption

Higher priority pods can preempt (evict) lower priority pods to get scheduled.

```bash
# List priority classes
kubectl get priorityclass

# Check a pod's priority
kubectl get pod POD -o jsonpath='{.spec.priority} {.spec.priorityClassName}'

# Check if a pod was preempted
kubectl get events --field-selector reason=Preempted -n NAMESPACE
```

### Default Priority Classes

| Priority Class | Value | Description |
|---------------|-------|-------------|
| system-cluster-critical | 2000000000 | Core cluster components (kube-apiserver, etcd) |
| system-node-critical | 2000001000 | Node-level components (kube-proxy, CNI) |
| (user-defined) | < 1000000000 | Application workloads |

### Creating a Priority Class for Production Workloads

```yaml
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: production-high
value: 1000000
globalDefault: false
preemptionPolicy: PreemptLowerPriority
description: "High priority for production workloads"
```

## Pod Disruption Budgets (PDB)

PDBs prevent voluntary disruptions (drains, upgrades) from taking down too many pods.

```bash
# Check existing PDBs
kubectl get pdb -n NAMESPACE

# Verify PDB is protecting your deployment
kubectl describe pdb PDB_NAME -n NAMESPACE
# Look for: Allowed disruptions, Current/Desired/Expected pods
```

### Common PDB Patterns

```yaml
# At least 1 pod must always be available
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: myapp-pdb
spec:
  minAvailable: 1
  selector:
    matchLabels:
      app: myapp

# At most 1 pod can be unavailable at a time
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: myapp-pdb
spec:
  maxUnavailable: 1
  selector:
    matchLabels:
      app: myapp
```

**Warning:** A PDB with `minAvailable` equal to the replica count will block all drains
and node upgrades. Always allow at least one disruption.
