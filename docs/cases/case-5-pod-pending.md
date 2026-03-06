# Case 5: Pod Pending (Resource Exhaustion)

## Fault Description

| Field | Value |
|-------|-------|
| **Type** | workload |
| **Severity** | warning |
| **Target** | frontend |
| **Namespace** | online-boutique |

Six stress pods are deployed, each requesting 900m CPU, consuming the majority of the cluster's allocatable CPU capacity. The frontend deployment is then scaled to 5 replicas, but the scheduler cannot place the new pods due to insufficient CPU resources. The additional frontend pods remain in Pending state indefinitely.

## Injection

**Script**: `infra/eks-lab/scenarios/case-5-pod-pending/inject.sh`

**Key command(s)**:
```bash
# Deploy CPU stress pods to exhaust cluster capacity
cat <<'EOF' | kubectl apply -f -
apiVersion: apps/v1
kind: Deployment
metadata:
  name: agenticops-stress
  namespace: online-boutique
  labels:
    chaos-injected: "true"
spec:
  replicas: 6
  selector:
    matchLabels:
      app: agenticops-stress
  template:
    metadata:
      labels:
        app: agenticops-stress
        chaos-injected: "true"
    spec:
      containers:
      - name: stress
        image: busybox
        command: ["sh", "-c", "while true; do :; done"]
        resources:
          requests:
            cpu: 900m
EOF

# Scale frontend to trigger pending pods
kubectl scale deploy/frontend -n online-boutique --replicas=5
```

## Expected Alert Flow

| Alert | Severity | For Duration | Expected Time |
|-------|----------|-------------|---------------|
| KubePodPending | warning | 3m | ~4 min after injection |
| KubeDeploymentReplicasMismatch | warning | 5m | ~6 min after injection |

## Expected Pipeline Flow

1. **Alert → HealthIssue**: KubePodPending fires when frontend pods remain unschedulable for 3 minutes, creating a HealthIssue referencing the pending pods.
2. **RCA**: Agent inspects the pending pods via `kubectl describe pod` and finds the scheduler event: `Insufficient cpu`. Examines cluster-wide resource allocation and identifies the `agenticops-stress` deployment (labeled `chaos-injected=true`) consuming 5400m CPU across 6 pods. Recognizes the stress pods as the root cause of resource exhaustion, not a legitimate workload.
3. **SRE Fix Plan**: Agent proposes deleting the `agenticops-stress` deployment to free CPU resources, allowing the frontend pods to be scheduled (Risk Level: L1).
4. **Approval**: Auto-approved (L1 — deleting an identifiable chaos deployment).
5. **Execution**: Executor deletes the stress deployment, then monitors the frontend pods to confirm they transition from Pending to Running.

## Expected Fix

**Command(s)**:
```bash
kubectl delete deploy agenticops-stress -n online-boutique
```

**Risk Level**: L1

## Challenges

- **Root cause identification**: The agent must look beyond the pending frontend pods and examine cluster-wide resource usage to find the stress pods. Simply scaling down frontend would be incorrect.
- **Label-based identification**: The `chaos-injected=true` label on the stress pods is the key signal that these are injected workloads, not legitimate production services. The agent should reference this label in the RCA.
- **Post-fix cleanup**: After deleting stress pods and frontend pods are running, the frontend replica count (5) may be higher than the original. The cleanup script should restore the original scale.

## Metrics

| Metric | Target | Actual |
|--------|--------|--------|
| Detection latency | ≤ 3 min | ~2 min |
| MTTR (end-to-end) | ≤ 10 min | 7m 30s |
| Token cost | ≤ $3 | ~$2-3 |

## Status

- [x] Injection script tested
- [x] Alert fires correctly
- [x] Pipeline completes end-to-end
- [x] Fix verified
- [x] Metrics recorded
