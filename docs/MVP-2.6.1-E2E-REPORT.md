# MVP-2.6.1 — Joint Live E2E Evidence Report

> **Status: in progress — the location eval and the API checks are done; the owner's UI walkthrough (checklist items 2, 3, 6 UI part, 7) is pending.**
> **Date:** 2026-10-02 / 2026-10-03 · **Branch:** `MVP-2.6.1` · **Deployed commit:** `fe7e9fd` (the location eval's `off` and on #1 ran `f4127b3`)
> **Scope:** design §7 joint live E2E + §8 acceptance (`docs/superpowers/specs/2026-09-28-mvp-2.6.1-graph-rca-loop-and-issue-change-design.md`,
> release note `docs/MVP-2.6.1-RELEASE.md`). Location eval detail: `docs/MVP-2.6.1-LOCATION-EVAL-REPORT.md`.
>
> **Route A (owner decision):** everything runs in the `agenticops-chaos-lab` EKS cluster; the dev box is updated only after
> the push is approved. **Writes were limited to the chaos-lab cluster** (see [Writes performed](#writes-performed)).

---

## Environment

| Item | Value |
|------|-------|
| Cluster | `agenticops-chaos-lab` (us-east-1), EKS 1.32, 3 nodes (2 × `chaos-lab-ng`, 1 × tainted `agenticops-ng` for the app) |
| App | in-cluster Deployment `agenticops/agenticops`, ClusterIP only (no public Service — `deploy-app.sh` refuses `LoadBalancer`/`NodePort`), 4 uvicorn workers, SQLite on emptyDir, **API auth ON** (`admin`), `rbac_enforce=false` (shadow) |
| Reached from | the operator's laptop through a supervised `kubectl port-forward` (`:8899` for the eval batches, `:8900` for the walkthrough) |
| Image | `agenticops:f4127b3`, then `agenticops:fe7e9fd` — built on the dev box, not locally (see [Remote build](#remote-build)) |
| Models | committed defaults; the RCA agent (Opus 4.6) and the critic (Haiku 4.5) carry the eval cost, SRE review is Fable 5.1 |
| Walkthrough settings | `AIOPS_EXECUTOR_AUTO_APPROVE_L0_L1=false` (every plan waits for a human), `change_auto_approve_standard=false`; webhook secret and change-intake secret set from a 0600 env file outside the repo, never committed |
| Target account | `chaos-lab` (533267047935, us-east-1), resolved through the provider layer; kubeconfig `/var/run/agenticops/kubeconfig` per cluster |

## Test 0 — Gates

| Gate | At `fe7e9fd` |
|------|------|
| `pytest tests/` | **6350 passed, 85 skipped, 1 failed** — the failure is `test_web_tools::test_invalid_headers_json`, the documented local-DNS false failure (`example.com` resolves to a reserved address on this machine, so the SSRF guard fires first) |
| Frontend (`tsc`, vitest, `vite build`, locale parity) | unchanged since `f4127b3` (no frontend change after it): `tsc` 0 errors, vitest 27 files / 279, build OK |

## Remote build

Docker Desktop on the operator's laptop is blocked by an organisation sign-in, and the owner asked for the image to be
built remotely. Path used: `git archive <sha>` → `s3://agenticops-deploy-533267047935/e2e/src-<sha>.tar.gz` → presigned
URL → the dev box (`i-0935450a95f321942`, over SSM) builds in `/tmp/aiops-build-<sha>` with `docker/Dockerfile` and pushes
`agenticops:<sha>` to ECR us-east-1. The dev box's running service was not touched. Pitfall: the bucket is in
ap-southeast-1, so the presign must pass `--region ap-southeast-1`; without it the URL 301-redirects and the box
saves an XML error page that `tar` reports as "not in gzip format".

## Checklist results

| # | Item (release note «联合 live E2E 清单») | Result |
|---|---|---|
| 1 | Location eval, 13 cases × off / on | **Done** — off AC@1 0.00 → on #2 **0.77** (on #1 before the recollect fix: 0.38); located 15% → 100%; graph recall 13/13 in every batch. Acceptance 3 / 4 pass, 5 reported. Detail and per-case misses: `MVP-2.6.1-LOCATION-EVAL-REPORT.md` |
| 2 | Fix flow (approve with hash → execute → `pending_acceptance` → accept; edited plan → execution refused) | **Pending owner.** Prepared: I#1 is a live scale-to-zero fault (chaos-lab `backend` / `frontend` at 0 replicas). RCA located `Deployment chaos-lab/backend` at rank 1, but at confidence 0.57 with critic `weak` the post-RCA gate sent it to `needs_review` — no auto plan, as designed. The walkthrough starts with «Generate fix plan» on IssueDetail. The `infra/eks-lab/.../case-6-unhealthy-targets/verify.sh` approve block needs the eks-lab cluster, not chaos-lab — not run on route A |
| 3 | Change flow (NewChangeDialog → SRE review → ChangeDetail → approve → execute → acceptance) | **First attempt: safety pass, happy path not shown.** The owner approved C#1 (from the intake check below; plan #1 L1) as `user:admin` at 09:55:56 UTC and queued it with Execute at 09:56:11; the executor picked execution #1 up at 09:56:17 and **aborted it at pre-check #1** at 09:56:39: «Deployment frontend in chaos-lab namespace reports 0 ready replicas (expected 3/3). Execution aborted to prevent changes on an unhealthy deployment.» — no step ran, C#1 `failed`, acceptance card «Failed». Cause: a preparation conflict — C#1 targets the same Deployment the live I#1 fault (item 2) had scaled to 0. The walkthrough also led to an owner ruling: **approving a change runs it** (release note «变更批准即执行»; red test `6cf348e`, implementation `e762b9a`). Item 3 is re-run on the new image with a fresh request against a healthy target, after item 2 |
| 4 | Change intake | **Pass** — table below |
| 5 | Alert webhook token | **Pass** — table below |
| 6 | Connectors | API part **pass**: each run `partial` (lab RBAC grants no `secrets` read — by design), 129 K8s objects created, `absent` 0 on a partial run; no `K8s_Secret` row at all; Galaxy build #3 (after onboarding) 175 nodes / 260 edges with the K8s objects. Count invariant live: `/api/stats` 167 = `/api/resources` total 167 = Σ type-counts 167. UI part (card «Run now», 409 on a second click, `?focus=` deep link) **pending owner**. The 409 lock is per process and the pod runs 4 workers, so the 409 may not reproduce (see Observations) |
| 7 | UI walkthrough | **Pending owner** |

### Item 4 — change intake (`POST /api/changes/intake`)

| Step | Expected | Live |
|---|---|---|
| Secret unset, anonymous caller | 404 | **401** «Authentication required» — see note |
| Secret unset, authenticated caller | 404 | **404** «Change intake is not configured» |
| Wrong signature | 401 | **401** |
| Right signature, timestamp 1 h old | 401 | **401** |
| Right signature | 201, requester `webhook:<system>` | **201**, C#1, `requested_by=webhook:e2e-itsm` |
| Same external ticket again | 200, same request | **200**, C#1 |
| `webhook:*` approves / executes (in-pod `change_service.approve` / `request_execution`, shadow mode) | 403 | **403** `ChangeForbidden` both, «webhook actors may never change.approve / change.execute» |

Note: with API auth on, `APIAuthMiddleware` exempts the intake route only while `change_intake_secret` is set
(`web/app.py`, «unset, it is a 404»). An unconfigured intake is therefore behind the normal bearer check: an anonymous
caller gets the generic 401, an authenticated one the 404. The unit test runs without API auth. Behaviour is safe (an
anonymous caller learns nothing about the route); the release note's «未配置 404» holds for an authenticated caller.
No HTTP route lets a webhook actor approve, so the 403 was checked at the service layer, inside the running pod.

### Item 5 — alert webhook token (`POST /api/webhooks/alert/cloudwatch`, `webhook_secret` set)

| Step | Expected | Live |
|---|---|---|
| No token | 401 | **401** «webhook token or signature required» |
| Wrong `X-AIOps-Token` | 401 | **401** |
| Right `X-AIOps-Token` | 200 | **201** — Signal #1 promoted to HealthIssue #1 (201 Created is the route's status for a new issue; the release note's «200» means accepted) |

## Fixes made during the E2E

All are new commits on top of `f4127b3`; nothing was amended.

| Commit | What | Why |
|---|---|---|
| `4967eb5` | chaos-lab `service-deleted` restores the backend Service from the workloads manifest | its restore could never re-apply its own backup, so the first `off` batch lost the Service |
| `ffc9de1` | lab app: `tcpSocket` liveness, `dnsPolicy: Default`, kubeconfig by API-server service IP | `coredns-down` got the app SIGKILLed: liveness was `/api/health`, which makes a live STS call, so the DNS outage it was asked to locate failed the probe (Ruling E-T10b: the observer stays out of the fault domain) |
| `3907747` | the harness supervises its port-forward | an app restart killed the tunnel and voided every later case |
| `c3137c5` | each location batch saves its `GET /api/cost/summary` before cleanup | the cleanup restart empties the emptyDir database, and with it the batch's cost |
| `b401d36` + `fe7e9fd` | red test, then the fix: the RCA K8s recollect is skipped only when the last collection is younger than `rca_k8s_recollect_min_age_seconds` **and** no earlier than the issue's onset | on #1 ranked the previous case's objects first; spec §3.C.2 修订 2026-10-03, Ruling E-T10f (owner chose «fix product + re-run») |

The first `off` batch (6/13 valid) was void for the first three causes and is not scored; the scored batches are listed in
the location eval report.

## Observations (not fixed in this release)

- **The single-process premise does not hold in the shipped deployments.** Spec §10.3 says «当前部署是单进程», and
  three 2.6.1 guards are process-local `threading.Lock`s:
  - the connector run lock behind the «already running» 409 and the card's running badge (`connectors/runner.py`, `is_running`);
  - the rule-publication lock shared by normal Galaxy builds and rule-only refreshes (`galaxy/builder.py`, `_RULE_LOCK`;
    release note A-2);
  - the intake dedup lock (`services/change_service.py`, `_intake_lock`; release note D-9).

  But `docker/Dockerfile` (this lab) and the dev box's systemd unit (`iac/deploy-sg/deploy.sh` rewrites it to
  `--workers 4`) both run **4 uvicorn workers**. So a second «Run now» that lands on another worker is accepted and starts a
  parallel run instead of returning 409. The badge depends on which worker answers the poll. Two workers can publish
  rule relations at once. Two intake deliveries of one ticket can each create a request. Found by reading the code and the
  unit files; not provoked live, because overlapping rule publications could damage the lab database the walkthrough
  uses. Item 6's 409 step is expected to be nondeterministic here.
- **`/api/health` blocks its worker's event loop** — it is `async def` and calls STS synchronously. Harmless while STS
  answers fast; during a DNS outage it held the probe past its timeout. The lab now uses a `tcpSocket` liveness probe;
  the endpoint itself is unchanged (pre-existing).
- **`--workers 4` + SQLite startup race** — every worker runs `init_db` at startup. One lost the `create_all` race
  (`table aws_accounts already exists`, «Application startup failed»), and the pod stayed Ready on the other three.
  Pre-existing (`docker/Dockerfile`).
- **`dnsPolicy: Default` costs the lab its OTel export** — with node DNS the pod cannot resolve
  `cloudwatch-agent.amazon-cloudwatch`, so the ADOT exporter logs a resolve error per flush. Accepted for the lab, where
  surviving `coredns-down` matters more. A real deployment on `ClusterFirst` that observes its own cluster shares that
  cluster's DNS fault domain; put the observer outside it, or reach the API server by IP as the lab does.
- **Connector runs are always `partial` in the lab** — `infra/eks-chaos-lab/agenticops/rbac.yaml` grants no `secrets`
  read on purpose, so the Secret kind never lists completely. A partial run still refreshes the evidence pack, and marks
  nothing absent.
- **Credential hygiene during the run** — the three E2E secrets were once echoed into the operator's local tool output by a
  redaction that missed `export`-prefixed lines. All three were rotated before the walkthrough; the cluster Secret was
  re-applied from the rotated file. No secret is in any committed file.

## Writes performed

- **chaos-lab cluster:** the 13 eval faults, each injected and restored by the harness (cleanup restored every fault and
  removed the eval environment); the app Deployment, its Secret and env (`AIOPS_EXECUTOR_AUTO_APPROVE_L0_L1=false`) for the
  walkthrough; the live I#1 fault (`chaos/pod-kill.sh scale-zero`) — restore with `bash infra/eks-chaos-lab/chaos/pod-kill.sh restore`
  if the fix flow does not scale it back.
- **ECR (us-east-1):** image tags `f4127b3`, `fe7e9fd`. **S3:** `e2e/src-<sha>.tar.gz` source archives in the deploy bucket.
- **Dev box:** build directories under `/tmp` only; the running service, its database, agent-memory and skills were not touched.
- **AWS account resources:** none written (the eval and the walkthrough read AWS through the provider layer).
