# MVP-2.6.1 Root-Cause Location Eval — Live Report

> **Status: template — filled in during the joint live E2E with the user.**
> **Date:** _run date_ · **Branch:** `MVP-2.6.1` · **Deployed commit:** _sha_ · **Scope:** design §3.C.6 eval + §8 acceptance 3–5
> (`docs/superpowers/specs/2026-09-28-mvp-2.6.1-graph-rca-loop-and-issue-change-design.md`)
>
> Method, eval environment and budget: `infra/eks-chaos-lab/e2e/README.md` → «Root-cause location eval».
> Ground truth: `infra/eks-chaos-lab/e2e/ground_truth.yaml` (13 cases). Scoring: `infra/eks-chaos-lab/e2e/location_eval.py`.

---

## Environment

| Item | Value |
|------|-------|
| Cluster | `agenticops-chaos-lab` (us-east-1), nodes: _n_ |
| App | in-cluster, ClusterIP-only, image _tag_, SQLite on emptyDir (re-onboarded by each batch's preflight) |
| Models | rca _model_, critic _model_ |
| Eval env | `AIOPS_RCA_TOPOLOGY_CONTEXT_ENABLED` = batch · `AIOPS_DEDUP_RESOLVED_COOLDOWN_MINUTES=0` · `AIOPS_NOISE_FLAP_THRESHOLD=1000` · `AIOPS_AUTO_FIX_ENABLED=false` · `AIOPS_RAG_PIPELINE_ENABLED=false` |
| Result files | `results/location-<off>.json`, `results/location-<on>.json` (gitignored; tables below are `python location_eval.py <off> <on>`) |
| Cost / time | _per batch: wall time, `GET /api/cost/summary` delta_ |

## Results

_Paste the batch table from `location_eval.py`._

| batch | runs | valid | invalid | AC@1 | AC@3 | MRR | located | graph recall |
|---|---|---|---|---|---|---|---|---|
| off | | | | | | | | |
| on | | | | | | | | |

_Paste the per-case table from `location_eval.py`._

| case | off | on |
|---|---|---|
| | | |

## Acceptance (design §8)

| # | Criterion | Result |
|---|-----------|--------|
| 3 | Graph recall ≥ 12/13 (deterministic, hard gate) | _x/13 — pass/fail_ |
| 4 | `on` batch: `location_status ∈ {valid, partial}` ≥ 90%; no invalid reference stored as `valid` | _located %, spot-check_ |
| 5 | AC@1 / AC@3 / MRR off vs on, reported as measured (no threshold — 13 samples) | _see Results_ |

## Invalid runs

_Each run whose alert did not open a new issue after both attempts: case, batch, the recorded `invalid_reason`. None → write "none"._

## Findings

_Per miss: case, what the RCA located instead, whether the root cause was in the graph (recall), and the likely reason
(no inventory row, no rule edge, wrong anchor, model choice)._
