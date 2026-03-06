# Case 8: PVC Pending (Wrong StorageClass)

## Fault Description

| Field | Value |
|-------|-------|
| **Type** | storage |
| **Severity** | warning |
| **Target** | PVC agenticops-bad-pvc |
| **Namespace** | online-boutique |

A PersistentVolumeClaim is created referencing a non-existent StorageClass (`nonexistent-sc`). The PVC remains in Pending state indefinitely because no provisioner can fulfill it. A consumer pod that mounts this PVC also stays in Pending, as the kubelet cannot attach a volume that was never provisioned.

## Injection

**Script**: `infra/eks-lab/scenarios/case-8-pvc-pending/inject.sh`

**Key command(s)**:
```bash
cat <<'EOF' | kubectl apply -f -
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: agenticops-bad-pvc
  namespace: online-boutique
  labels:
    chaos-injected: "true"
spec:
  accessModes:
  - ReadWriteOnce
  resources:
    requests:
      storage: 1Gi
  storageClassName: nonexistent-sc
---
apiVersion: v1
kind: Pod
metadata:
  name: agenticops-pvc-consumer
  namespace: online-boutique
  labels:
    chaos-injected: "true"
spec:
  containers:
  - name: app
    image: busybox
    command: ["sh", "-c", "sleep 3600"]
    volumeMounts:
    - name: data
      mountPath: /data
  volumes:
  - name: data
    persistentVolumeClaim:
      claimName: agenticops-bad-pvc
EOF
```

## Expected Alert Flow

| Alert | Severity | For Duration | Expected Time |
|-------|----------|-------------|---------------|
| KubePVCPending | warning | 5m | ~6 min after injection |

## Expected Pipeline Flow

1. **Alert → HealthIssue**: KubePVCPending fires after the PVC remains in Pending state for 5 minutes, creating a HealthIssue referencing the PVC name and namespace.
2. **RCA**: Agent inspects `kubectl describe pvc agenticops-bad-pvc -n online-boutique` and finds the event indicating that StorageClass `nonexistent-sc` does not exist. Runs `kubectl get storageclass` to list available StorageClasses and confirms the mismatch.
3. **SRE Fix Plan**: Agent proposes deleting the PVC and its consumer pod to remove the faulty resources. If the workload is needed, it should be recreated with a valid StorageClass (Risk Level: L1).
4. **Approval**: Auto-approved (L1 — deleting identifiable chaos-injected resources).
5. **Execution**: Executor deletes both the PVC and the consumer pod. Verifies that no Pending PVCs remain in the namespace.

## Expected Fix

**Command(s)**:
```bash
kubectl delete pvc agenticops-bad-pvc -n online-boutique
kubectl delete pod agenticops-pvc-consumer -n online-boutique
```

**Risk Level**: L1

## Challenges

- **PVC immutability**: The `storageClassName` field on a PVC is immutable after creation. The agent cannot simply patch the StorageClass to a valid one. The correct approach is to delete and recreate with the right StorageClass, or in this chaos case, simply delete the offending resources.
- **Executor must handle two resources**: The fix requires deleting both the PVC and the consumer pod. The executor should handle both commands, not just one.
- **StorageClass discovery**: The agent should list available StorageClasses to provide context in the RCA about what valid options exist (e.g., `gp2`, `gp3`).

## Metrics

| Metric | Target | Actual |
|--------|--------|--------|
| Detection latency | ≤ 3 min | ~2 min |
| MTTR (end-to-end) | ≤ 10 min | 6m 38s |
| Token cost | ≤ $3 | ~$2-3 |

## Status

- [x] Injection script tested
- [x] Alert fires correctly
- [x] Pipeline completes end-to-end
- [x] Fix verified
- [x] Metrics recorded
