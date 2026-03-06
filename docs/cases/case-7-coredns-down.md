# Case 7: CoreDNS Failure

## Fault Description

| Field | Value |
|-------|-------|
| **Type** | dns/infrastructure |
| **Severity** | critical |
| **Target** | CoreDNS (kube-system) |
| **Namespace** | kube-system |

The CoreDNS deployment in kube-system is scaled to zero replicas, eliminating all cluster DNS resolution capability. All services that rely on DNS-based service discovery (virtually every pod in the cluster) begin experiencing name resolution failures. New connections fail immediately while existing connections with cached DNS entries may continue briefly.

## Injection

**Script**: `infra/eks-lab/scenarios/case-7-coredns-down/inject.sh`

**Key command(s)**:
```bash
kubectl scale deploy/coredns -n kube-system --replicas=0
```

## Expected Alert Flow

| Alert | Severity | For Duration | Expected Time |
|-------|----------|-------------|---------------|
| KubeCoreDNSDown | critical | 1m | ~2 min after injection |

## Expected Pipeline Flow

1. **Alert → HealthIssue**: KubeCoreDNSDown fires after CoreDNS has zero available replicas for 1 minute, creating a critical HealthIssue for the cluster DNS infrastructure.
2. **RCA**: Agent inspects `kubectl get deploy coredns -n kube-system` and finds 0/0 replicas. Checks recent events and replica history to determine that the deployment was explicitly scaled to zero (not a crash or eviction). Identifies cluster-wide DNS resolution failure as the impact.
3. **SRE Fix Plan**: Agent proposes scaling CoreDNS back to 2 replicas (the standard EKS default) to restore cluster DNS (Risk Level: L1).
4. **Approval**: Auto-approved (L1 — restoring a critical system component to its expected replica count).
5. **Execution**: Executor runs `kubectl scale` to restore CoreDNS replicas, then verifies DNS resolution is working by checking that CoreDNS pods reach Running/Ready state.

## Expected Fix

**Command(s)**:
```bash
kubectl scale deploy/coredns -n kube-system --replicas=2
```

**Risk Level**: L1

## Challenges

- **EKS addon self-recovery**: On EKS, CoreDNS is managed as an addon. The EKS addon controller may detect the replica count deviation and automatically restore it. The validation must accept both outcomes: (a) AgenticOps fixes it before the addon controller, or (b) the addon controller self-recovers and AgenticOps detects the resolution.
- **Blast radius**: CoreDNS failure affects the entire cluster. The alert should fire quickly and the pipeline should prioritize this as a critical issue.
- **Verification**: After the fix, DNS resolution should be tested (e.g., verifying that pods can resolve `kubernetes.default.svc.cluster.local`) rather than just checking replica count.

## Metrics

| Metric | Target | Actual |
|--------|--------|--------|
| Detection latency | ≤ 3 min | ~2 min |
| MTTR (end-to-end) | ≤ 10 min | 4m 42s |
| Token cost | ≤ $3 | ~$2-3 |

**Note**: An AlertEvent dedup fix was needed for re-runs of this scenario. Without the fix, repeated injections of the same alert fingerprint were suppressed by the dedup window.

## Status

- [x] Injection script tested
- [x] Alert fires correctly
- [x] Pipeline completes end-to-end
- [x] Fix verified
- [x] Metrics recorded
