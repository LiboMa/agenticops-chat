# Case 1: Pod OOM Kill

## Fault Description

| Field | Value |
|-------|-------|
| **Type** | workload |
| **Severity** | critical |
| **Target** | adservice |
| **Namespace** | online-boutique |

The adservice deployment (a Java application requiring ~300Mi of heap memory) has its container memory limit reduced to 64Mi and the JVM heap is explicitly forced to 256Mi via `JAVA_TOOL_OPTIONS="-Xmx256m -Xms256m"`. The JVM heap request exceeds the 64Mi cgroup limit, causing the kernel to OOM-kill the container on every startup attempt and resulting in a CrashLoopBackOff cycle with exponentially increasing restart delays. (Note: 32Mi was too low for the pod to even start; 64Mi allows the container to begin JVM initialization before the OOM kill.)

## Injection

**Script**: `infra/eks-lab/scenarios/case-1-oom/inject.sh`

**Key command(s)**:
```bash
kubectl set resources deploy/adservice -n online-boutique --limits=memory=64Mi
kubectl set env deploy/adservice -n online-boutique JAVA_TOOL_OPTIONS="-Xmx256m -Xms256m"
```

## Expected Alert Flow

| Alert | Severity | For Duration | Expected Time |
|-------|----------|-------------|---------------|
| KubePodOOMKilled | critical | 0m (immediate) | ~30s after injection |
| KubePodCrashLooping | critical | 1m | ~2 min after injection |

## Expected Pipeline Flow

1. **Alert → HealthIssue**: KubePodOOMKilled alert fires immediately on first OOM kill event, creating a HealthIssue with source `prometheus` and fingerprint based on (prometheus, adservice, OOMKilled).
2. **RCA**: Agent identifies that the container was terminated with exit code 137 (SIGKILL from OOM killer). Inspects `kubectl describe pod` to find `OOMKilled` reason and the current memory limit of 64Mi. Compares against container memory usage history to confirm the 64Mi limit is insufficient for a JVM configured with 256Mi heap.
3. **SRE Fix Plan**: Agent proposes increasing the memory limit to at least 256Mi and removing the forced heap override to accommodate the Java application's baseline memory requirement (Risk Level: L1).
4. **Approval**: Auto-approved (L1 — resource limit adjustment on a single workload, no cluster-wide impact).
5. **Execution**: Executor runs `kubectl set resources` to raise the memory limit, then monitors pod restart to confirm the OOM kills stop.

## Expected Fix

**Command(s)**:
```bash
kubectl set resources deploy/adservice -n online-boutique --limits=memory=256Mi
```

**Risk Level**: L1

## Metrics

| Metric | Target | Actual |
|--------|--------|--------|
| Detection latency | ≤ 3 min | ~2 min |
| MTTR (end-to-end) | ≤ 10 min | 5m 34s |
| Token cost | ≤ $3 | ~$2-3 |

## Status

- [x] Injection script tested
- [x] Alert fires correctly
- [x] Pipeline completes end-to-end
- [x] Fix verified
- [x] Metrics recorded
