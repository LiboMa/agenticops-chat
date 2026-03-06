# Case 2: Bad Image (ImagePullBackOff)

## Fault Description

| Field | Value |
|-------|-------|
| **Type** | workload |
| **Severity** | warning |
| **Target** | productcatalogservice |
| **Namespace** | online-boutique |

The productcatalogservice deployment is updated to reference a non-existent container image tag (`v999.0.0-nonexistent`). Kubernetes cannot pull the image, causing new pods to enter ImagePullBackOff status while the old ReplicaSet maintains existing pods (if any). The deployment's rollout stalls with a replica count mismatch.

## Injection

**Script**: `infra/eks-lab/scenarios/case-2-bad-image/inject.sh`

**Key command(s)**:
```bash
kubectl set image deploy/productcatalogservice server=REPO:v999.0.0-nonexistent -n online-boutique
```

## Expected Alert Flow

| Alert | Severity | For Duration | Expected Time |
|-------|----------|-------------|---------------|
| KubeDeploymentReplicasMismatch | warning | 5m | ~6 min after injection |

## Expected Pipeline Flow

1. **Alert → HealthIssue**: KubeDeploymentReplicasMismatch fires after 5 minutes of the deployment having fewer ready replicas than desired, creating a HealthIssue linked to productcatalogservice.
2. **RCA**: Agent runs `kubectl describe pod` on the failing pods and identifies `ImagePullBackOff` with the error message indicating the image tag `v999.0.0-nonexistent` does not exist in the registry. Inspects the deployment's rollout history to confirm a recent image change.
3. **SRE Fix Plan**: Agent proposes rolling back the deployment to the previous revision using `kubectl rollout undo` (Risk Level: L1).
4. **Approval**: Auto-approved (L1 — rollback to a known-good state on a single deployment).
5. **Execution**: Executor runs `kubectl rollout undo`, then monitors rollout status to confirm all replicas are ready with the previous working image.

## Expected Fix

**Command(s)**:
```bash
kubectl rollout undo deploy/productcatalogservice -n online-boutique
```

**Risk Level**: L1

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
