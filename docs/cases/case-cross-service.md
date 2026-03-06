# Case Cross-Service: Redis Latency Cascade

## Fault Description

| Field | Value |
|-------|-------|
| **Type** | application |
| **Severity** | critical |
| **Target** | redis-cart → frontend cascade |
| **Namespace** | online-boutique |

The redis-cart deployment is starved of resources by setting extremely low CPU and memory limits (10m CPU, 16Mi memory). Redis becomes severely throttled, responding to cart operations with multi-second latencies or timeouts. The latency cascades upstream through the call chain: redis-cart (throttled) → cartservice (slow responses) → checkoutservice (timeouts) → frontend (5xx errors to end users). This case validates the agent's ability to trace a cascading failure back to its downstream root cause.

**Call chain**: `frontend → checkoutservice → cartservice → redis-cart (throttled)`

## Injection

**Script**: `infra/eks-lab/scenarios/case-cross-service/inject.sh`

**Key command(s)**:
```bash
kubectl set resources deploy/redis-cart -n online-boutique \
  --limits=cpu=10m,memory=16Mi \
  --requests=cpu=10m,memory=16Mi
```

## Expected Alert Flow

| Alert | Severity | For Duration | Expected Time |
|-------|----------|-------------|---------------|
| HighLatencyP99 | warning | 5m | ~6 min after injection |
| HighErrorRate | critical | 5m | ~6 min after injection |

## Expected Pipeline Flow

1. **Alert → HealthIssue**: HighErrorRate and/or HighLatencyP99 fire on the frontend service, as it is the user-facing entry point showing degraded performance. HealthIssues are created referencing frontend metrics.
2. **RCA**: This is the key validation step. The agent must not stop at the symptom (frontend 5xx). It should trace the dependency chain: frontend logs show timeouts calling checkoutservice → checkoutservice shows timeouts calling cartservice → cartservice shows slow responses from redis-cart. Agent inspects `kubectl top pod` and `kubectl describe pod` for redis-cart and identifies the severely constrained resource limits (10m CPU, 16Mi memory) as the bottleneck. The RCA `root_cause` field should mention "redis" and the confidence should be > 0.7.
3. **SRE Fix Plan**: Agent proposes restoring redis-cart resource limits to reasonable values (e.g., 200m CPU, 256Mi memory) to eliminate the throttling bottleneck (Risk Level: L1).
4. **Approval**: Auto-approved (L1 — resource adjustment on a single workload to restore normal operation).
5. **Execution**: Executor runs `kubectl set resources` on redis-cart, then monitors the cascade recovery: redis-cart latency drops → cartservice responds normally → frontend error rate returns to baseline.

## Expected Fix

**Command(s)**:
```bash
kubectl set resources deploy/redis-cart -n online-boutique \
  --limits=cpu=200m,memory=256Mi \
  --requests=cpu=100m,memory=128Mi
```

**Risk Level**: L1

## Key Validation Criteria

This case is the most important test of the RCA agent's reasoning capability:

| Criterion | Requirement |
|-----------|-------------|
| RCA `root_cause` field | Must mention "redis" or "redis-cart" |
| RCA confidence | Must be > 0.7 |
| Dependency chain traced | Must identify at least 2 hops (frontend → ... → redis-cart) |
| Fix targets correct service | Must fix redis-cart, not frontend or cartservice |

## Challenges

- **Multi-hop root cause**: The alerts fire on frontend, but the root cause is 3 hops downstream at redis-cart. The agent must follow the dependency chain rather than applying a superficial fix to frontend.
- **Symptom vs. cause distinction**: The agent might be tempted to scale frontend replicas or increase frontend resources. The correct action is to fix the downstream bottleneck.
- **Resource observation**: The agent needs to check `kubectl top pod` or `kubectl describe pod` resource usage to identify that redis-cart is CPU-throttled and memory-constrained, not just that it is "slow."
- **Cascade recovery time**: After fixing redis-cart, the upstream services may take 30-60 seconds to recover as connection pools reset and retries succeed. The executor should allow time for cascade recovery.

## Metrics

| Metric | Target | Actual |
|--------|--------|--------|
| Detection latency | ≤ 3 min | TBD |
| MTTR (end-to-end) | ≤ 10 min | TBD |
| Token cost | ≤ $3 | TBD |

## Status

- [ ] Injection script tested
- [ ] Alert fires correctly
- [ ] Pipeline completes end-to-end
- [ ] Fix verified
- [ ] Metrics recorded
