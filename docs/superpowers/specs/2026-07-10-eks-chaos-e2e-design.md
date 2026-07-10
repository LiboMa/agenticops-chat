# EKS Chaos E2E — In-Cluster AgenticOps + Four-Phase Verification

**Date:** 2026-07-10
**Branch:** MVP-2.2.0
**Status:** Design — awaiting user review

## Goal

Prove AgenticOps performs the full autonomous loop — **感知 (perceive) → 分析 (analyze) → 解决 (resolve) → 记录 (record)** — against real, injected failures on a live EKS cluster, with:

1. The app deployed as an **internal-only** service (⚠️ **never** exposed to the public internet — no ALB, no CloudFront, no public LB).
2. **Chaos injection** on a shared EKS cluster (reuse existing lab).
3. An **E2E test suite** runnable **from a remote server**, combining deterministic pass/fail asserts **and** captured chat/report evidence.
4. **More scenarios** than the existing six.

Success = a single command from a remote box injects each fault, then verifies the four phases completed (via REST API asserts) and/or captures the agent's narrative + report as reviewable evidence, then restores the cluster to green.

## Non-Goals

- Not a production deployment path (prod uses its own IaC; dev box `deploy-sg` unchanged).
- Not multi-account (monitor account == target account; single-account, IRSA-based).
- Not a rewrite of the chaos scripts or the pipeline — we orchestrate what exists.
- No changes to application source under `src/agenticops/` are required by this design. (If a gap surfaces during implementation, it is called out then, not assumed here.)

## What Already Exists (reused, not rebuilt)

| Asset | Path | Reuse |
|---|---|---|
| EKS lab cluster def | `infra/eks-chaos-lab/cluster.yaml` | `agenticops-chaos-lab`, us-east-1, OIDC on, CloudWatch observability addon — used as-is |
| Cluster + workloads setup | `infra/eks-chaos-lab/setup.sh` | IAM role → cluster → frontend/backend workloads → 6 alarms — used as-is |
| 6 chaos scripts | `infra/eks-chaos-lab/chaos/*.sh` | pod-kill, resource-stress, network-chaos, node-drain, config-break, restore-all — the assert-mode inject/restore commands |
| Restore-all | `infra/eks-chaos-lab/chaos/restore-all.sh` | Per-scenario safety net |
| Readonly IAM policy | `infra/eks-chaos-lab/iam/readonly-policy.json` | Base of the IRSA perceive policy |
| Prod container image | `docker/Dockerfile` + `docker/build.sh` | Built + pushed to ECR, run in-cluster **unmodified** (already ships aws/kubectl/git/ssh) |
| API auto-chain | `web/app.py` + `services/pipeline_service.py` | `POST /api/health-issues` → auto-RCA → auto-SRE → auto-approve L0/L1 → auto-execute → resolve → post-resolution |
| Polling harness patterns | `infra/eks-lab/scenarios/common.sh` | `wait_for_health_issue`/`wait_for_status`/`get_fix_plan` logic ported into the Python client |
| Richer scenarios | `infra/eks-lab/scenarios/case-*` | Source for CoreDNS-down / service-deleted evidence scenarios |

**Confirmed API auto-chain** (`web/app.py`): creating a `HealthIssue` (via `POST /api/health-issues` or `POST /api/webhooks/alert`) fires `trigger_auto_rca` → `trigger_auto_sre` (`auto_fix_enabled`) → `trigger_auto_approve` (`executor_auto_approve_l0_l1`) → `trigger_auto_execute` → issue transitions to `resolved` → `trigger_post_resolution` (RAG pipeline + `distill_case_study` = KB record). Every stage emits `PipelineEvent`s queryable at `GET /api/health-issues/{id}/timeline` and `GET /api/trace/{trace_id}`.

## Architecture

```
┌─ Remote test server (kubectl + python + repo checkout) ─────────────────┐
│  run-e2e.sh:                                                            │
│   1. kubectl port-forward svc/agenticops 8000:8000  (background tunnel) │
│   2. per scenario: inject → poll REST API → assert 4 phases → restore   │
│   3. evidence scenarios: drive chat SSE, capture transcript + report    │
│   4. collect results/ + junit.xml                                       │
└────────────────────────────┬───────────────────────────────────────────┘
                 kubectl (EKS API, CIDR-restricted) — no public app ingress
                              ▼
┌────────── EKS cluster: agenticops-chaos-lab (us-east-1) ────────────────┐
│                                                                          │
│  namespace: agenticops              namespace: chaos-lab (the TARGET)   │
│  ┌────────────────────────────┐     ┌──────────────────────────────┐   │
│  │ Deployment: agenticops     │     │ frontend (nginx) x3          │   │
│  │  image: <ECR>/agenticops   │     │ backend  x2                  │   │
│  │  Service: ClusterIP :8000  │     │ HPA / PDB / configmap        │   │
│  │  SA: agenticops            │     │ + injected chaos artifacts   │   │
│  │   ├ IRSA → readonly + BR   │     └──────────────────────────────┘   │
│  │   └ in-cluster kubeconfig  │──── kubectl (SA token) ──▶ fixes here   │
│  └────────────────────────────┘                                        │
│         │ boto3 (IRSA)                                                  │
│         ▼                                                               │
│  CloudWatch alarms / Logs / EKS describe   (perceive)   Bedrock (analyze)│
└──────────────────────────────────────────────────────────────────────────┘

NO public internet path to the app. ClusterIP only. Sole ingress = port-forward
from the remote server over the CIDR-restricted EKS API endpoint.
```

### Two identities, both least-privilege

The app pod carries **two** credential paths, because "perceive" and "fix" have different trust needs:

**1. Perceive — AWS APIs via IRSA.** The `agenticops` ServiceAccount is bound (via `eksctl create iamserviceaccount`) to an IAM role carrying `iam/agenticops-irsa-policy.json` = the existing `readonly-policy.json` (CloudWatch/Logs/CloudTrail/EKS/EC2/ELB read) **plus** `bedrock:InvokeModel` + `bedrock:InvokeModelWithResponseStream`. The projected token is the pod's default AWS chain. AgenticOps registers a `chaos-lab` account with **`source_type: environment`** (region us-east-1) — per 凭证铁律 rule 2, `environment` is the one legal "use the local default chain" declaration; it is resolved through the provider layer and validated by `GetCallerIdentity`. No ambient fallback, no cross-account AssumeRole (single account).

**2. Perceive + Fix — kubectl via in-cluster ServiceAccount.** The container's start command writes an **in-cluster kubeconfig** (SA token at `/var/run/secrets/.../token` + CA cert → `https://kubernetes.default.svc`) and exports `KUBECONFIG` to point at it. `skills/execution.py:_execute_kubectl` already honors a pre-set `KUBECONFIG` (line 445), bypassing `aws eks update-kubeconfig` entirely — so both read and write kubectl flow through the SA token. No `aws-auth` ConfigMap mapping, no IAM-for-kubectl needed.

### Fix-path RBAC (scoped least-privilege — decided)

The SA gets exactly the verbs the eight scenarios' fixes require, no more:

- **ClusterRole `agenticops-observe`** (cluster-wide): `get/list/watch` on core + apps + networking + metrics resources (pods, nodes, services, endpoints, deployments, replicasets, events, namespaces, networkpolicies, configmaps, hpa, pvc, pv). Plus `patch` on `nodes` (for uncordon) and `create` on `pods/eviction` if drain-recovery needs it.
- **Role `agenticops-remediate` in `chaos-lab`** (namespaced): the mutating verbs — `patch/update` on deployments (scale, set-image), `delete` on pods, `delete` on networkpolicies, `create/update` on configmaps, `delete` on jobs/stress pods.
- **Role `agenticops-dns-remediate` in `kube-system`** (namespaced, evidence scenarios only): `patch` on `deployments/coredns` (scale back up). Kept separate + minimal because kube-system is sensitive.

No `cluster-admin`. Blast radius is contained to `chaos-lab` + node cordon state + coredns replica count.

## Components

New tree under `infra/eks-chaos-lab/`:

```
infra/eks-chaos-lab/
├── agenticops/                    # NEW: in-cluster app deployment
│   ├── deploy-app.sh              #   build→ECR→IRSA SA→apply→wait ready (one command)
│   ├── namespace.yaml
│   ├── serviceaccount.yaml        #   annotated for IRSA (ARN filled by deploy-app.sh)
│   ├── rbac.yaml                  #   ClusterRole + 2 Roles + bindings (scoped)
│   ├── configmap.yaml             #   AIOPS_* non-secret settings
│   ├── secret.example.yaml        #   admin password etc. (real one created by script, gitignored)
│   ├── deployment.yaml            #   pod: in-cluster kubeconfig init + uvicorn
│   └── service.yaml               #   ClusterIP :8000 (NO LoadBalancer)
├── iam/
│   └── agenticops-irsa-policy.json   # NEW: readonly + bedrock:InvokeModel*
└── e2e/                           # NEW: the E2E harness
    ├── scenarios.yaml             #   declarative scenario registry (see below)
    ├── client.py                  #   AgenticOpsClient: login→Bearer, pollers (ported from common.sh)
    ├── conftest.py                #   pytest fixtures: client, scenario loader, restore-on-teardown
    ├── test_e2e_four_phases.py    #   parametrized: assert-mode scenarios
    ├── test_e2e_evidence.py       #   parametrized: evidence-mode scenarios (chat + report capture)
    ├── run-e2e.sh                 #   port-forward tunnel → pytest → collect artifacts
    ├── results/                   #   (gitignored) per-scenario evidence + junit.xml
    └── README.md
```

### `scenarios.yaml` — the single registry

Each scenario is declarative so adding cases = adding YAML, not code:

```yaml
- id: scale-to-zero
  mode: assert
  description: "Frontend+backend scaled to 0 replicas"
  inject:  "chaos/pod-kill.sh scale-zero"
  perceive:                       # how the harness seeds/expects perception
    signal: "RunningPods-Low"     # CloudWatch alarm name suffix OR log keyword
    title_pattern: "running pods|replicas|scaled"
  expect_fix: "replicas >= 1"     # human-readable; asserted via kubectl post-resolve
  restore: "chaos/pod-kill.sh restore"
  timeout_perceive_s: 240
  timeout_resolve_s: 420
- id: bad-image
  mode: assert
  inject:  "chaos/config-break.sh bad-image"
  perceive: { signal: "PodRestarts-High", title_pattern: "image|ImagePull|restart" }
  expect_fix: "image != *nonexistent*"
  restore: "chaos/config-break.sh restore"
  ...
```

| # | id | inject | 感知 signal | 解决 (fix) | mode |
|---|---|---|---|---|---|
| 1 | scale-to-zero | pod-kill.sh scale-zero | RunningPods-Low | scale up | assert |
| 2 | bad-image | config-break.sh bad-image | PodRestarts-High / ImagePullBackOff | set valid image | assert |
| 3 | crashloop-config | config-break.sh bad-config | RunningPods-Low / CrashLoop | restore configmap | assert |
| 4 | node-drained | node-drain.sh drain | NodeCount-Low | uncordon node | assert |
| 5 | resource-stress | resource-stress.sh start | NodeCPU/Mem-High | delete stress pod | assert |
| 6 | netpol-block | network-chaos.sh block | connection errors in logs | delete networkpolicy | assert |
| 7 | coredns-down | (ported from eks-lab case-7) | DNS resolution failures | scale coredns ≥1 | evidence |
| 8 | service-deleted | (ported from eks-lab case-10) | empty endpoints | recreate service | evidence |

Assert-mode = deterministic, agent-achievable fixes with a machine-checkable end state. Evidence-mode = harder/ambiguous fixes where we capture the agent transcript + generated report for human judgement rather than a hard assert. Both run in one `run-e2e.sh` pass. **Scenario count grows from 6 → 8 now, and the YAML registry makes further additions cheap** (this satisfies "add more test cases").

### The four-phase assertion (assert mode)

For each assert scenario, `test_e2e_four_phases.py` does:

```
1. restore_precondition()                     # ensure green start
2. inject()                                    # run the chaos script (via kubectl, from remote)
3. seed_perception()                           # see "Perception entry" below
4. issue_id = poll GET /api/health-issues      # 感知: assert an issue appears (title_pattern, recent)
5. poll GET /api/health-issues/{id}/rca        # 分析: assert ≥1 RCAResult attached
6. poll GET /api/health-issues/{id} status     # 解决: assert reaches "resolved"
   AND poll GET /api/fix-plans?health_issue_id # assert a FixPlan executed
   AND kubectl assert expect_fix end-state      # assert the cluster is actually fixed
7. assert GET /api/health-issues/{id}/timeline # 记录: assert PipelineEvents for rca/fix/resolve
   AND GET /api/trace/{trace_id}                # assert linked artifacts
8. teardown: restore()  (always, even on failure — pytest fixture)
```

**Perception entry (seed_perception).** Two supported modes, chosen per deployment:

- **`webhook`** (default, deterministic): after injecting, POST the corresponding CloudWatch-style alert to `POST /api/webhooks/alert/cloudwatch`. This is the documented dual-intake path and makes 感知 immediate and reliable in a test. The alarm is real (created by `setup.sh`), so the payload mirrors a genuine CloudWatch alarm transition.
- **`patrol`** (optional, more autonomous): rely on the scheduled health patrol / detect agent to notice via CloudWatch. Slower and flakier (metric propagation ~5–10 min), gated behind a `--mode=patrol` flag for a "fully hands-off" demo run. Default runs stay on `webhook` for CI determinism.

This choice is explicit in `scenarios.yaml`/CLI, never silent — if patrol mode times out, the harness logs that perception (not the fix) was the failure point.

### Evidence mode

For scenarios 7–8, `test_e2e_evidence.py`:
1. inject the fault,
2. open a chat session (`POST /api/chat/sessions`), send a prompt like *"investigate and fix the DNS failures in the chaos-lab namespace"* (`POST /api/chat/sessions/{id}/messages`),
3. stream the SSE response, capture the full transcript to `results/<id>/transcript.md`,
4. capture any generated report (`GET /api/reports`, newest) to `results/<id>/report.{md,html}`,
5. capture the timeline/trace JSON,
6. assert only the soft guarantees (a session completed, a transcript exists, no crash) — the report is the deliverable for human review,
7. restore.

### `run-e2e.sh` (the remote entrypoint)

```
run-e2e.sh [--mode webhook|patrol] [--scenarios id1,id2] [--assert-only|--evidence-only]
  1. preflight: kubectl reachable, svc/agenticops exists, app /api/health OK
  2. start `kubectl port-forward svc/agenticops -n agenticops 8000:8000` (bg, trap-killed on exit)
  3. export AGENTICOPS_URL=http://localhost:8000, KUBECONFIG
  4. python -m pytest e2e/ -v --junitxml=results/junit.xml   (parametrized by scenarios.yaml)
  5. print summary table (scenario | perceive | analyze | resolve | record | duration)
  6. always run chaos/restore-all.sh at the end
```

## Data Flow (one assert scenario, end to end)

```
remote: pod-kill.sh scale-zero ──kubectl──▶ chaos-lab: frontend/backend → 0 replicas
remote: POST /api/webhooks/alert/cloudwatch {RunningPods-Low} ─▶ app
  app: parse alert → create HealthIssue (感知) → trigger_auto_rca
       → RCAResult attached (分析)
       → trigger_auto_sre → FixPlan(L0/L1) → auto-approve → auto-execute
            executor runs: kubectl scale deploy/frontend --replicas=3  (解决, via SA token)
       → issue → resolved → trigger_post_resolution → RAG + distill_case_study (记录)
remote: poll API asserts each phase ✓  → kubectl confirms replicas≥1 ✓
remote: pod-kill.sh restore  (teardown)
```

## Error Handling & Safety

- **Fail-closed restore:** every scenario restores in a pytest teardown fixture regardless of pass/fail; `run-e2e.sh` also runs `restore-all.sh` at the very end. If restore can't return the cluster green within timeout, the run is marked failed (never leaves the lab broken silently).
- **Phase attribution:** each assert reports *which* phase failed (perceive/analyze/resolve/record) so a failure is diagnosable, not just "timed out".
- **No public exposure invariant:** `service.yaml` is `type: ClusterIP` with a comment forbidding LoadBalancer/NodePort; a preflight check in `deploy-app.sh` refuses to apply if the manifest contains `LoadBalancer`. The EKS API endpoint stays `publicAccess: true` but `publicAccessCIDRs` restricted to the remote server (documented; a "flip to fully private + bastion" note included for later hardening).
- **Idempotent deploy:** `deploy-app.sh` is safe to re-run (checks for existing SA/ECR repo, `kubectl apply` is declarative).
- **Isolation:** the app runs in its own `agenticops` namespace; chaos only touches `chaos-lab` (and `kube-system/coredns` for scenario 7). The app's own deployment is never a chaos target.
- **Secrets:** the admin password + any API keys land in a k8s `Secret` created by `deploy-app.sh` from env/prompt, never committed (`secret.example.yaml` is the template; real secret gitignored).

## Testing (of this harness itself)

- **Static:** `bash -n` on every new shell script; `python -m py_compile` on `client.py`/`conftest.py`/tests; `kubectl apply --dry-run=client` on every manifest; a lint asserting no `LoadBalancer`/`NodePort` in `service.yaml`.
- **Unit (offline, no cluster):** `client.py` pollers unit-tested against a mocked `httpx`/`requests` (fixtures replay recorded API JSON) — lives in the repo `tests/` so it runs in normal CI without AWS.
- **Live E2E:** the suite itself, run from the remote server against the real cluster — the deliverable. Not part of offline CI (needs AWS + cluster).

## Rollout Plan (implementation order)

1. IRSA policy + `deploy-app.sh` + manifests → app running in-cluster, `/api/health` green via port-forward.
2. Register `chaos-lab` account (`environment` source) in the running app; confirm scan/detect see the cluster.
3. `client.py` + `conftest.py` + offline unit tests (green in CI).
4. `scenarios.yaml` + `test_e2e_four_phases.py` for the 6 assert scenarios; run live; tune timeouts.
5. Port coredns-down + service-deleted as evidence scenarios; `test_e2e_evidence.py`.
6. `run-e2e.sh` end-to-end from the remote server; capture a full results/ artifact set.
7. Docs: `infra/eks-chaos-lab/e2e/README.md` + update `docs/WORKFLOW.md` with the chaos-E2E runbook.

## Open Questions

None blocking. Deferred hardening (post-MVP): flip EKS endpoint to fully private + SSM bastion; add Litmus-based chaos (`infra/eks-lab/chaos/litmus-values.yaml` exists) for richer fault injection.
