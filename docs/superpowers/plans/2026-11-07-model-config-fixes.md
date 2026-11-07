# Model configuration fixes — Opus 4.6 leftovers, Galaxy, cost table, model attribution, ACP (2026-11-07)

Branch `fix/model-config-consistency` off `origin/main` 603046d. Plan approved by the owner in Plan Mode on 2026-11-07;
four decisions below are the owner's. Push and deploy each need the owner's OK after the evidence.

## Why — measured on the dev box (agenticops.tinyboat.blog, `i-0935450a95f321942`)

Read-only audit 2026-11-07 (SSM probes, SQLite read-only, CloudTrail us-east-1 `LookupEvents` for the instance role):

- **Opus 4.6 was still called** although all seven agents ran 5.5 / GPT-6: `/etc/agenticops.env` set
  `AIOPS_BEDROCK_MODEL_ID=global.anthropic.claude-opus-4-6-v1` (from `iac/deploy-sg/variables.tf`; env beats
  settings.yaml), and four paths read that tier directly — skill generation / improvement (`skills/evolution.py`,
  30 Converse calls on 11-06 04:19–06:20), the reporter's `distill_case_study` (`tools/kb_tools._llm_distill`,
  20 InvokeModel calls 09:02–15:46, one-to-one with the five reporter runs), SOP generation (`pipeline/sop_upgrader`)
  and the legacy `analyze/rca.RCAEngine`.
- **Galaxy failed every hourly build from 11-06 07:00** (18 in a row): the box's Galaxy model, Opus 5.5, answers 400
  "`temperature` is deprecated for this model", and `galaxy/builder` sent `temperature: 0`. Claude 4.7+ rejects
  sampling parameters (Sonnet / Haiku 5.5: any non-default value); Signal Gate (and through it the RCA critic and the
  security advisor) and report translation sent it too.
- **Cost table**: no rows for claude-opus-5-5 / claude-sonnet-5-5 / gpt-6-astra (every call billed $0 since 10-10);
  Opus 4.6 / 4.8 / 5 were billed at 3× the Bedrock list price, Fable 5 / 5.1 at 1.5×, Haiku 4.5 at 0.8×.
- **agent_logs labelled runs with the configured model**: L1 fix plan #221 ran on the executor's smart model
  (Sonnet 4.6, 24 ConverseStream calls) and was logged and priced as Opus 5.5.
- **git defaults** still put RCA / Executor on Opus 4.6: a redeploy that did not restore the box's uncommitted
  settings.yaml would have moved them back.
- **ACP** (Claude Code via `claude-agent-acp`) ran its own `"opus"` (Opus 4.8), outside AgenticOps config.
- Also found: `terraform plan` in `iac/deploy-sg` on origin/main **replaces the instance** (the `most_recent` AMI lookup
  moved to a newer Ubuntu image) — its root disk holds the SQLite DB.

## Owner decisions

1. The four direct paths follow the **main** agent's model.
2. Committed defaults = what the box runs: main / rca / sre / executor Opus 5.5, scan / detect Sonnet 5.5, reporter
   GPT-6 Astra, executor L0/L1 smart model Sonnet 5.5, Galaxy Opus 5.5 (≈4× the Haiku 4.5 price, accepted).
3. Galaxy stays on Opus 5.5.
4. ACP's Claude Code follows Main.

## Changes

1. `agents/preamble.py` — `converse_text(model_id, prompt, *, max_tokens, temperature, read_timeout, total_attempts)`,
   the one single-shot Converse helper: `temperature` only where `accepts_temperature` (Claude before 4.7, and pre-4
   ids), reasoning blocks skipped, `ModelReplyEmpty` / `ModelReplyTruncated` (a `ModelReplyError`) instead of an
   empty or partial answer, botocore `total_max_attempts` (first try included). `converse_text_on_main(prompt)` =
   Main's model and output limit, 300 s, one retry. `_claude_version` reads a date after the major as no minor
   (`claude-sonnet-4-20250514` → (4, 0), previously (4, 20250514) — which also sent Sonnet 4 the adaptive-thinking
   shape). Callers import the helper inside the function (the agents package imports every agent → cycle).
2. Galaxy (`_call_bedrock`: 300 s, one retry), Signal Gate (`_call_bedrock`) and translation (`_call_model`: 300 s,
   one retry — `max_attempts: 2` used to mean 3 attempts) delegate to it; names and signatures unchanged.
3. Skill generation / improvement, `_llm_distill`, `sop_upgrader._call_llm` → `converse_text_on_main`; `BedrockLLM`
   picks Main's model in `__init__` (stored as `RCAResult.model_id`) and no longer builds a bare `boto3.client`.
4. `track_agent(..., model_id=None)` records and prices the model that ran; the executor passes its smart-model pick.
5. ACP: `ANTHROPIC_MODEL` = Main's model when on Bedrock and Main is a Claude model.
6. `config/settings.yaml` (the defaults above; tier keys written out; aliases `opus` / `sonnet` → 5.5, new
   `opus-5-5`, `sonnet-5-5`, `gpt-6-astra`; cost table from the AWS Price List — `AmazonBedrockFoundationModels`,
   us-east-1, global cross-region, standard tier, 5-minute cache write) and the same defaults in `config.py`;
   `MODEL_WINDOW_DEFAULTS` gains `claude-haiku-5-5` and `gpt-6`.
7. `iac/deploy-sg`: no `AIOPS_BEDROCK_MODEL_ID` in `user_data.sh` / `variables.tf` / `deploy.sh setup)`;
   `lifecycle { ignore_changes = [ami, user_data_base64] }` on the instance.
8. `pages/Settings.tsx` fallback presets → Opus 5.5 / Sonnet 5.5 / Haiku 4.5.
9. Docs: README.md + README_CN.md, CLAUDE.md, docs/WORKFLOW.md, docs/DESIGN.md.

## Reachable surfaces

| Surface | This change |
|---|---|
| CLI | indirect: `aiops skills` generation / improvement on Main; `/model opus` / `/model sonnet` → 5.5 |
| Web API | indirect: `/api/skills/*` generation / update, `POST /api/rag-pipeline/{id}` on Main; no new endpoint |
| Web UI | Settings fallback presets. Non-goal: a "follows Main" hint on the Agent Models card (provider-layer project) |
| Agent tool | `distill_case_study`, `skill_manage` / `improve_skill`, `enhanced_task` (ACP) follow Main |
| Schedule | indirect: `galaxy-auto-build` works again; scheduled reports' distillation and FullScan / DailyReport's RCAEngine on Main |
| Notification | non-goal |

## Non-goals

The cheap tier stays Haiku 4.5, and the three cheap-tier InvokeModel callers in `web/` (session titles,
`summary_service`, the frozen `memory_service`) are unchanged — they need a pre-4.7 Claude cheap tier (CLAUDE.md says
so). Small-budget calls (Signal Gate 500, critics) pointed at a model that thinks by default raise and fail open; not
handled further. No backfill of historical `agent_logs.cost_usd`. Direct calls are still not written to `agent_logs`.
The 12 chat sessions pinned to older models are the users' choice. `infra/cloud-deploy` (CFN, still
`_STRONG=opus-4-6`) is untouched: a UserData change interrupts its instance on the next stack update, and whether it is
prod is the owner's call. `aiops init` still writes `AIOPS_BEDROCK_MODEL_ID` into `.env`. No provider layer, no deploy.

## Verification

- Unit: `tests/test_converse_helper.py`, `tests/test_model_routing.py`, sync guards in
  `tests/test_claude5_bedrock_models.py`, `tests/test_galaxy_publish.py` (a reasoning-only reply fails the build and
  keeps the diff baseline), updated `test_sop_upgrader` / `test_kb_tools_extended` / `test_rca_engine` / `test_cost`.
- Full suite on the worktree venv (Strands 1.64 pins), frontend `tsc` + vitest + clean `/tmp` `npm ci && npm run build`,
  `terraform plan` on a copy of the live state.
- Live: `AIOPS_TESTS_ALLOW_AWS=1 pytest --run-integration tests/integration/test_converse_live.py tests/test_acp_integration.py`
  plus CloudTrail for the ACP model.

## Evidence (2026-11-07)

- **Full suite** (worktree venv with origin/main's pins, Strands 1.64; throwaway DB): baseline on origin/main 603046d
  6995 passed / 66 skipped / 1 failed; with this branch **7083 passed / 66 skipped / 1 failed** — the same one, the
  known DNS false failure `test_web_tools.py::TestWebFetchErrors::test_invalid_headers_json`. A
  `PytestUnhandledThreadExceptionWarning` from `test_report_access_api.py` (a translation thread reading a torn-down
  test DB) is pre-existing: it reproduced in 4 of 8 runs on unmodified origin/main.
- **Frontend**: clean `/tmp` copy, `npm ci` → `tsc --noEmit` 0 errors, `npm run build` OK; vitest 59 files / 712 tests
  (the two files that read the repo-root `tests/fixtures/*.json` run in place).
- **Terraform** (`plan -lock=false` on a copy of the live state): origin/main → `aws_instance.app must be replaced`
  (AMI ami-0ba6f2c4de657798c → ami-0403d346e3210afd6), 2 to add / 2 to destroy. This branch → no replacement; the only
  change left is removing the tag `QSConfigName-igp8l`, which SSM Quick Setup added outside Terraform (pre-existing).
- **Live Bedrock** (`tests/integration/test_converse_live.py`, 9/9 in 264 s, us-east-1): `converse_text` asking for
  temperature 0 → Opus 5.5, Sonnet 5.5, GPT-6 Astra (not sent) and Haiku 4.5 (sent) all answer `end_turn`; a
  40-resource Galaxy batch on Opus 5.5: 40.1 s, 7529 in / 5747 out tokens (≈ $0.15), 59 edges parsed; case
  distillation, SOP generation, skill generation and the legacy RCAEngine on Main (Opus 5.5) return valid output.
- **Negative control**: temperature 0 sent directly → Opus 5.5 and Sonnet 5.5 answer 400 "`temperature` is deprecated
  for this model"; Haiku 4.5 accepts it. CloudTrail does not record `temperature` (the box's pre-fix Galaxy calls show
  `{"maxTokens": 16384}` only), so the request shape rests on the unit tests and these live results.
- **ACP**: `tests/test_acp_integration.py` passed. With Main set to a model no other local session uses, Claude Code
  answered "Model global.anthropic.claude-sonnet-5-5 is restricted by your organization's settings. Using
  us.anthropic.claude-opus-5-5 instead." — it received `ANTHROPIC_MODEL`; the restriction is this workstation's
  organization policy. The dev box has no Claude Code managed policy and no `ANTHROPIC_MODEL` in its settings env:
  confirm there after the deploy (CloudTrail, the instance role, user agent claude-cli).

## Deploy (next step, owner's OK)

The new defaults equal the box's settings.yaml except the new keys, so the box needs no settings restore after a
redeploy (back it up anyway); agent-memory / skills as usual; delete `AIOPS_BEDROCK_MODEL_ID` from
`/etc/agenticops.env` once and restart. Live checks: the next Galaxy build completes; no opus-4-6 from the box in
CloudTrail; a reporter run distils on opus-5-5; agent_logs rows for 5.5 carry a cost.

## Deploy result (2026-11-07)

- Deployed `main` `f115743` (PR #35) to the dev box; the service restarted at 06:33:39 UTC. Before the deploy, the DB,
  env file, unit and local state were backed up to `/opt/agenticops-backups/pre-model-config-fix-20261107T062902Z/`.
  `/etc/agenticops.env` no longer has an `AIOPS_BEDROCK_MODEL_ID` line.
- Galaxy works again: build #1237 completed 07:00:04–07:02:08 UTC on `global.anthropic.claude-opus-5-5`
  (951,682 input / 13,394 output tokens, $4.07). It was the first build after the failing streak, so it re-enriched
  the backlog.
- CloudTrail, us-east-1, the instance role, 06:33:39–13:35 UTC: **0 calls to `opus-4-6`**. Calls seen by model:
  - Haiku 4.5: 81 Converse + 3 InvokeModel (the cheap tier);
  - Opus 5.5: 47 Converse + 15 ConverseStream;
  - GPT-6 Astra: 12 ConverseStream;
  - Titan embeddings: 26 InvokeModel;
  - plus Claude Code's own calls.
- `agent_logs` since the restart: Opus 5.5 4 runs, $0.1105; GPT-6 Astra 4 runs, $2.1542. No run is priced at $0.

### Follow-up: ACP needed Node 22 on the dev box

- **Symptom:** with `ANTHROPIC_MODEL` set to Opus 5.5, Claude Code 2.1.185 answered "does not support this model".
- **Cause:**
  - The box ran Node v20.20.2, installed by `iac/deploy-sg/user_data.sh` for the frontend build.
  - `@agentclientprotocol/claude-agent-acp` declares `engines.node >= 22` from 0.50.0 (2026-06-23).
  - On Node 20, npm therefore installs 0.49.0, which bundles claude-agent-sdk 0.3.185, and that Claude Code does not
    know the 5.x models. Moving the npx cache aside did not help: at 06:35 npx installed 0.49.0 again.
- **Fix (owner decision: keep ACP), applied at 13:30 UTC:**
  - nodesource 22.x, `nodejs` 22.23.4-1nodesource1 (npm 10.9.9).
  - The npx cache moved to `…/npx-d820eb7d96bc2600-claude-agent-acp-0.49.0-node20` in the backup folder.
  - The service was not restarted: ACP starts a new subprocess for every task.
- **Verified:**
  - **Frontend, locally:** a clean copy of origin/main on Node 22.23.4 passed `npm ci`, `npm run build` and vitest,
    61 files / 725 tests (the same counts on Node 25.4.0).
  - **Frontend, on the box:** the `git archive HEAD` (7893547) frontend built in a temp dir with
    `npm install && npm run build` on Node 22. The deployed `dist` was not touched.
  - **ACP smoke:** run as the service user (`systemd-run` with the unit's `EnvironmentFile` and the app venv),
    `ClaudeCodeBackend().run("Reply with exactly one word: pong")` returned `pong` in 21.2 s with no error.
    npx now holds claude-agent-acp 0.101.0 (claude-agent-sdk 0.3.318).
  - **CloudTrail:** at 13:33:15, `InvokeModelWithResponseStream` on `global.anthropic.claude-opus-5-5`, user agent
    `claude-cli/2.1.318`. Claude Code's own helper call went to `us.anthropic.claude-haiku-4-5-20251001-v1:0`.
  - **Service:** active the whole time; `/api/health` returned 200.
- **`iac/deploy-sg/user_data.sh` now installs Node 22.** Only a rebuilt box runs it, because `user_data_base64` is in
  `ignore_changes`. `terraform plan -lock=false` on a copy of the live state: 0 to add, 1 to change, 0 to destroy. The
  one change is the pre-existing `QSConfigName-igp8l` tag drift; there is no replacement.
- **Rollback:** reinstall Node 20 from nodesource 20 with
  `apt-get install -y --allow-downgrades nodejs=20.20.2-1nodesource1`, and put the npx cache back from the backup folder.
- **Not changed:**
  - The Docker image. Its runtime stage (`python:3.12-slim`) has no Node, so ACP cannot run in that deployment anyway;
    its frontend build stage stays on `node:20-alpine`.
  - `infra/cloud-deploy`.
  - The adapter is still unpinned: npx picks the newest version the installed Node supports. If a newer Main model is
    ever reported as unsupported, clear the npx cache.
