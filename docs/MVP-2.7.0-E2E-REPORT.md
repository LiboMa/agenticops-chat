# MVP-2.7.0 — Joint Live E2E Evidence Report

> **Status: done. The 2.7.0 flows ran on real models in the chaos-lab EKS cluster. Two defects found by the run were fixed and re-verified live. Push, PR and tag wait for the owner.**
> **Date:** 2026-10-08 · **Branch:** `MVP-2.7.0` · **Deployed:**
> - pod 1 `7b4b2b6`: parts A, B (B1–B5), C, D (D1–D7);
> - pod 2 `52e1c3f`, the final code: B6–B8 and D8–D10 again after the translation fix.
>
> **Scope:** S7 plan `docs/superpowers/plans/2026-10-08-mvp-2.7.0-s7-release.md`, Tasks 2–8 (release note `docs/MVP-2.7.0-RELEASE.md`).
>
> **Route (owner decision, 10-08):**
> - in-cluster in `agenticops-chaos-lab`, reached only through `kubectl port-forward`;
> - the image is built on the dev box (its service untouched);
> - writes are limited to the chaos-lab cluster (see [Writes performed](#writes-performed));
> - A1–A4 are not in v2.7.0 — they moved to MVP-2.7.1 (owner, 10-08).

---

## Environment

| Item | Value |
|------|-------|
| Cluster | `agenticops-chaos-lab` (us-east-1), EKS 1.33, 3 nodes |
| App | in-cluster Deployment `agenticops/agenticops`, ClusterIP only, **one uvicorn process** (`--workers 1`, `replicas: 1`; checked in the pod's process list), SQLite on emptyDir, **API auth ON**, `rbac_enforce=false` (shadow) |
| Version | `GET /api/ui/bootstrap` and OpenAPI `info.version` = **2.7.0**; the sidebar shows `v2.7.0` |
| Reached from | the operator's laptop: `kubectl port-forward svc/agenticops 8901:8000` |
| Users | `admin` (built-in), `alice@example.com` and `bob@example.com` (registered, `read` + `write`). Passwords and the webhook secret were generated for this run and kept in a 0600 file outside the repo |
| Settings | `AIOPS_EXECUTOR_AUTO_APPROVE_L0_L1=false` (every plan waits for a human); `change_auto_approve_standard=false`; notifications off (publish is not part of the live run) |
| Models | committed defaults: main Opus 5, RCA Opus 4.6, SRE Fable 5.1, executor Opus 4.6, critic and translation Haiku 4.5 |
| Target account | `chaos-lab` (533267047935), `environment` source = the pod's IRSA role, resolved through the provider layer (test-connection: `success`) |
| Inventory | resource scan 828 found; K8s connector run `partial` (the lab RBAC grants no `secrets` read — by design) with 129 K8s objects; 953 resources in total |

## Test 0 — Gates

At `52e1c3f`, before the docs commit. The final numbers are in the RELEASE «S7 门禁结果».

| Gate | Result |
|------|------|
| `pytest tests/` (throwaway DB) | **6910 passed / 85 skipped / 2 failed**. The two are the known environment failures, unrelated to 2.7.0: `test_claude5_bedrock_models::test_defaults_upgraded` (the owner's local settings.yaml) and `test_prompt_budget::test_no_cjk_in_base_prompts`. The third known one, `test_web_tools::test_invalid_headers_json`, passed on this network |
| Frontend | `tsc` 0 errors; vitest 58 files / 708; a clean `npm ci && npm run build` in an empty directory (see fix 1) |

## Remote build

- **Why remote:** Docker is not available on the operator's laptop.
- **Path:**
  1. `git archive <sha>` → `s3://agenticops-deploy-533267047935/e2e/src-<sha>.tar.gz`;
  2. a presigned URL (`--region ap-southeast-1`);
  3. the dev box (`i-0935450a95f321942`, over SSM) builds `docker/Dockerfile` in `/tmp/aiops-build-<sha>` and pushes `agenticops:<sha>` to ECR us-east-1.
- **Builds:**
  - `7866994` **failed** at the frontend's `tsc -b` — fix 1;
  - `7b4b2b6` and `52e1c3f` built and were deployed.

## Checklist results

### A — a real fault through the work-item flow (pod 1)

| # | Check | Result |
|---|---|---|
| A1 | `chaos/pod-kill.sh scale-zero` + the scenario's signed CloudWatch alert → one issue | **Pass** — I#1 `EKS-agenticops-chaos-lab-RunningPods-Low`, account chaos-lab, anchored |
| A2 | RCA on the real model | **Pass, with the gate working as designed.** RCA in 160 s. Root-cause location `valid`: rank 1 `Deployment chaos-lab/backend`, rank 2 `frontend` — both were scaled. Its root cause: the IAM user's manual `kubectl scale` to 0. Confidence 0.57, critic `weak`, so the quality gate set `needs_review` and no plan was made automatically. «Generate fix plan» made one |
| A3–A4 | The plan waits on a person | **Pass.** «Needs your attention» lists I#1, reason `approval_required`, route `/app/plans/1`. The approve action's effect is `approve_and_queue_execution` |
| A5 | Approval binds the content hash | **Pass.** A wrong hash → 409 «I#1 fix plan v1 changed since it was loaded … reload it and review it again», no run. The reviewed hash → 200 |
| A6 | Plan #1's run | **Verdict correct: `failed`, rolled back.** See [Incident](#incident--a-plan-approved-without-reviewing-its-steps). The run aborted at step 4, so it had no post-check results; the rollback scaled both Deployments back to 0. The issue went back to `root_cause_identified`; the RCA's critic verdict became `disputed_by_execution` |
| A9–A10 | A new plan, reviewed by the approver | **Pass.** The SRE again proposed 9 steps including the add-on. The approver (the operator) cut the draft to the 3 in-scope steps (`PUT /api/fix-plans/2`, v1 → v2, new content hash). Approving with the hash from before the edit → 409 |
| A11–A12 | Approve & run, one verdict bound by `check_id` | **Pass.** `approved_by = user:admin`; run #2 `succeeded`; the post-check result names `pc-1` and passed; verdict **`passed`** → I#1 `resolved` (no acceptance step needed). Cluster: frontend 3/3, backend 2/2 |

`pending_acceptance` → «Accept» did not come up live, because both verdicts were final. It stays covered by the S1 / 2.6.1 tests.

### B — notes, a bound chat, idempotent send, a private report

| # | Check | Result |
|---|---|---|
| B1 | Notes | **Pass.** alice's note → 201, actor `user:alice@example.com`; admin's → `user:admin`; a body that names an author (`actor`) → 422. The timeline keeps both, in order, and `<b>not bold</b>` stays text |
| B2 | A chat bound to the issue | **Pass.** A client `account_id` that differs from I#1's → 409 `context_account_mismatch`. The new session is `private` with the issue's account (chaos-lab) |
| B3 | Streaming | **Pass.** `accepted` → `tool_start` / `tool_end` (`get_rca_result`, `get_health_issue`, each with `call_id` and `outcome: ok`) → `done.terminal_status = completed` in 10.7 s. The answer cites I#1, the alarm, the scale-to-zero and the RCA's 0.57. It also caught that alice's note («only backend was scaled») disagrees with the RCA — the notes reach the agent's context (S5) |
| B4 | One send, one run | **Pass.** A second message while the first ran → 409 `session_busy`. A resend with the same `client_message_id` → replayed in 0.7 s, `replayed: true`, 0 tokens, message count unchanged |
| B5 | The binding, by its effect | **Partial.** With a temporary second account (`other-lab`, deleted after), asked to run a command there, the agent refused on its own («this conversation is bound to account chaos-lab»). It called no tool, so the resolver-level refusal was not reached live (it is covered by the S5 tests) |
| B6 | A report from a private chat | **Pass.** `visibility: private`. bob → 404 and no list row; admin → 200 |
| B7 | Real translation | **Failed on pod 1 → fixed → pass on pod 2.** On `7b4b2b6` the zh rendering failed with `protected_values_changed` in 7 s, reproduced on the real model locally. Fix 2. On `52e1c3f` a new real chat report (a table of Deployments, replicas, HPA min / max, commands) → zh `ready` in 7 s, protected values equal |
| B8 | Export | **Pass on pod 2.** html in zh and en, one paper each, `AgenticOps_R1_v1_zh.html` / `…_en.html`. On pod 1 zh was a correct 409 (`rendering_not_ready`) |

### C — a change on a healthy target

| # | Check | Result |
|---|---|---|
| C#1 | — | Rejected by the operator's driver before any write. The driver's allow-list was wrong (it took only `deployment/x`), and admin was both requester and would-be approver. «Needs your attention» correctly did not list it for admin: the strict policy's `sod-change-approver-not-requester` |
| C1–C2 | alice requests «scale frontend 3 → 2» with her own step | **Pass.** SRE review (Fable 5.1) in 69 s → `planned`, verdict `approved_for_planning`, L1, `steps_diff` 1 unchanged. The policy said `auto_approve`, but `change_auto_approve_standard=false`, so it waited for a human. Admin's «Needs your attention» lists C#2 (`approval_required`) |
| C3 | Approve & run | **Pass.** One request approved and ran it. `approved_by = user:admin` (requester `user:alice@example.com`). The run succeeded; 3 post-checks bound `pc-1…pc-3`, all passed; verdict **`passed`** → C#2 `completed`. Cluster: frontend 2/2. The operator then restored 3/3 (`pod-kill.sh restore`) |

### D — the live UI (headless Chromium, 1440 × 900 and 1000 × 800)

| # | Check | Result |
|---|---|---|
| D1–D3 | Login → home; sidebar `v2.7.0`; top-bar account scope = chaos-lab | **Pass** (pod 1 and pod 2) |
| D4 | Cases split view: I#1 in the queue; the reading pane shows its phases and the notes as plain text; at 1000 px, list → full-screen case → back to the list | **Pass** (pod 1) |
| D5 | «Needs your attention» in the top bar | **Pass** — 0 after A and C (nothing waits) |
| D6–D7 | The plan page (I#1 fix plan v1: Failed, its run); the change page (C#2: request by alice … Completed) | **Pass** (pod 1) |
| D8 | alice's report: one paper; 中文 switches it; Export downloads the language shown (`AgenticOps_R1_v1_zh.html`) | **Pass** (pod 2). On pod 1 Export was correctly disabled for the failed zh |
| D9 | bob's report list is empty | **Pass** (pod 2) |
| D10 | No page errors; no request leaves `localhost:8901` | **Pass** on pod 2's pages. Pod 1's walk stopped at D8 before this check |

## Incident — a plan approved without reviewing its steps

- **What the operator did:** the E2E driver approved fix plan #1 as soon as it existed, without reading its steps. That is the operator's mistake: in this E2E the operator is the human approver.
- **What the SRE planned:** «Restore frontend/backend replicas **and enable HPA recovery** (metrics-server + minReplicas guard)», L2, 8 steps. Steps 1–3 restore the replicas. Then:
  - step 4: `aws eks create-addon --addon-name metrics-server` (cluster-wide, an AWS write);
  - step 7: a new HPA;
  - step 8: annotations.
- **What happened:**
  - steps 1–3 ran;
  - step 4 was **refused by AWS**: the IRSA role has no `eks:CreateAddon`;
  - steps 5–8 were skipped;
  - the rollback scaled both Deployments back to 0.
- **What was written:** nothing outside the allowed writes. After the run the add-on list is unchanged (`amazon-cloudwatch-observability`, `aws-ebs-csi-driver`, `coredns`, `kube-proxy`, `vpc-cni`), the only HPA is the 88-day-old `frontend-hpa`, and there are no annotations.
- **The product did its part:** one verdict (`failed`, never `passed`), the rollback ran, every attempted write is in the command audit, and the issue went back for a new plan.
- **From then on:** the driver checks every step's command against the allowed writes before approving, and trims or rejects otherwise (see A9–A10 and C#1).

## Fixes made during the E2E

| # | Defect | Fix |
|---|---|---|
| 1 | **The image could not be built from a clean checkout since S2**, which added `home.test.ts`. Two frontend tests read shared fixtures through `node:fs` / `node:path`, and the project never declared `@types/node`. Locally `tsc` found a stray copy in a home-directory `node_modules`, so every gate passed while every clean build failed | `7b4b2b6`: `@types/node ^20` as a dev dependency (the Dockerfile's node:20); `typeRoots` pinned to the project's own `node_modules/@types`, so the local gate sees what a clean build sees. RED: `tsc` with the pinned type roots gave the Docker log's 6 errors. GREEN: `tsc` 0; `npm ci && npm run build` in an empty directory OK |
| 2 | **A real chat report could not be translated** (`protected_values_changed`, deterministic at temperature 0). (a) The resource-id pattern took the word `cluster-admin` for an id; the opaque placeholder sat in a parenthetical and the model dropped it. (b) The protected-value hash compared values **in order of appearance**, so a translation that writes the date before the time (as zh does) was refused even with every value intact | `52e1c3f`: a resource id must contain a digit (`cluster-admin`, `cluster-wide`, `db-admin`, `nat-gateway` stay prose; `i-0abc…`, `vol-…`, `cluster-7f3k2` stay protected), and the hash compares the values as a multiset (any value changed, dropped, added, duplicated or merged still fails). RED → GREEN: `test_a_hyphenated_word_is_prose_not_a_resource_id` (6), `test_a_translation_may_reorder_the_values`; `test_a_duplicated_or_dropped_value_still_changes_the_hash` guards the other side. The same report then passed on the real model; live on pod 2, B7 passes |

## Observations (not fixed in this release)

1. **The SRE over-reaches on a fix plan.** Both fix plans for a «replicas at 0» issue added a cluster-wide add-on install, an HPA and annotations, at L2. Nothing in policy limits a fix plan to the issue's own resources. The human review caught it; the execution role's IAM stopped the one AWS write.
2. **A rollback can bring back the outage.** Plan #1's rollback for «restore failed half-way» was «scale both back to 0».
3. **The command classifier marks `kubectl rollout status` (read-only) as write**, and the first attempt of each was refused, then retried. It also marks `aws eks create-addon` as tier `unknown`, which the executor was allowed to attempt inside an approved plan. A write command of unknown tier should be treated as write.
4. **`RCAResult.model_id` is empty** in the API for the RCA run.
5. **Run `duration_ms` is 45000 for both runs** (45 s each); it looks reported, not measured.
6. **The cluster's OpenTelemetry operator injects auto-instrumentation** into the app pod, which logs failures to reach a `cloudwatch-agent` that is not running. It is cluster configuration, not the app.
7. **The scan cannot list EFS** (`aws efs describe-file-systems` → error): the IRSA role lacks the permission, as in 2.6.1.
8. **`pending_acceptance` was not reached live** (both runs were final), and B5 did not reach the resolver's refusal (the agent refused first).

## Cost

From `GET /api/cost/summary`:

| | USD | Breakdown |
|---|---|---|
| Pod 1 | **10.33** | SRE (Fable 5.1, 2 fix plans + 1 change review) 5.35, executor 2.83, RCA 2.04, chat 0.12 |
| Pod 2 | **0.54** | — |
| Total | **10.87** | — |

Translation and critic calls are not in the cost summary (a known S6 gap).

## Writes performed

- **chaos-lab cluster:**
  - the app (`agenticops` Deployment image `fe7e9fd` → `7b4b2b6` → `52e1c3f`, its Secret, env `AIOPS_EXECUTOR_AUTO_APPROVE_L0_L1=false`);
  - the leftover 2.6.1 fault restored at the start (`backend` / `frontend` had been at 0 replicas since the 2.6.1 E2E);
  - the drill's scale-to-zero, plan #1's restore and its rollback, plan #2's restore, C#2's scale to 2, and the operator's restore to 3.
  - End state: `frontend 3/3`, `backend 2/2`, no fault active, the app still deployed (ClusterIP).
- **AWS account:** no resource created or changed. The one attempted write (`eks:CreateAddon`) was refused; the add-on list is the same before and after.
- **ECR (us-east-1):** tags `7b4b2b6`, `52e1c3f`.
- **S3:** `e2e/src-7866994.tar.gz`, `src-7b4b2b6.tar.gz`, `src-52e1c3f.tar.gz`.
- **Dev box:** `/tmp/aiops-build-<sha>` directories only. The running service, its database, agent-memory and skills were not touched.
