# MVP-2.6.1 Root-Cause Location Eval — Live Report

> **Status: measured — joint live E2E, route A (chaos-lab).** Three scored batches: one `off`, two `on` (before / after the recollect fix found by this eval).
> **Date:** 2026-10-02 / 2026-10-03 · **Branch:** `MVP-2.6.1` · **Deployed commit:** `f4127b3` (off, on #1) → `fe7e9fd` (on #2) · **Scope:** design §3.C.6 eval + §8 acceptance 3–5
> (`docs/superpowers/specs/2026-09-28-mvp-2.6.1-graph-rca-loop-and-issue-change-design.md`)
>
> Method, eval environment and budget: `infra/eks-chaos-lab/e2e/README.md` → «Root-cause location eval».
> Ground truth: `infra/eks-chaos-lab/e2e/ground_truth.yaml` (13 cases). Scoring: `infra/eks-chaos-lab/e2e/location_eval.py`.

---

## Environment

| Item | Value |
|------|-------|
| Cluster | `agenticops-chaos-lab` (us-east-1), EKS 1.32, nodes: 3 (2 × `chaos-lab-ng`, 1 × tainted `agenticops-ng`) |
| App | in-cluster, ClusterIP-only, SQLite on emptyDir (re-onboarded by each batch's preflight). Image `agenticops:f4127b3` for off / on #1, `agenticops:fe7e9fd` for on #2 — both built on the dev box over SSM, not locally |
| Models | rca `global.anthropic.claude-opus-4-6-v1`, critic `global.anthropic.claude-haiku-4-5-20251001-v1:0` |
| Eval env | `AIOPS_RCA_TOPOLOGY_CONTEXT_ENABLED` = batch · `AIOPS_DEDUP_RESOLVED_COOLDOWN_MINUTES=0` · `AIOPS_NOISE_FLAP_THRESHOLD=1000` · `AIOPS_AUTO_FIX_ENABLED=false` · `AIOPS_RAG_PIPELINE_ENABLED=false` |
| Result files | off `results/location-20261002T163305Z.json`, on #1 `results/location-20261002T172605Z.json`, on #2 `results/location-20261003T023907Z.json` (gitignored; tables below are `python location_eval.py <off> <on>`) |
| Cost / time | off: 46 min 42 s, $19.20 (4,782,067 tokens) · on #1: 40 min 10 s, $16.38 (3,291,466 tokens) · on #2: 40 min 58 s, $14.52 (3,346,498 tokens). Each is the batch's own `GET /api/cost/summary` (`results/cost-location-<batch>-<ts>.json`); 13 RCA calls per batch, RCA is the only cost line |

**Baseline comparability.** `off` ran image `f4127b3` and on #2 ran `fe7e9fd`. The only code difference is the recollect
fix in `graph/evidence.py`, which is reached only through `get_topology_evidence` — a tool the RCA agent does not have
while `rca_topology_context_enabled` is off (`agents/rca_agent.py`). So the one `off` batch is the baseline for both `on` batches.

## Results

| batch | runs | valid | invalid | AC@1 | AC@3 | MRR | located | graph recall |
|---|---|---|---|---|---|---|---|---|
| off | 13 | 13 | 0 | 0.00 | 0.00 | 0.00 | 0.15 | 1.00 |
| on #1 (`f4127b3`) | 13 | 13 | 0 | 0.38 | 0.38 | 0.38 | 1.00 | 1.00 |
| on #2 (`fe7e9fd`) | 13 | 13 | 0 | **0.77** | **0.77** | **0.77** | **1.00** | **1.00** |

Per case: `rank · location_status`; `off` located nothing it could rank (11 × `absent`, 2 × a `valid` reference
at the wrong level — the cluster and an EC2 instance id). Graph recall is `yes` for every case in every batch.

| case | off | on #1 | on #2 | on #2 first candidate |
|---|---|---|---|---|
| scale-to-zero | — · absent | — · valid | **1** · valid | Deployment chaos-lab/backend |
| bad-image | — · absent | 1 · partial | **1** · partial | Deployment chaos-lab/frontend |
| crashloop-config | — · valid | 1 · valid | **1** · valid | ConfigMap chaos-lab/nginx-config |
| node-drained | — · valid | — · valid | — · valid | EKS cluster `agenticops-chaos-lab` |
| resource-stress | — · absent | — · valid | **1** · valid | Pod chaos-lab/stress-test |
| netpol-block | — · absent | 1 · valid | **1** · valid | NetworkPolicy chaos-lab/chaos-block-backend |
| coredns-down | — · absent | — · valid | **1** · valid | Deployment kube-system/coredns |
| service-deleted | — · absent | — · valid | — · valid | Deployment chaos-lab/backend |
| l2-payment-svc | — · absent | 1 · valid | **1** · valid | Deployment chaos-lab/payment-svc |
| l2-checkout-api | — · absent | — · valid | **1** · valid | Deployment chaos-lab/checkout-api |
| l2-session-store | — · absent | — · valid | **1** · valid | Deployment chaos-lab/session-store |
| l2-inventory-db | — · absent | 1 · partial | **1** · valid | Deployment chaos-lab/inventory-db |
| l2-notification-worker | — · absent | — · valid | — · valid | EKS cluster `agenticops-chaos-lab` |

## Acceptance (design §8)

| # | Criterion | Result |
|---|-----------|--------|
| 3 | Graph recall ≥ 12/13 (deterministic, hard gate) | **13/13 — pass** (all three batches) |
| 4 | `on` batch: `location_status ∈ {valid, partial}` ≥ 90%; no invalid reference stored as `valid` | **13/13 = 100% — pass** (both `on` batches). Spot-check: every stored candidate in on #2 resolves to an inventory row of the deployed cluster (table above); no `invalid` status was stored |
| 5 | AC@1 / AC@3 / MRR off vs on, reported as measured (no threshold — 13 samples) | off 0.00 / 0.00 / 0.00 → on #1 0.38 / 0.38 / 0.38 → on #2 **0.77 / 0.77 / 0.77**. Every hit is at rank 1, so AC@1 = AC@3 = MRR |

## Invalid runs

None in the three scored batches (39/39 runs valid). `crashloop-config` (off) and `node-drained` (on #2) needed their
second attempt (the first alert did not open a new issue; the harness allows two).

One earlier `off` batch (`results/location-20261002T152249Z.json`) is **void, not scored**: 6/13 valid. `coredns-down`
got the app SIGKILLed — its liveness probe was `/api/health`, which makes a live STS call, so a broken cluster DNS
failed the probe — and the unsupervised port-forward died with it, so the 6 cases after it could not post their alert
(`ConnectionError` on both attempts). `service-deleted`'s restore could also never re-apply its backup. Fixed before
the scored batches, as new commits: `4967eb5` (service-deleted restores from the workloads manifest), `ffc9de1` (lab
app: `tcpSocket` liveness, `dnsPolicy: Default`, kubeconfig by service IP — the observer stays out of the fault
domain), `3907747` (supervised port-forward), `c3137c5` (cost summary saved per batch).

## Findings

**1. Recollect bias (fixed in this eval — `fe7e9fd`).** On #1 missed 8/13. Five misses (`coredns-down`,
`service-deleted`, `l2-session-store`, `l2-notification-worker`, and in part `l2-checkout-api`) ranked objects from
the **previous** case first: Pod `stress-test`, NetworkPolicy `chaos-block-backend`, Deployment `payment-svc`.
Cause: the cases run back to back, so the K8s connector's last collection was always younger than
`rca_k8s_recollect_min_age_seconds` (120 s), and the evidence pack skipped the recollect. It then read a snapshot taken
**before** this fault, which still showed the previous fault's objects as the freshest change. Fix: recollect unless the
last collection is both younger than the min age **and** later than the issue's onset (`observed_at`, else
`first_seen`). Red test `b401d36` (`test_recent_collection_from_before_the_fault_is_recollected`), fix `fe7e9fd`,
spec §3.C.2 修订 2026-10-03, controller Ruling E-T10f. Cost: at most one extra bounded connector run per RCA. On #2
re-ran the full batch on the fixed image: `coredns-down`, `l2-session-store`, `l2-checkout-api`, `resource-stress`
and `scale-to-zero` turned into rank-1 hits.

**2. Observer contamination (on #1 `scale-to-zero`).** The first candidate was Deployment `agenticops/agenticops` —
the app itself, which the batch preflight had just restarted with the eval environment, so it was the freshest change
in the graph. On #2 (recollect after onset) ranked `backend` / `frontend` first. The lab app is excluded from the
fault domain (`ffc9de1`) but not from the inventory — a real deployment would observe its own namespace the same way.

**3. Right answer in the text, wrong level in the location (`node-drained`, all `on` batches).** The on #2 RCA text
names the cordoned Node `ip-192-168-17-26.ec2.internal` and the full causal chain (one schedulable node at 17/17 pods,
the third node tainted). The structured location is the EKS cluster row instead. The Node is reachable in the graph
(recall yes), so this is a model choice, not missing data. The RCA also cited a K8s audit-log entry from an earlier
batch (2026-10-02T15:36Z) as the cordon event — the same node, but the actor/time it quotes is stale.

**4. Deleted object as root cause (`service-deleted`).** The accept key is Service `chaos-lab/backend`, which no longer
exists, so its row is `absent` at RCA time. The RCA wrote a generic "chaos framework" narrative (confidence 0.55)
and located the Deployments behind the Service. Graph recall is yes — the absent row is still in the graph — but the
RCA never named it; locating a just-deleted object is not solved by this release.

**5. Cluster-level location (`l2-notification-worker`, on #2).** Located the cluster row; the accept keys are
Deployment `notification-worker` and PodDisruptionBudget `notification-worker-pdb`. The RCA body was not captured (the
side dump of issue 18 is empty), so the reason is unknown. On #1 ranked previous-case objects here (finding 1).

**6. False positive called on a real fault (on #1 `resource-stress`).** On #1 judged the alarm a false positive (the
metric was in `INSUFFICIENT_DATA`) and located the cluster; on #2 ranked Pod `stress-test` first.

**7. `bad-image` is `partial` because its path was dropped.** In both `on` batches the RCA proposed the path edge
ref 39 → ref 50 (Deployment `frontend`) as `contains`, which is not a rule/observed relation of the checked build, so
the validator dropped the whole path fail-closed (spec §3.C.3) and kept the rank-1 candidate. The hit still counts.

**8. Every connector run is `partial` — by design in the lab.** The lab ClusterRole
(`infra/eks-chaos-lab/agenticops/rbac.yaml`) grants no `secrets` read, so the Secret kind never lists completely and
the run status is `partial` (`graph_refresh` in every result row); the other 12 kinds list completely. A `partial`
run still counts as a successful recollect for the evidence pack.
