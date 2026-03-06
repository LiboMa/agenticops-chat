# Case 9: HPA Not Scaling

## Fault Description

| Field | Value |
|-------|-------|
| **Type** | workload |
| **Severity** | warning |
| **Target** | frontend HPA |
| **Namespace** | online-boutique |

A HorizontalPodAutoscaler is created for the frontend deployment with `maxReplicas` set to 1, effectively disabling horizontal scaling. The loadgenerator is then scaled to 3 replicas, driving up CPU utilization on the single frontend pod. Despite sustained high CPU, the HPA cannot scale beyond 1 replica, causing degraded response times and potential request failures.

## Injection

**Script**: `infra/eks-lab/scenarios/case-9-hpa-maxed/inject.sh`

**Key command(s)**:
```bash
# Create HPA with maxReplicas=1
cat <<'EOF' | kubectl apply -f -
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: frontend-hpa
  namespace: online-boutique
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: frontend
  minReplicas: 1
  maxReplicas: 1
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 50
EOF

# Increase load to trigger scaling pressure
kubectl scale deploy/loadgenerator -n online-boutique --replicas=3
```

## Expected Alert Flow

| Alert | Severity | For Duration | Expected Time |
|-------|----------|-------------|---------------|
| KubeHPAMaxedOut | warning | 5m | ~6 min after injection |

## Expected Pipeline Flow

1. **Alert → HealthIssue**: KubeHPAMaxedOut fires after the HPA has been at its maximum replica count (1) with the desired count exceeding the maximum for 5 minutes, creating a HealthIssue for the frontend HPA.
2. **RCA**: Agent inspects `kubectl describe hpa frontend-hpa -n online-boutique` and finds that current CPU utilization far exceeds the 50% target, but the HPA cannot scale because `maxReplicas=1` equals `currentReplicas=1`. Identifies the misconfigured `maxReplicas` ceiling as the constraint preventing scaling.
3. **SRE Fix Plan**: Agent proposes patching the HPA to increase `maxReplicas` to a reasonable value (e.g., 5) to allow the autoscaler to respond to load (Risk Level: L0).
4. **Approval**: Auto-approved (L0 — read-modify on a non-destructive autoscaler configuration, no impact to running pods).
5. **Execution**: Executor patches the HPA `maxReplicas`, then monitors to confirm the HPA begins scaling up frontend replicas and CPU utilization decreases.

## Expected Fix

**Command(s)**:
```bash
kubectl patch hpa frontend-hpa -n online-boutique --type=merge -p '{"spec":{"maxReplicas":5}}'
```

**Risk Level**: L0

## Challenges

- **Correct root cause identification**: The agent must recognize that the issue is the HPA `maxReplicas` ceiling, not insufficient cluster resources or node capacity. Scaling the node group or adding more nodes would be the wrong fix.
- **Not a pod issue**: Unlike most other cases, the pods themselves are healthy and running. The issue is a configuration constraint on the autoscaler. The agent needs to reason about the relationship between load, CPU utilization targets, and scaling limits.
- **Load generator awareness**: The agent should note the increased loadgenerator replicas as the source of elevated traffic, but the fix is adjusting the HPA, not reducing load.

## Metrics

| Metric | Target | Actual |
|--------|--------|--------|
| Detection latency | ≤ 3 min | ~2 min |
| MTTR (end-to-end) | ≤ 10 min | 4m 7s |
| Token cost | ≤ $3 | ~$2-3 |

**Note**: An AlertEvent dedup fix was needed for re-runs of this scenario. Without the fix, repeated injections of the same alert fingerprint were suppressed by the dedup window.

## Status

- [x] Injection script tested
- [x] Alert fires correctly
- [x] Pipeline completes end-to-end
- [x] Fix verified
- [x] Metrics recorded
