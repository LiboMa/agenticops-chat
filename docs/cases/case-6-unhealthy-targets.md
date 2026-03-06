# Case 6: Unhealthy LB Targets

## Fault Description

| Field | Value |
|-------|-------|
| **Type** | workload |
| **Severity** | warning |
| **Target** | checkoutservice |
| **Namespace** | online-boutique |

The checkoutservice deployment's readiness probe is patched to target port 19999, a port on which no process is listening. The memory request is also bumped to 128Mi to satisfy the namespace LimitRange minimum (otherwise the patch triggers an admission rejection). The kubelet readiness checks fail, causing Kubernetes to remove the pods from the Service endpoints. The AWS ALB target group (if configured) also marks the targets as unhealthy. Upstream traffic to checkoutservice fails with connection errors.

## Injection

**Script**: `infra/eks-lab/scenarios/case-6-unhealthy-targets/inject.sh`

**Key command(s)**:
```bash
kubectl patch deploy/checkoutservice -n online-boutique --type=json \
  -p '[{"op":"replace","path":"/spec/template/spec/containers/0/readinessProbe/grpcHealthCheck/port","value":19999},{"op":"replace","path":"/spec/template/spec/containers/0/resources/requests/memory","value":"128Mi"}]'
```

## Expected Alert Flow

| Alert | Severity | For Duration | Expected Time |
|-------|----------|-------------|---------------|
| KubePodNotReady | warning | 3m | ~4 min after injection |
| TargetDown | warning | 3m | ~4 min after injection |

## Expected Pipeline Flow

1. **Alert → HealthIssue**: KubePodNotReady and/or TargetDown fire when checkoutservice pods fail readiness probes for 3 minutes, creating HealthIssues referencing the service.
2. **RCA**: Agent inspects `kubectl describe pod` and finds readiness probe failures with `connection refused` on port 19999. Examines the deployment spec to see the readiness probe is configured for port 19999, which does not match the container's actual listening port. Checks rollout history to identify the recent probe configuration change.
3. **SRE Fix Plan**: Agent proposes rolling back the deployment to the previous revision where the readiness probe targeted the correct port (Risk Level: L1).
4. **Approval**: Auto-approved (L1 — rollback to a known-good configuration on a single deployment).
5. **Execution**: Executor runs `kubectl rollout undo`, then monitors the rollout to confirm all pods pass readiness checks and the Service endpoints are restored.

## Expected Fix

**Command(s)**:
```bash
kubectl rollout undo deploy/checkoutservice -n online-boutique
```

**Risk Level**: L1

## Metrics

| Metric | Target | Actual |
|--------|--------|--------|
| Detection latency | ≤ 3 min | ~2 min |
| MTTR (end-to-end) | ≤ 10 min | 5m 24s |
| Token cost | ≤ $3 | ~$2-3 |

## Status

- [x] Injection script tested
- [x] Alert fires correctly
- [x] Pipeline completes end-to-end
- [x] Fix verified
- [x] Metrics recorded
