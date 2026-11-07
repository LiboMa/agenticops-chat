# Strands Agents 1.45 → 1.64 — upgrade and verification report

> **Date:** 2026-11-06 / 2026-11-07 · **Scope:** `strands-agents` 1.45.0 → 1.64.0 (released 2026-11-04), behaviour-preserving ·
> **Commits:** `3eb8883` (upgrade), `18d587a` (docs) on `feat/strands-1.64`; merged to `main` on 2026-11-07 together with the
> viewer-settings work (`ae62cd2`) — merge commit `603046d` (PR #33; PRs #29 and #32 merged with it) · **Status: done, deployed
> to the dev box.** No version bump: the app still reports 2.7.0 (see the post-release addendum in
> [`MVP-2.7.0-RELEASE.md`](MVP-2.7.0-RELEASE.md)).
>
> Inputs: the upgrade study [`superpowers/specs/2026-11-06-strands-upgrade-study.md`](superpowers/specs/2026-11-06-strands-upgrade-study.md)
> and the follow-up decision report
> [`superpowers/specs/2026-11-06-strands-164-feature-feasibility.md`](superpowers/specs/2026-11-06-strands-164-feature-feasibility.md)
> (the owner picked its combination A for the next release on 2026-11-07).

## 1. Summary

The upgrade changes no behaviour. Two silent changes in the SDK had to be neutralised, and a third was found during the live
gate and neutralised as well:

| # | SDK change | What it would have done to us | What we do now |
|---|---|---|---|
| 1 | **1.56** — any `context_manager` makes the agent discard a passed `conversation_manager` (a `UserWarning` is the only signal) | All 9 agent builds passed `context_manager="auto"`: every per-agent sliding window (detect 8000, scan 1000, executor / reporter 1800 …) would have stopped working | No build passes `context_manager`. `config.get_agent_context_plugins` passes the 1.45 "auto" offloader explicitly — `ContextOffloader(InMemoryStorage, 1500 / 750 tokens)`, now `context_offload_*` in `settings.yaml` |
| 2 | **1.55** — `cache_tools` deprecated; **1.53/1.64** — `CacheConfig` gains `tools_ttl` / `system_prompt_ttl` (the latter on by default) | A deprecation warning, and a different cache layout (system prompt cached too) | `CacheConfig(strategy="auto", tools_ttl=True, system_prompt_ttl=False)` — exactly the 1.45 cache points. System-prompt caching is a separate, measured change (feasibility report X7) |
| 3 | **1.64** — the offloader's preview of a large tool result is now 60 % head + 40 % tail (1.45: head only) | The RCA topology evidence (~20k tokens, always offloaded) lists candidates, then edges, then neighbours: the 1.45 head showed the candidates and the first edges, the 1.64 head + tail showed **no edge**. The RCA then guessed causal-path edges and the location dropped to `partial` (§3.5) | A `_slice_preview` override keeps the 1.45 preview (`config._head_preview_offloader_class`); the parity test pins it and checks the SDK still calls it |

`uv.lock` and `requirements.txt` move `strands-agents` only (1.45.0 → 1.64.0); `pyproject.toml` floor `>=1.64.0,<2.0.0`.

## 2. Reachable surfaces

No new user-reachable capability. CLI / Web API / Web UI / Agent tool / Schedule / Notification: unchanged (non-goal). Two
new settings, schema defaults equal to the committed values: `context_offload_max_result_tokens: 1500`,
`context_offload_preview_tokens: 750`.

## 3. Verification

| Gate (plan acceptance criterion) | Result |
|---|---|
| 1 Only strands moves in the lock | Pass — `uv.lock` / `requirements.txt` change `strands-agents` only |
| 2 Parity test (`tests/test_strands_parity.py`, 18 tests) | Pass — real `strands.Agent` builds for 7 agents × offload on / off under warnings-as-errors: own conversation manager and window size, offloader 1500 / 750 only when on, head-only preview, SDK still calls `_slice_preview`, no `context_manager=` anywhere in `src/` |
| 3 Full pytest (throwaway DB) | Pass — see §3.2 |
| 4 Live Bedrock smoke (`scripts/smoke/strands_live_smoke.py`) | Pass — see §3.3 |
| 5 Local chat E2E | Pass — see §3.4 |
| 6 Root-cause location eval, 3 cases | Pass on the final build — see §3.5 |

### 3.1 Environment

- Unit / smoke / chat / eval ran from a worktree of `feat/strands-1.64` with its own virtualenv (1.64.0); the shared root
  `.venv` stayed on 1.45.0 for the baseline.
- Chat E2E and the location eval ran against a **local** app instance (uvicorn, one worker, auth on, throwaway SQLite) with
  the 2.6.1 location-eval environment (topology evidence on, resolved-cooldown 0, flapping threshold 1000, auto-fix off,
  RAG off), connected to the chaos-lab EKS cluster `agenticops-chaos-lab` (account 533267047935) through a private
  kubeconfig, using the 2.6.1 harness `infra/eks-chaos-lab/e2e/test_e2e_location.py` unchanged. The 2.6.1 baseline ran
  in-cluster, so wall times are not comparable (§3.5).

### 3.2 Full suite

| Run | Passed | Failed | Notes |
|---|---|---|---|
| Baseline, 1.45.0 | 6977 | 2 | `test_web_tools::test_invalid_headers_json` (local DNS resolves example.com to 198.18.x, the SSRF guard fires first — a known false failure) + one hypothesis property test (`test_session_manager_props`) |
| 1.64.0, before the preview override | 6990 | 1 | the DNS false failure only (+13 = the new parity tests) |
| 1.64.0, final | 6990 | 3 | the DNS false failure + two hypothesis `FlakyFailure`s ("falsified on the first call but not on a subsequent one") — the run shared the machine with the local app and the eval (9 m 48 s instead of ~2 min); both files pass alone (13/13). +2 tests = the two preview tests |

### 3.3 Live Bedrock smoke

One agent per distinct model id in the committed settings, built exactly like the agent modules (our conversation manager,
plugins and `bedrock_model_kwargs`): build without warnings, own window, a streamed tool call (`data` / `current_tool_use` /
`toolResult` / `result`), the model's thinking shape accepted, a second fresh agent reading the prompt cache, and
`limits={"turns": 1}`.

| Model | build | window | stream | thinking | cache read | limits |
|---|---|---|---|---|---|---|
| `global.anthropic.claude-opus-5` (main) | ok | ok | ok | ok (adaptive) | 3,864 | ok |
| `global.anthropic.claude-sonnet-4-6` (scan) | ok | ok | ok | ok (adaptive) | 1,964 | ok |
| `global.anthropic.claude-opus-4-6-v1` (rca) | ok | ok | ok | ok (adaptive) | 6,376 ¹ | ok |
| `global.anthropic.claude-fable-5-1` (sre) | ok | ok | ok | ok (adaptive) | 3,864 | ok |
| `global.anthropic.claude-haiku-4-5-20251001-v1:0` (cheap tier) | ok | ok | ok | ok (`budget_tokens`) | 6,398 ¹ | ok |
| `openai.gpt-oss-120b-1:0` | ok | ok | ok | ok (`reasoning_effort`) | n/a (not Anthropic) | ok |

`activate_skill` (web-research) registered `web_search` and `web_fetch` on a live agent.
¹ Opus 4.6 and Haiku 4.5 read **0** cache tokens with a ~4.4k-token prefix and cache normally with ~11k — the same on 1.45
(A/B measured), so a model-side minimum prefix, not a regression; the smoke script uses the ~11k prefix.

### 3.4 Local chat E2E (one session, three turns)

| Turn | Result | Time | Tools | Main-agent cost ¹ |
|---|---|---|---|---|
| Plain answer, no tools | `completed` | 5.0 s | — | $0.519 |
| Read-only sub-agent query | `completed` | 43.0 s | `get_active_account`, `sre_query` (ok) | $0.667 (+ sre $0.511) |
| Skill activation | `completed` | 7.4 s | `activate_skill` (ok) | $0.813 |

Server log for the whole run: 0 × "ignoring co-provided conversation_manager", 0 × `DeprecationWarning`, 0 × `drop_block`,
0 × Traceback. ¹ Chat-message `token_usage`; see finding 3 for what the two cost records leave out.

### 3.5 Root-cause location eval (3 cases)

| Case | 2.6.1 on #1 | 2.6.1 on #2 | 1.64, SDK preview | 1.64, final (1.45 preview) |
|---|---|---|---|---|
| bad-image | rank 1 · partial | rank 1 · partial | rank 1 · valid | rank 1 · **valid** |
| netpol-block | rank 1 · valid | rank 1 · valid | rank 1 · valid | rank 1 · **valid** |
| l2-payment-svc | rank 1 · valid | rank 1 · valid | rank 1 · partial (rerun: partial) | rank 1 · **valid** |

- Final build: AC@1 = AC@3 = MRR = 1.0, graph recall 3/3, **3/3 valid** — no case below its best 2.6.1 verdict.
- With the SDK's own preview, l2-payment-svc was `partial` twice: the rank-1 candidate (Deployment `payment-svc`) was right,
  the causal path was dropped by the fail-closed validator. Once the model wrote "namespace `agenticops` → payment-svc" —
  that namespace is the destination of the one edge fragment visible in the head of the 1.64 preview — and once
  "cluster → payment-svc" in one hop; the graph holds cluster → namespace `chaos-lab` → payment-svc. 2.6.1's bad-image
  `partial` (its report, finding 7) is the same mode.
- Tokens per case (only these RCAs, from `agent_logs`): final 167k / 152k / 135k, $1.00 / $0.78 / $0.73 (total $2.51);
  first round 193k / 191k / 195k, rerun 156k. The 2.6.1 batches came to about 253–258k per case (batch total / 13,
  including the batch's other calls) — within the plan's 1.2 × bound either way.
- Wall time per RCA: 121–150 s (2.6.1 in-cluster: 64–111 s) — local app vs in-cluster, not comparable.

## 4. Findings

| # | Finding | Caused by the upgrade? | Status |
|---|---|---|---|
| 1 | The offloader's preview changed to head + tail (§1 row 3) | Yes | Fixed in `3eb8883` (override + tests) |
| 2 | The RCA topology evidence is 20–23k tokens (184 edges, 152 neighbours of which 4 are abnormal) and is **always** offloaded to a 3,000-character preview — on either SDK version the model has to retrieve it to see the edges | No (since 2.6.1) | Open — feasibility report X1: code-computed `path_to_anchor` per candidate + a compact default pack (simulated 1.1–1.5k tokens) |
| 3 | Cost records: the chat route logs main's `AgentLog` row without cache tokens, so `/api/cost/summary` under-reports main chat cost (~93 % in §3.4: $0.15 vs $2.00); a chat message's own cost leaves out its sub-agents (the $0.51 sre call) | No | Open — feasibility report X2 |
| 4 | `list_cloud_accounts` reads `CloudAccount` attributes after its session closed → `DetachedInstanceError` (seen in a live chat on the dev box; the agent fell back to the enabled-account list) | No (`tools/account_tools.py` unchanged since `2610058`) | Open — tracker backlog |
| 5 | Opus 4.6 / Haiku 4.5 do not cache a ~4.4k-token prefix | No (model-side) | Documented in `CLAUDE.md` (`bedrock_cache_enabled` row) |
| 6 | Two hypothesis property tests fail under heavy concurrent load | No | Noted; they pass alone |

## 5. Deployment (dev box, `iac/deploy-sg`)

1. 2026-11-07 03:04 UTC — backup of the box's uncommitted state (`config/settings.yaml`, `agent-memory/`, `skills/`; 44 files),
   an online SQLite backup, `/etc/agenticops.env` and the unit: `/opt/agenticops-backups/pre-strands-164-20261107T030437Z/`.
2. `deploy.sh redeploy deploy/dev-strands-1.64` (= the upgrade + `ae62cd2`, so the editor account's read-only Settings view
   did not regress while PR #29 was still open). Restored the backup and added the two new settings to the box's
   `settings.yaml`; health OK; `strands-agents` 1.64.0; a live headless chat as the service user completed.
3. 03:25 UTC — after the merge, the box was moved onto `main` (`603046d`): the tree is identical, so only the branch pointer
   moved — no reset, no rebuild, no restart; the 40 local modifications are untouched.

Two redeploy pitfalls met and recorded for the next operator: a target branch that changes a file the box has modified
(`settings.yaml`) aborts at `git checkout` before anything changes — back it up, `git checkout -- <file>`, rerun, restore;
`deploy.sh`'s `mktemp /tmp/redeploy-XXXXX.sh` is literal on macOS, so a failed run leaves a file that fails the next run.

## 6. Rollback

Revert `603046d` (or redeploy the previous commit): `requirements.txt` puts 1.45.0 back. No schema or data change; the two
`context_offload_*` keys are ignored by the old code.

## 7. What comes next

The owner chose combination A of the feasibility report (2026-11-07), tracked as `next/*` in the progress tracker (`docs/progress/tracker.yaml` on `feat/progress-dashboard`, PR #27):
X2 cost accounting → S1 + S2 sub-agent `invocation_context` / `cancel_signal` → X1 topology evidence fit → M1–M3 memory
retrieval / ageing / ownership → K1 embedding provider (with the model provider layer), with X4 Strands Evals in parallel.
Each starts in Plan Mode.
