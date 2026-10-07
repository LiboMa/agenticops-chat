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
export AIOPS_WEBHOOK_SECRET=...        # matches deploy-app.sh --webhook-secret (alert posts send it as X-AIOps-Token)
bash run-e2e.sh                        # all scenarios
bash run-e2e.sh --assert-only          # deterministic pass/fail only
bash run-e2e.sh --evidence-only        # chat + report capture only
LOCATION_BATCH=off bash run-e2e.sh --location-only   # root-cause location eval, one batch (see below)
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

## Root-cause location eval (MVP-2.6.1)
Scores where the RCA says the root cause is, not whether the loop closes. 13 cases
(`ground_truth.yaml`: the 8 scenarios above + the 5 L2 faults of `../faults-l2/`),
each naming the objects that count as the root cause. Two batches, one per
invocation — `off` is the baseline without topology context in the RCA prompt, `on` is
with it:

```bash
LOCATION_BATCH=off bash run-e2e.sh --location-only
LOCATION_BATCH=on  bash run-e2e.sh --location-only
python location_eval.py results/location-<off>.json results/location-<on>.json
```

- **The eval environment.** `run-e2e.sh` sets it on the app with `kubectl set env` and
  waits for the rollout: `AIOPS_RCA_TOPOLOGY_CONTEXT_ENABLED` from the batch, auto-fix and
  the RAG pipeline off (nothing touches the cluster or the KB), resolved-cooldown 0 and
  the flapping threshold out of reach (every alert may open a new issue). The exit
  cleanup unsets the variables, which restarts the app once more.
- **Each restart empties the app's database** (an emptyDir), so the module preflight
  onboards the cluster again: resource scan → K8s connector run → graph build. The
  results JSON is the only record that survives.
- **Per case:** inject → settle (`settle_s`, 60 s for L2) → alert → the alert must open a
  NEW issue, else the attempt is invalid (retried once) → wait for the RCA (≤ 960 s) →
  score the stored location → refresh the graph with a manual connector run and measure
  graph recall → resolve the issue (resolved, not dismissed: a dismissal would teach the
  detect agent the fault was a false positive) → restore. An invalid run is recorded,
  excluded from the rates, and fails its test.
- **Metrics** (`location_eval.py`, pure): AC@1, AC@3 and MRR over the rank of the best
  root-cause candidate, and graph recall — a root cause within 2 hops of the issue
  anchor, rule relations only, both directions. Results land in
  `results/location-<utc>.json` (gitignored) after every case; the tables go into
  `docs/MVP-2.6.1-LOCATION-EVAL-REPORT.md`.
- **Budget:** about 1¾ h per batch (13 RCAs), about 3½ h for both. Cleanup also restores
  the L2 faults, CoreDNS and the deleted Service.

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
