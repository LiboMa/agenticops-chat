# EKS Chaos E2E Harness

Proves the AgenticOps 感知→分析→解决→记录 loop against injected faults on the
`agenticops-chaos-lab` EKS cluster, with the app deployed **internal-only**
(ClusterIP — never public).

## Prerequisites
- `kubectl` context pointing at `agenticops-chaos-lab` (us-east-1)
- `aws` CLI creds for the lab account; `python` with `requests`, `pyyaml`, `pytest`
- App deployed in-cluster: `bash ../agenticops/deploy-app.sh`
- Cluster + workloads + alarms up: `bash ../setup.sh`

**Note:** The harness derives `AWS_ACCOUNT_ID` from the machine running it and registers it as the `chaos-lab` account. Ensure your AWS credentials match the lab account where the cluster's IRSA role resides.

## Run
```bash
export AIOPS_ADMIN_PASSWORD=...        # matches deploy-app.sh --admin-password
bash run-e2e.sh                        # all scenarios
bash run-e2e.sh --assert-only          # deterministic pass/fail only
bash run-e2e.sh --evidence-only        # chat + report capture only
```
`run-e2e.sh` opens a `kubectl port-forward` tunnel, runs pytest, writes
`results/junit.xml` + per-scenario evidence, and always runs `restore-all.sh`.

## Phases asserted (assert mode)
| Phase | Assertion |
|-------|-----------|
| 感知 perceive | a HealthIssue matching the scenario appears (`/api/health-issues`) |
| 分析 analyze  | an RCAResult is attached (`/api/health-issues/{id}/rca`) |
| 解决 resolve  | issue → `resolved`, a FixPlan executed, cluster end-state fixed (kubectl) |
| 记录 record   | pipeline timeline has fix/resolve events (`/api/health-issues/{id}/timeline`) |

## Scenarios
6 assert (scale-to-zero, bad-image, crashloop-config, node-drained,
resource-stress, netpol-block) + 2 evidence (coredns-down, service-deleted).
Add more by appending to `scenarios.yaml`.

## Safety
- App is ClusterIP-only; the sole ingress is the port-forward tunnel.
- Every scenario restores on teardown; `restore-all.sh` runs at the very end.

## Live-run notes (validated 2026-07-11 on a real EKS cluster)

Three fault classes drove the full autonomous loop end-to-end (each PASSED):

| Scenario | Fault class | Agent fix (auto, L1) |
|----------|-------------|----------------------|
| `bad-image` | image pull failure | roll back to the valid image |
| `crashloop-config` | bad nginx config / CrashLoop | restore the valid ConfigMap |
| `netpol-block` | network isolation | delete the deny-all NetworkPolicy |

**`scale-to-zero` is intentionally different.** The agent reads EKS audit logs,
sees a human (`kubectl scale ... --replicas=0`) caused it, classifies the fix as
**L2**, and inserts a **manual-approval gate** — it will not auto-revert a
deliberate-looking operator action. Under `executor_auto_approve_l0_l1` this
issue stops at `fix_planned` (correct behaviour, not a bug). Assert-mode targets
genuine *system* faults (image/config/network); human-action scenarios should
assert `fix_planned` + a gated plan, not `resolved`.

**Port collision gotcha:** if a local `uvicorn agenticops.web.app` (or anything)
already holds `:8000`, `kubectl port-forward` silently fails to bind and requests
hit the *other* app (symptom: `401` on login against a stale local DB).
`run-e2e.sh` now auto-selects a free local port and verifies a real login
through the tunnel before running. Override with `LOCAL_PORT=<n>`.
