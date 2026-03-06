# Case 3: Redis Cart CrashLoop

## Fault Description

| Field | Value |
|-------|-------|
| **Type** | workload |
| **Severity** | critical |
| **Target** | redis-cart |
| **Namespace** | online-boutique |

The redis-cart deployment is patched with an invalid command override (`redis-server --invalid-flag`), causing the container to crash-loop on every startup attempt. The cartservice loses its backing Redis store, resulting in cart operation failures and upstream 5xx errors from frontend and checkoutservice.

**Design note**: The original design used a deny-all NetworkPolicy on cartservice to block traffic, but NetworkPolicy does not block kubelet health probes (kubelet bypasses CNI network policies). This meant no alerts would fire, making the scenario unsuitable for closed-loop validation. The redesigned approach crash-loops redis-cart with an invalid command patch, which reliably triggers KubePodCrashLooping alerts.

## Injection

**Script**: `infra/eks-lab/scenarios/case-3-network-policy/inject.sh`

**Key command(s)**:
```bash
kubectl patch deploy/redis-cart -n online-boutique --type=json \
  -p '[{"op":"replace","path":"/spec/template/spec/containers/0/command","value":["redis-server","--invalid-flag"]}]'
```

## Expected Alert Flow

| Alert | Severity | For Duration | Expected Time |
|-------|----------|-------------|---------------|
| KubePodCrashLooping | critical | 1m | ~2 min after injection |

## Expected Pipeline Flow

1. **Alert → HealthIssue**: KubePodCrashLooping fires after redis-cart pods restart repeatedly for 1 minute, creating a HealthIssue with source `prometheus` and fingerprint based on (prometheus, redis-cart, CrashLooping).
2. **RCA**: Agent inspects `kubectl describe pod` and finds the container crashing with an invalid command flag error. Examines the deployment spec to identify the patched command override as the root cause. Checks rollout history to confirm a recent change.
3. **SRE Fix Plan**: Agent proposes rolling back the deployment to the previous revision to restore the valid Redis startup command (Risk Level: L1).
4. **Approval**: Auto-approved (L1 — rollback to a known-good state on a single deployment).
5. **Execution**: Executor runs `kubectl rollout undo`, then monitors the rollout to confirm redis-cart pods reach Running/Ready state and cartservice can reconnect.

## Expected Fix

**Command(s)**:
```bash
kubectl rollout undo deploy/redis-cart -n online-boutique
```

**Risk Level**: L1

## Metrics

| Metric | Target | Actual |
|--------|--------|--------|
| Detection latency | ≤ 3 min | ~2 min |
| MTTR (end-to-end) | ≤ 10 min | 7m 3s |
| Token cost | ≤ $3 | ~$2-3 |

## Status

- [x] Injection script tested
- [x] Alert fires correctly
- [x] Pipeline completes end-to-end
- [x] Fix verified
- [x] Metrics recorded
