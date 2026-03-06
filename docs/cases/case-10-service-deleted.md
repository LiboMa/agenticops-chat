# Case 10: CartService CrashLoop (5xx Surge)

## Fault Description

| Field | Value |
|-------|-------|
| **Type** | application |
| **Severity** | critical |
| **Target** | cartservice |
| **Namespace** | online-boutique |

The cartservice deployment is patched with an invalid command override (`/bin/sh -c exit 1`), causing the container to crash-loop on every startup attempt. All upstream services that depend on cartservice (checkoutservice, frontend) begin returning 5xx errors when attempting to reach the cart backend. The deployment enters CrashLoopBackOff with exponentially increasing restart delays.

**Design note**: The original design deleted the cartservice deployment entirely, but deleting a deployment removes its metrics targets, meaning no Prometheus alert fires (TargetDown requires a target to exist in a down state). Scaling to 0 replicas was also considered, but results in 0/0 desired=ready (no mismatch). The redesigned approach crash-loops cartservice with an invalid command patch, which reliably triggers KubePodCrashLooping and KubeDeploymentReplicasMismatch alerts while keeping the deployment and its metrics targets intact.

## Injection

**Script**: `infra/eks-lab/scenarios/case-10-service-deleted/inject.sh`

**Key command(s)**:
```bash
kubectl patch deploy/cartservice -n online-boutique --type=json \
  -p '[{"op":"replace","path":"/spec/template/spec/containers/0/command","value":["/bin/sh","-c","exit 1"]}]'
```

## Expected Alert Flow

| Alert | Severity | For Duration | Expected Time |
|-------|----------|-------------|---------------|
| KubePodCrashLooping | critical | 1m | ~2 min after injection |
| KubeDeploymentReplicasMismatch | warning | 5m | ~6 min after injection |

## Expected Pipeline Flow

1. **Alert → HealthIssue**: KubePodCrashLooping fires first when cartservice pods restart repeatedly. KubeDeploymentReplicasMismatch follows as the deployment has zero ready replicas. Both create HealthIssues tied to cartservice.
2. **RCA**: Agent inspects `kubectl describe pod` and finds the container exiting immediately with code 1 due to the invalid command override. Examines the deployment spec to identify the patched command as the root cause. Checks rollout history to confirm a recent change.
3. **SRE Fix Plan**: Agent proposes rolling back the deployment to the previous revision to restore the valid startup command (Risk Level: L1).
4. **Approval**: Auto-approved (L1 — rollback to a known-good state on a single deployment).
5. **Execution**: Executor runs `kubectl rollout undo`, then monitors the rollout to confirm cartservice pods reach Running/Ready state and upstream services stop returning 5xx errors.

## Expected Fix

**Command(s)**:
```bash
kubectl rollout undo deploy/cartservice -n online-boutique
```

**Risk Level**: L1

## Challenges

- **Cascade verification**: After restoring cartservice, the agent should verify that upstream services (checkoutservice, frontend) stop returning 5xx errors, not just that cartservice pods are running.
- **Rollout history**: The deployment must have a previous revision available for `kubectl rollout undo` to work. The clean-state setup ensures at least one good revision exists before injection.

## Metrics

| Metric | Target | Actual |
|--------|--------|--------|
| Detection latency | ≤ 3 min | ~2 min |
| MTTR (end-to-end) | ≤ 10 min | 6m 24s |
| Token cost | ≤ $3 | ~$2-3 |

## Status

- [x] Injection script tested
- [x] Alert fires correctly
- [x] Pipeline completes end-to-end
- [x] Fix verified
- [x] Metrics recorded
