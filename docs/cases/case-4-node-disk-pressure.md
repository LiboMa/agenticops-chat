# Case 4: Node DiskPressure

## Fault Description

| Field | Value |
|-------|-------|
| **Type** | infrastructure |
| **Severity** | warning → critical |
| **Target** | workload node |
| **Namespace** | online-boutique |

A busybox pod writes a 70GB file via `fallocate` into a hostPath volume mounted at `/var/chaos-disk-fill`, consuming the majority of the node's 80GB EBS root volume. The kubelet detects disk pressure and taints the node with `node.kubernetes.io/disk-pressure:NoSchedule`, begins evicting pods, and eventually marks the node as NotReady if pressure persists. (Note: hostPath is used instead of emptyDir to ensure the disk consumption is attributed to the node's root filesystem. The pod specifies 128Mi memory request to satisfy the namespace LimitRange minimum.)

## Injection

**Script**: `infra/eks-lab/scenarios/case-4-node-disk-pressure/inject.sh`

**Key command(s)**:
```bash
cat <<'EOF' | kubectl apply -f -
apiVersion: v1
kind: Pod
metadata:
  name: agenticops-disk-filler
  namespace: online-boutique
  labels:
    chaos-injected: "true"
spec:
  containers:
  - name: filler
    image: busybox
    command: ["sh", "-c", "fallocate -l 70G /data/fill && sleep 3600"]
    resources:
      requests:
        memory: 128Mi
      limits:
        memory: 128Mi
    volumeMounts:
    - name: data
      mountPath: /data
  volumes:
  - name: data
    hostPath:
      path: /var/chaos-disk-fill
      type: DirectoryOrCreate
EOF
```

## Expected Alert Flow

| Alert | Severity | For Duration | Expected Time |
|-------|----------|-------------|---------------|
| NodeDiskPressure | warning | 1m | ~2-3 min after injection |
| NodeNotReady | critical | 2m | ~4-5 min after injection |

## Expected Pipeline Flow

1. **Alert → HealthIssue**: NodeDiskPressure fires first as kubelet detects the exhausted disk. If pressure persists, NodeNotReady follows. Both create HealthIssues linked to the affected node.
2. **RCA**: Agent inspects the node conditions via `kubectl describe node` and identifies the DiskPressure condition. Examines pods on the node to find `agenticops-disk-filler` with its large emptyDir usage. Correlates the `chaos-injected=true` label with the disk consumption.
3. **SRE Fix Plan**: Agent proposes deleting the disk-filler pod to release the consumed disk space, then waiting for the node to recover from DiskPressure (Risk Level: L1).
4. **Approval**: Auto-approved (L1 — deleting a single identifiable chaos pod).
5. **Execution**: Executor deletes the disk-filler pod. Monitors the node condition to confirm DiskPressure clears and the node returns to Ready status. Note: node recovery may take up to 5 minutes as kubelet garbage collection reclaims emptyDir storage.

## Expected Fix

**Command(s)**:
```bash
kubectl delete pod agenticops-disk-filler -n online-boutique
```

**Risk Level**: L1

## Challenges

- **Slow recovery**: Node recovery after disk pressure relief can take up to 5 minutes as kubelet performs garbage collection and re-evaluates conditions. The executor should wait and verify rather than declare failure prematurely.
- **Volume size**: The 80GB EBS root volume means the 70GB fill leaves very little headroom. The kubelet eviction threshold (typically 15% or 100Mi) will be breached quickly.
- **hostPath cleanup**: After deleting the pod, the hostPath directory `/var/chaos-disk-fill` and its 70GB file remain on the node. The cleanup script should remove this directory via SSM or a DaemonSet.
- **LimitRange constraint**: The namespace has a LimitRange requiring minimum 128Mi memory. The disk-filler pod must specify at least 128Mi memory request/limit or it will be rejected by the admission controller.
- **Evicted pods**: Other pods may be evicted from the node before the fix is applied. The agent should verify that workload pods are rescheduled after the node recovers.

## Metrics

| Metric | Target | Actual |
|--------|--------|--------|
| Detection latency | ≤ 3 min | ~2 min |
| MTTR (end-to-end) | ≤ 10 min | 8m 41s |
| Token cost | ≤ $3 | ~$2-3 |

## Status

- [x] Injection script tested
- [x] Alert fires correctly
- [x] Pipeline completes end-to-end
- [x] Fix verified
- [x] Metrics recorded
