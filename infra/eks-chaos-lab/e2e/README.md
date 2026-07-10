# EKS Chaos E2E Harness

Proves the AgenticOps 感知→分析→解决→记录 loop against injected faults on the
`agenticops-chaos-lab` EKS cluster, with the app deployed **internal-only**
(ClusterIP — never public).

## Prerequisites
- `kubectl` context pointing at `agenticops-chaos-lab` (us-east-1)
- `aws` CLI creds for the lab account; `python` with `requests`, `pyyaml`, `pytest`
- App deployed in-cluster: `bash ../agenticops/deploy-app.sh`
- Cluster + workloads + alarms up: `bash ../setup.sh`

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
