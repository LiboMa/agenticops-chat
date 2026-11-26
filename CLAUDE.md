# AgenticOps — Development Guide

## Project Overview

AgenticOps (`aiops`) — CLI + Web AI operations assistant with a multi-agent architecture (Strands SDK; models on AWS Bedrock or, since MVP-2.9.0 N35, any OpenAI- / Anthropic-compatible provider): `aiops chat` REPL, a React workspace with streaming chat, resource scanning, anomaly detection, RCA, fix plans, change management and reports across cloud accounts.

**Docs:** `docs/WORKFLOW.md` (diagrams + tutorials), `docs/README.md` (doc map: living docs vs. release snapshots), `docs/MVP-1.0.0-RELEASE.md` (feature report). What each version built, why, what was measured and what it leaves open is in `docs/MVP-<v>-RELEASE.md` + `docs/MVP-<v>-E2E-REPORT.md` (append-only); this file keeps the rules in force and where they live.

| Version | State | Release note / evidence |
|---|---|---|
| 2.2.0 / 2.2.1 | released | Signal Gate + RCA quality gate; effort policy — chaos E2E `docs/MVP-2.2.0-CHAOS-E2E-REPORT.md`, `docs/MVP-2.2.1-CHAOS-L2-E2E-REPORT.md` (faults `infra/eks-chaos-lab/chaos/`, `faults-l2/`) |
| 2.5.0 / 2.6.0 / 2.6.1 | released (`v2.6.1`) | Cloud Security Review; Change Management; graph facts, pull connectors, RCA location (`docs/MVP-2.6.1-LOCATION-EVAL-REPORT.md`) |
| 2.7.0 | released, tag `v2.7.0` | blue/white workspace + core trust (S1–S7); then on `main`: viewer accounts, Strands 1.64 (`docs/STRANDS-1.64-UPGRADE-REPORT.md`), chat attachments |
| 2.7.1 | branch `MVP-2.7.1`, pushed | E2E follow-ups, ChatGPT-style chat (`docs/MVP-2.7.1-CHAT-E2E-REPORT.md`), account edit = merge; change-aware track A1–A4 not started |
| 2.8.0 | branch `MVP-2.8.0`, S1–S2 accepted | workspace redesign; its S3–S8 were built on 2.9.0 (N20–N25) — never redo them on `MVP-2.8.0` |
| 2.9.0 | branch `MVP-2.9.0` (worktree `.worktrees/mvp-2.9.0`), pushed, awaiting the owner's acceptance | NewUI + the frame that hosts every page (N0–N27), read-only diagnosis / plan / detection (N28–N31), issue reset (N32–N34), model providers (N35); real run in the chaos-lab cluster: E2E «N27 第三步» |

The cluster image is built as for 2.7.0: `git archive` → the deploy S3 bucket → a presigned URL → the dev box over SSM (`bash -s`: the box's `sh` is dash) → ECR. The main checkout is shared with peer sessions: work in a worktree, commit explicit paths, tell peers before a service restart or a full-suite run.

## Protected Files

- **`RAW-Idea-latest-v3.md`** — Core idea document. **NEVER delete, move, or modify.** Local only: not in git
  (untracked 2026-11-06, listed in `.gitignore`) — keep the local copy; never re-add it to the repo.
- **`RAW-Creative-Idea.md`** — Core idea document. **NEVER delete, move, or modify.** Local only, as above.
- **`docs/use-cases/*`** — Hand-written use cases. Do not remove.
- **`docs/MVP-1.0.0-RELEASE.md`** — Important MV release files, always refer to this file when reading the project! **NEVER delete**

## Architecture

```
CLI (aiops chat)  ──┐
                    ├──► Main Agent (orchestrator) ──► Sub-Agents (scan, detect, rca, sre, executor, reporter)
Web Dashboard ──────┘         │
  (React + SSE)               ├──► AWS via STS AssumeRole
                              ├──► CloudWatch, CloudTrail, EKS, VPC, ELB, ...
                              ├──► SQLite / PostgreSQL metadata DB
                              ├──► Graph Engine (NetworkX) — SPOF, capacity, dependency, change sim
                              └──► Agent Skills (SKILL.md packages) — 16 domain skills
```

Each rule below names the code that enforces it and, where there is one, the test that pins it; «details: X» = the section of that version's release note.

**Models**
- **Agents-as-tools**: Main routes to 6 specialist sub-agents exposed as `@tool` functions; SRE's read-only Mode C (change review) is Main's `review_change`; no new agent since (MVP-2.6.0).
- **Which model runs**: an agent's own `agent_*_model_id` in `config/settings.yaml` wins; the tiers `bedrock_model_id` (mid), `bedrock_model_id_cheap`, `bedrock_model_id_strong` are fallbacks for an empty one (the one list of model settings and that one rule: `llm/registry.MODEL_SETTINGS`, `registry.fallback`). The committed yaml is what the dev box runs (main / rca / sre / executor Opus 5.5, scan / detect Sonnet 5.5, reporter GPT-6 Astra, `executor_simple_model_id` Sonnet 5.5, `galaxy_model_id` Opus 5.5). **No environment variable may pin a model** (`AIOPS_*` beats the yaml — the dev box's env file once pinned every tier path to Opus 4.6).
- **Direct (non-Strands) calls** go through `agents/preamble.converse_text` (temperature only where `accepts_temperature`; reasoning blocks skipped; an empty or `max_tokens`-cut reply raises `ModelReplyError`; read timeout / `total_max_attempts` per call). Skill generation, `distill_case_study`, SOPs and the legacy RCAEngine follow Main's model (`converse_text_on_main`); `track_agent(model_id=)` prices the model that ran. Import `converse_text` inside the function — the agents package imports every agent (`tests/test_converse_helper.py`). Only the frozen `memory_service` still sends the Anthropic-only body.
- **Model providers (MVP-2.9.0 N35)**: any model setting may be `<provider>::<model id>` (split at the first `::`; no `::`, or a value starting `arn:`, is a Bedrock id) to an OpenAI-compatible (LiteLLM, OpenRouter, vLLM, Ollama, LM Studio → `OpenAIModel`) or Anthropic-compatible (Anthropic, Sub2API → `AnthropicModel`) provider. `llm/factory.build_model` is the ONE builder (`tests/test_llm_call_sites.py`); a model that cannot be built raises `ModelProviderUnavailable` — never a fallback. Bedrock can be switched off (`PUT /api/model-providers/bedrock`): settings still naming it are `model_issues`, Claude Code on Bedrock is not offered (`agents/enhanced.bedrock_refusal`).
- **A provider model is its row, never its name** (review of 2.9.0): capabilities, window, price, `accepts_temperature` (not said → not sent), `prompt_cache` (else the platform's — `presets.PROMPT_CACHE_PRESETS`), the thinking shape (`reasoning`, below); a new row is a chat model until marked; nothing Bedrock-only is sent there. Details: «N35», «Standards 三条», «思考请求的形状 + 坏味道六条».
- **Bedrock families**: Opus 5 / Sonnet 5 / Fable 5.1 are inference-profile-only (`global.anthropic.*`); single-segment ids (`claude-opus-5`) must match the cost-key and picker regexes and `MODEL_WINDOW_DEFAULTS` (first substring wins, a family before its prefix — `tests/test_claude5_bedrock_models.py`), else $0 and the global window. Anthropic-only features (cache points, thinking) are gated per family in `agents/preamble.bedrock_model_kwargs`; an OpenAI family gets its own reasoning field capped at its top tier (`preamble._OPENAI_REASONING`: gpt-oss `reasoning_effort` ≤ high, GPT 5.4 / 5.5 `reasoning: {effort}` ≤ xhigh, GPT-5.6 / 6.x ≤ max — `reasoning_effort` fails those); an id not in the table gets no field.
- **Thinking shape**: Claude ≥ 4.6 takes `{"thinking":{"type":"adaptive"},"output_config":{"effort":…}}` and 400s on `budget_tokens`; < 4.6 the reverse; ≥ 4.7 is asked for `"display": "summarized"`, streamed as SSE `thinking` (never stored). `preamble.thinking_fields(…, adaptive=, summarized=)` builds either; on Bedrock `thinking_fields_for_budget(budget, max_tokens, model_id)` reads the id (`claude_reasoning`); a provider model's shape is its row's `reasoning` (`catalog.ANTHROPIC_REASONING`: `anthropic_adaptive_summarized` | `anthropic_adaptive` | `anthropic_budget`), never its name. The budget stays the internal currency (2048 low, 4096 medium, 8192 high, 12288 xhigh, above that max; `preamble.effort_tier`); non-Anthropic ids keep `budget_tokens`, which `bedrock_model_kwargs` turns into the family's field.
- **Model stream timeout**: `model_runtime.stream_read_timeout_seconds` (`agents/model_runtime`; `bedrock_model_kwargs` carries `boto_client_config` for every model — `tests/test_model_runtime.py` fails on a build site passing its own). `chat/stream_errors` words `timeout` / `max_tokens` with what to change.

**Pipeline, plans and runs**
- **Auto-fix pipeline**: HealthIssue → RCA → quality gate (evidence check → critic → confidence ≥ `rca_min_confidence_for_autofix`) → SRE → approve (L0/L1 auto) → execute → verify → resolve; low-confidence / refuted → `needs_review`. The RCA's root-cause location (`services/rca_location`, fail-closed) is observed only — gate and auto-fix never read it.
- **The auto-approval floor**: never a plan that follows a person's «no» (`plan_content.rejected_by_person`, rule `reviewer_requested_changes`), never a step the code cannot classify — an `unknown`-tier command or no command, in steps or rollback (`change_steps.unclassified_commands`, rule `unclassified_command`; fix plans in `pipeline_service.trigger_auto_approve`, standard changes in `change_service.evaluate_policy`).
- **«Read-only» means it cannot change anything**: `change_steps.command_tier` answers `readonly` only for ONE command that a shell would not split, redirect, substitute into or comment (`_shell_would_split`; `2>/dev/null` / `2>&1` change nothing), in its own case, and for a host command only when its first word is in `HOST_CANNOT_WRITE` (`HOST_CANNOT_WRITE` + `HOST_CAN_WRITE` partition `skills/security.SHELL_READONLY_COMMANDS`, pinned by a test).
- **A command is classified as its tool will RUN it** — split with `shlex` first (`aws_cli_tool._as_run`, `skills/security.classify_kubectl_command`); an unsplittable line, a line holding the DB scrub's placeholder, an AWS operation the tables miss (by its verb, `aws_cli_tool._aws_operation`) are `unknown` or higher. A «read» that saves a local file is `write` (`aws_cli_tool._SAVES_A_LOCAL_FILE`, `kubectl cluster-info dump --output-directory`); `kubectl rollout status|history` and `aws cloudformation describe-|list-` read. Details: «N26», «N27».
- **A fix plan only restores** (MVP-2.7.1): the SRE Mode A prompt scopes it to the last working state (improvements go to the summary as change-request follow-ups) and asks for EXACT COMMANDS — one runnable command per step, rollback line and check (cloud-neutral, pinned by a test); `save_fix_plan` refuses a rollback that takes the service down (`change_steps.outage_commands`; change plans are not checked).
- **Change Management (ITSM, MVP-2.6.0)**: ChangeRequest → SRE review (Mode C, read-only) → policy → approval → executor, with NO HealthIssue; one plan table, two origins (`fix_plans.plan_kind`, CHECK `ck_fix_plans_origin`); CR terminal state is written ONLY by `on_execution_result`; change tools and prompt are gated together by `change_management_enabled`. Approve / reject is a HUMAN action. Approving runs it (`change_service.approve_and_execute`); a run that cannot be queued leaves it `approved` + `execution_not_queued`, and `POST /api/changes/{id}/execute` / `/execute C<id>` / `execute_change` / «Retry execution» are only that retry.
- **Issue & Change logic (MVP-2.6.1)**: ONE writer of `HealthIssue.status` (`services/issue_state.transition_issue` — `tests/test_issue_status_writes.py`). A plan has `plan_version` + `content_hash`; approval binds the hash it was shown (stale → 409), the run recomputes it (drift → refused, withdrawn). A change request may carry `proposed_steps` + `external_ref` (code computes `steps_diff`); external systems open one via HMAC-signed `POST /api/changes/intake` as `webhook:<system>` (never approve / execute). Every run gets ONE verdict (`services/verification.evaluate`: `passed` / `failed` / `pending_acceptance` — a missing result is never a pass).
- **A plan's hash is of its content AS STORED** (N15): text / JSON columns are scrubbed of secrets at flush (`security/db_redaction`), so `plan_content.content_hash` hashes `redaction.redact_obj(...)` (idempotent — existing hashes unchanged, pinned); `models._repair_plan_hashes_2_9_0` and `plan_content.repair_stale_hash` restamp waiting plans.
- **A decision names what the person was shown** (2.9.0): approve takes the `content_hash`, `rca-feedback` the `rca_id` (409 `rca_changed`), `PUT /api/issues/{id}/status` the `expected_status` (409 `status_moved`; its `note` is the transition's reason, the only text quoted as a person's); whose words a rejection is: `plan_content.rejection_is_feedback` (`HUMAN_ACTORS`). `rca_agent` / `sre_agent` return an error string and log their failed end (`pipeline_events.log_agent_failed`). `tests/test_decision_binding.py`.

**Runs (MVP-2.9.0 round 2+)**
- **Every run has one record; a closed record stops the executor** (N8): the three starts (a queued ticket via `ExecutorService`, the approval thread `pipeline_service._run_auto_execute`, Main in a chat) all pass `agents/executor_agent.executor_agent()`, which opens a record when there is none (`services/run_tickets.open_ticket`: plan `approved → executing` CAS, issue → `fix_executing`, a `running` `fix_executions` row). `save_execution_result` closes it in place; `run_tickets.close_ticket` is the only other closer (cancel, `executor_total_timeout`, crash, the reconcile in the `finally`; first closer wins; it never disputes the diagnosis); `run_tickets.close_orphans()` at startup.
  `agents/run_guard.RunGuard` reads the record before every tool and model call: closed from outside → nothing more runs; closed by the run itself → it may still read, record and answer (`RunGuard.recorded`). Tools run one at a time (`SequentialToolExecutor`).
- **A run starts only while its issue waits for it** (N27): `issue_state.run_refusal` (the issue must be `fix_approved`; closed, reopened, re-diagnosed → withdraw and plan again) at `run_tickets.open_ticket`, the run route, CLI `/execute` before and after its confirmation and the queue claim (`run_tickets.claim_refusal`); `ui_actions` reasons `issue_closed` / `issue_moved`.
- **Stopping is not cancelling** (N9): `POST /api/fix-executions/{id}/stop` (a person; never an API key) records the stop with a CAS (`run_tickets.request_stop`) and leaves the record `running`. Then `RunGuard` lets through only reads, `run_guard.READS_OR_RECORDS` / `describe_*`, and a command word for word one of THIS plan's rollback lines (`change_steps.rollback_commands`, `exact_text`, judged as the tool runs it — `change_steps.tool_command`); a run that applied nothing (`RunGuard.applied == 0`) may not roll back. `RunGuard._say_stop` tells the agent once (`tests/test_run_stop_told.py`).
  The code guarantees what MAY run, not that the rollback ran: pages show `rollback_results`. A stopped run does not dispute the RCA; one that succeeded is `pending_acceptance`, never `passed`. Hook tests drive a real `strands.Agent` with a scripted model (`tests/test_run_guard.py::Scripted`, `tests/test_run_stop.py`) — never the preview's executor (its accounts are real).
- **«Tried» vs «applied»**: `RunGuard.tried` (`run_guard.tried_of`) = commands that could change something and are not the plan's own checks (`change_steps.check_commands`); `metadata_tools.nothing_tried` reads it — an `aborted` run that tried nothing does not dispute its diagnosis; a stop still decides on `applied`.
- **Steps on record while an agent works** (N10): `agents/step_recorder.StepRecorder` (a hook on `rca_agent`, `sre_agent` — never `sre_query` — and `executor_agent`, after `RunGuard`) writes `agent_steps`: one row per tool call (`ok` / `error` / `refused`), one per thing the model says, `look` read | act, an executor command's `plan_ref` (`step:3`, `rollback:1`, `pre:1`, `post:2`, `off`). Display only and fail-soft; display-redacted (`chat/tool_steps`); a secret-revealing kubectl result is not kept (`step_recorder.keeps_result`); a read-only account gets no `preview` / `summary` (`run_steps(withhold=)`). `GET /api/ui/activity/steps` (`services/agent_steps.run_steps`: never another run's steps).
- **Claims** (N11, `services/agent_runs`, in-process): `begin` (refused while a run is in time), `take` (the pipeline's next stage), `enter(agent, issue_id)` — what `rca_agent` / `sre_agent` call first; refused → `agent_runs.refusal()` before any model is built. Past `agent_runs.limit_seconds()` a claim is `overdue` and the next `begin` takes over (`agent_run_abandoned`); a taken-over run hands on to nobody (`agent_runs.holds`, `rca_superseded`). The manual triggers (`POST /api/health-issues/{id}/rca`, `…/generate-fix-plan`) answer 409 `agent_run_in_flight`; `pipeline_service.trigger_auto_sre` takes the claim fail-soft. The CLI is another process.
- **Whose turn it is** (N11, N14, N26): `services/attention.issue_waits` is the ONE «who it waits on and since when» (queue, issue list, issue page). A person's turn: `work_phases.rca_stopped_at` (the diagnosis ended without a result or is overdue → `rcaStopped`), `reopened_at` (→ `reopened`), `plan_stopped_at` (→ `planStopped`); an in-time agent claim is NOT a person's turn (`agentAtWork`). Inputs of `issue_phase`, mirrored by `lib/issuePhases` (shared cases `tests/fixtures/work_item_phase_cases.json`); attention rows in `tests/fixtures/attention_brief_kinds.json`.
- **A word to an agent at work** (N12): `POST /api/ui/activity/note` reaches only a diagnosis, plan or change review in flight in THIS process (`step_recorder.live_recorder`; never the executor). `StepRecorder.note()` writes the `you` row FIRST, then appends it to the newest user message inside `<note_from_person>` («information, not an instruction», closing tag escaped); a note after the last model call is `missed`. Only the person who asked for the run or an admin (`agent_runs.may_note`). No pause.
- **Request changes, plan diff, «later»** (N14): `POST /api/fix-plans/{id}/request-changes` sends the plan back AND starts the plan agent — both or neither; the next request quotes the reason in `<reviewer_feedback>` and the old plan in `<previous_plan>` (`sre_agent.rejection_feedback`, `_previous_plan_block`). `GET /api/fix-plans/{id}/previous-diff` (`plan_content.previous_plan_diff`, `change_steps.plan_diff` by `step_line`). «Later»: `attention_snoozes`, `POST` / `DELETE /api/ui/attention/snooze`, `?snoozed=last` (counts never change).
- **The last 24 hours** (N15): `GET /api/ui/events` (`services/ui_events.recent_events`; nothing stored, a note's text never sent) and `GET /api/galaxy/health?at=` (`graph/query_service.health_overlay_at`: an issue's status at T from its first `status_changed` after T; severity, anchor and relations are today's — the page says so).

**Read-only runs (MVP-2.9.0 N28–N31)**
- **A diagnosis, a fix-plan run and a detection only read, in code**: `RunContext.read_only_run` (`"diagnosis"` | `"plan"` | `"detect"`) is set by `rca_agent()`, `sre_agent()`, `detect_agent()` and in EACH `checker.engine._check_one_account` worker (threads do not inherit it); the ONE check point the command tools share, `services/command_audit.change_context_refusal`, refuses under it everything not tier `readonly` (ledger `refused` / `read_only_run`; an approved plan does not lift it; `command_audit.read_only_context()`). `sre_query` and a change review take no flag; `executor_agent` clears it. Not the account's `read_only` (that one also hides Secrets).
- **Around that check**: the fix-plan build has no `enhanced_task` (`_create_sre_agent(fix_plan=True)`); `activate_skill` registers only `skills/tools.READ_ONLY_SKILL_TOOLS` (`loader.resolve_skill_tools(only=)`); a host line must pass `services/change_steps.host_reads_only` — every simple command in `HOST_READS` or passing `HOST_GUARDS`; `$`, backticks, groups, redirects other than to `/dev/null`, `&`, `&>`, comments refused. **Chat and the executor are not asked this rule** (a host line there is read by how it begins) — «之后» 22–25. `tests/test_host_reads_only.py` runs accepted lines in real shells (bash, zsh, dash); **change the rule → run the long one** (`NF_HOST_FUZZ_LINES=5000`). `tests/test_read_only_run_tools.py` holds every tool of both agents to a class.
- **The approved plan reaches the executor whole** (N28): `config.WHOLE_RESULT_TOOLS` (`get_approved_fix_plan`) skip the context offloader via `should_offload` (`_offload_unless_whole`, must not raise). **kubectl namespace flag first** (N29): `classify_kubectl_command` takes one leading `-n X` / `--namespace[=]X` off (blocked patterns are searched on the whole line first); `kubectl_words` is the one split. `run_on_host` refuses an option-like host id (`skills/execution._host_refusal`).
- **Detection is bound to its account** (N32): `_check_one_account` also sets `bound_account_id`; a bound `get_managed_resources` lists only that account, cut by whole rows (`_bound_resource_list`); `_create_health_issue_impl` gives the Signal Gate the bound account. `poll_cloudtrail` queries per `HIGH_RISK_EVENTS` name (N33).
- **Clearing every issue**: `aiops delete issues --all [--dry-run] [--yes] [--reset-poll-cursors] [--move-knowledge] [--memory-dir DIR]` (`services/issue_purge.purge`, CLI only): one transaction after an online backup (`<data_dir>/backups/pre-delete-issues-<UTC>.db`); deletes every row keyed by an issue number (SQLite reuses ids) and all signals; keeps changes, audits, inventory, graph, reports; refuses without `--yes`, on non-SQLite and while `<data_dir>/.scheduler.lock` is held — and migrates (`init_db`) only after those checks and the backup; the cases / SOPs written from an issue go with their vectors and files (moved into `<backup>-knowledge/`, `MANIFEST.tsv`); `--move-knowledge` moves every KB file and the issue-derived agent memories. Details: «问题清零», «整条分支评审之后的修复».

**Trust, identity, process**
- **Core trust (MVP-2.7.0 S1)**: a post-check result counts only for the declared check its `check_id` names (`pc-1…pc-n` = position; `verification.bind_results`) — missing / duplicate / undeclared / id-less results or an approval drift are `pending_acceptance`, never `passed`; `save_execution_result` refuses an uncovering succeeded result once; `get_approved_fix_plan` is never truncated. Chat sessions have an owner: a signed-in user's new session is `private`, ownerless ones `workspace`; `services/chat_access` gates every chat route (invisible = 404; managing stays the owner's or an admin's — `can_manage`).
- **AgenticOps runs as ONE process** (`--workers 1`, replicas ≤ 1): chat / IM agents, claims, locks, runtime settings are per-process; the scheduler flock reports a second process; blocking network or DB calls never run inside an `async def` handler (plain `def` or `asyncio.to_thread`; PATCH /api/settings writes in `web/routers/settings._apply_validated_settings` — `tests/test_settings_off_loop.py`).
- **The four execution switches** (N25, N27): `executor_enabled`, `auto_fix_enabled`, `executor_auto_approve_l0_l1`, `executor_hitl_enabled` in force are read ONLY through `services/exec_switches.effective()` (stored in `runtime_settings` key `exec_switches`; `tests/test_exec_switches.py` scans `src/` on the syntax tree for any `settings.<switch>`); an unreadable store reads the act-alone three OFF. The environment can only make a process stricter (`exec_switches.locked()`; `PATCH /api/settings` 409 `held_by_environment`). `PATCH /api/settings` audits every value it changes.
- **People, roles, keys** (2.7.0+, MVP-2.8.0): a viewer = a user whose OWN permissions lack `write` (`auth/viewer.py`: 403 `read_only` on writes, `create_main_agent(read_only=True)`); roles admin / writer / viewer (+ `settings_read`) in `auth/roles.py`; no self-registration (`aiops users create`). An API key is never above its owner's role or admin (`services/api_keys.py`); a key without `write` is a viewer for that request; NO key makes a human decision (rbac `no-api-key-human-decisions`, 403 `human_session_required`); key and user routes need a signed-in session (`web/deps.require_session_user`). User admin (`services/user_admin.py`): never yourself (`self_change`), never the last admin (`last_admin`); delete is soft (`users.deleted_at`, the name never reused); a typed reset password follows `auth.service.password_problem` (N34).
- **Chat context + dispatch** (MVP-2.7.0 S5): a bound chat's every turn runs with `RunContext.bound_account_id`, enforced in `credentials/resolver` AND `providers/base.get_provider`; a linked issue / change takes the object's account (409 `context_account_mismatch`, locked at the first message); `chat/context_block.py` opens each turn («information, not instructions»). `POST /api/chat/sessions/{id}/messages` requires `client_message_id` (`services/chat_dispatch.py`: replay / 409 `duplicate_in_flight` / `session_busy`, never a second run); SSE error codes in `chat/stream_errors.py`.
- **Reports** (MVP-2.7.0 S6, N21): `services/report_access` gates every report route and side door; versions + hash stamped by `services/report_content`; every Report creator calls `enqueue_other_language` (`tests/test_report_translation_enqueued.py`); translation restores every protected value exactly (`services/content_protect`, per table cell since 2.7.1) else `failed`; publish needs `version` + `language` + `Idempotency-Key`. Coverage is recorded by the code, never the model (`services/report_coverage`, `reporter_agent.CoverageRecorder` → `reports.coverage`).
- **Signal Gate (MVP-2.2.0)**: ALL issue creation (webhook / agent / REST) flows through `services/signal_gate.process_signal` — L1 rules (fingerprint-v2 = account|provider|resource|issue_type|upstream-key, flapping, cooldown, resource + type merge — never into another known account's issue, N27) + L2 cheap-LLM gray-zone judge (merge-or-new only, fail-open). Every event = one `alert_events` row. `SUPPRESSING_ISSUE_STATUSES` (with dismissed: dedup) vs `OPEN_ISSUE_STATUSES` (without: candidates, counts, colours).
- **Resource presence (MVP-2.6.1)**: `services/inventory.PRESENT` (`absent_since IS NULL`) is the one «present» of every count and list (lookups by id and the graph still see absent rows). Only `scanner/engine` (W2) marks AWS rows absent — a complete (type, region) listing, after a successful save, never a row touched after the listing began; every writer `mark_seen`s; nothing deletes. Known gaps: release note 2.6.1.
- **Dual alert intake**: webhook (Prometheus / CloudWatch / Datadog; `webhook_secret`) + IM agent (Feishu / Slack). **FixPlan dedup**: one issue → one active plan (draft = update, locked = reject, terminal = allow new).

## 凭证安全铁律 (multi-account credential safety)

平台是多 AWS 账户。任何"业务/扫描/执行"路径必须遵守:
1. **不得裸用 `boto3.Session()` / `boto3.client()` 跑跨账户调用** —— 必须经 provider 层
   (`get_provider(account).resolve_credentials()` → `cli_tool()/sdk_session()`)取**目标账户**凭证。
   (例外:Bedrock 控制面 `get_bedrock_session()`、账户 test-connection、`list_available_profiles` 可读 `~/.aws`。)
2. **凭证解析失败 = 显式报错,绝不静默回退到 ambient(进程默认)凭证** —— 多账户下 ambient 只对应某一个账户,
   降级 = 在错误账户上执行。`environment` 源类型是唯一合法的"用本地默认链"声明(经 provider 层解析 + GetCallerIdentity
   校验,属解析成功),除此之外**没有任何 ambient 回退路径**。
3. **账户寻址执行(account-addressed),不再用隐式 ContextVar**:业务工具(`run_on_host`/`run_kubectl`/`run_aws_cli`、
   `describe_*`、network/graph(VPC·region 拓扑)/eks/cloudwatch/cloudtrail)都带显式 `account` 参数。解析顺序:显式 `account` → 按目标资源
   反查库存(`run_on_host` 按 instance-id、`run_kubectl` 按 cluster-name、graph VPC 工具按 vpc-id;同一 VPC 在多个账户库存里时报错列出账户名)→ 单账户默认(`resolve_default_account`,
   恰一个启用账户)→ fail-closed 列出账户名。子进程注入前先 strip 所有 `AWS_*`,再只注入解析出账户的 frozen 凭证
   (+ 需要时回注 region)。统一入口:`credentials/resolver.get_subprocess_env_for_account(account[, region])` ——
   `run_aws_cli/_readonly`、`run_on_host(ssm)`、`aws eks update-kubeconfig` 都经它取目标账户 env。**无任何"无上下文回退
   ambient"分支**(旧 `_active_account_var` ContextVar 已删:Strands 同步工具在 `asyncio.to_thread`+`copy_context` 里跑,
   工具内的 ContextVar 写入跨不出工具边界)。主机访问降级阶梯:`run_on_host(method="auto")` SSM → 分类失败 → SSH。
   kubectl 本身(`run_kubectl` 与 K8s 连接器)的 env 只来自 `credentials/kube.kubectl_env_for_cluster(account, cluster,
   region)`:上面那份目标账户 env,再加一个私有 kubeconfig —— 账户上登记的 `credentials.kubeconfigs[<cluster>]`(绝对路径),
   否则在同一 env 下用 `aws eks update-kubeconfig --kubeconfig` 生成
   `<data_dir>/kube/<账户主键>/<凭证指纹>/<region>/<cluster>.kubeconfig`(0600;指纹 = 凭证来源类型 + 去掉 `kubeconfigs`
   的凭证的 sha256 前 16 位 —— 账户被 PUT 改指向或主键被复用时,不会复用旧账户的文件);kubernetes 账户用它自己显式配置的
   `kubeconfig_path`(必填,不设默认)。`~/.kube/config` 与进程的 `KUBECONFIG` 从不被隐式使用、也不作回退,不切换
   current-context;失败抛 `KubeconfigError` / `AccountResolutionError`,没有回退(MVP-2.6.1)。
4. **缓存 key 必须含 account**:`credentials/resolver` 双写 `{provider}:{name}:{region}:{凭证指纹}` 与 `{account_id}:{region}:{凭证指纹}`(指纹 = `credential_fingerprint`:凭证来源类型 + 去掉 `kubeconfigs` 的凭证的 sha256 前 16 位,与私有 kubeconfig 路径同一函数 —— 账户凭证被改指向后 key 随之改变,不会复用旧会话;无需失效钩子,跨进程同样成立),
   禁止 region-only 取 session。会话缓存单一归属:`aws_tools._session_cache` 即 `providers/base._session_cache`(同一
   dict,线程安全);`SessionFactory._cache` 仅服务 Bedrock 控制面 + test-connection,另属一类。
5. **AssumeRole 会话自动刷新**:`providers/aws._build_assume_role_session` 用 botocore 原生
   `AssumeRoleCredentialFetcher` + `DeferredRefreshableCredentials`,长任务自动续期,勿退回手搓静态 Session+TTL。
6. **纵深校验**:`resolve_credentials` 在 `credentials.account_id` 存在时校验 `GetCallerIdentity().Account` 必须匹配,
   否则 fail-closed(防错号执行);未配置 `account_id` 则不校验(行为不变)。
7. **编辑账户 = 合并,不是替换**(2026-11-09:一次只改区域的编辑把 Global 账户存着的密钥对整个替换掉,34 个区域全部
   AccessDenied):`PUT /api/accounts/{id}` 与 agent 工具 `update_cloud_account` 都经 `CredentialStore.merge_update`
   (规则在 `credentials/store.merge_credentials`)。密钥字段(`is_sensitive_key`,与加密同一条规则)只被新的非空值替换,
   留空、不传、回传 `***REDACTED***` 或列表里的 `****xxxx` 掩码都保持不变;非密钥字段 `""` / `null` 删除;没传的字段保留
   (`account_id`、`kubeconfigs`:表单没有它们的输入框);删除已存密钥只有 `clear_secrets`(API 字段 / 工具参数 /
   表单「Remove the stored keys」)。`credential_source_type` 变了,就去掉旧方式自己的字段(assume_role 的 `role_arn` /
   `external_id`,profile 的 `profile_name`)——AWS provider 只看字段在不在,不看类型。密钥没变时保留原密文:凭证指纹
   (会话缓存 key、私有 kubeconfig 路径)按存储形态计算,重新加密会让它变。账户的增删改各写一条 `audit_logs`
   (`services/account_audit`,与改动同一事务;记非密钥字段、是否存有密钥、`details.secrets` =
   kept|replaced|added|removed|none、`via` = web|agent_tool|cli;从不记密钥值或密文):Web API、agent 工具,以及 CLI
   (`aiops create|update|delete account`、对话里的 `/account activate|deactivate|delete`、`aiops init` 重新登记——它也走
   `merge_update`)。

## Key Modules

### Backend (`src/agenticops/`)

| Module | Key Files | Purpose |
|--------|-----------|---------|
| `cli/` | `main.py`, `context.py`, `display.py`, `formatters.py`, `init_helpers.py` | CLI entry, chat loop, slash commands, init wizard. `/accept <I<id>\|C<id>> yes\|no <reason>` (a human verdict, as `cli:<user>`), `/execute`, `/change`; `aiops delete issues --all`, `aiops users`, `aiops providers list\|test`, `aiops connectors`, `aiops skills import` |
| `web/` | `app.py`, `session_manager.py`, `routers/*.py` | FastAPI, per-session agents, SSE chat. Routers: `changes`, `plans`, `audit`, `connectors`, `webhooks`, `ui` (bootstrap, preferences, attention, activity, events, nav-counts), `users`, `setup`, `model_providers`, `cost`, and since the split of `app.py` (review of 2.9.0) `health`, `resource_detail`, `settings`, `issue_agents`, `fix_plans`, `runs`, `rca_feedback` — each included where its code was, so the route order is unchanged; a router reaches the app's own objects (`_chat_sessions`, `_executor_service`, `_allowed_model_ids`) by importing them inside the function. List endpoints that page answer `{items, total, …}`. Settings → Messaging = `/api/messaging/*` (over channels.yaml + im-apps.yaml). Contracts: each version's release note |
| `agents/` | `main_agent.py`, `scan/detect/rca/sre/executor/reporter_agent.py`, `preamble.py`, `run_guard.py`, `step_recorder.py`, `model_runtime.py`, `enhanced.py` | 7 agents (1 router + 6 specialists); `preamble` = model kwargs, thinking shape, `converse_text`; `create_main_agent(read_only=, rich_output=)` |
| `tools/` | `metadata_tools.py`, `aws_cli_tool.py`, `change_tools.py` | DB tools, the account-addressed AWS CLI wrapper, Main's change tools. Facts the code knows are recorded by the code, not asked of the model: `save_rca_result` stores `RunContext.model_id`, `save_execution_result` measures `duration_ms` from `RunContext.run_started_at`. Main reads plans / runs via `get_plan` / `get_execution_result` |
| `services/` | `pipeline_service`, `rca_service`, `rca_quality`, `signal_gate`, `issue_state`, `plan_content`, `change_steps`, `verification`, `change_service`, `run_tickets`, `agent_runs`, `agent_steps`, `attention`, `work_phases`, `ui_actions`, `exec_switches`, `command_audit`, `inventory`, `readiness`, `issue_purge`, … | Pipeline + quality gate, the state writers and plan content (see Architecture). `work_phases` ports the pages' «who it waits on» input for input (shared fixtures with vitest); `ui_actions` gives `available_actions` side-effect free (`RbacPolicy.decide()` only); `attention` builds `GET /api/ui/attention` (~6 queries, no model or cloud call) |
| `auth/` | `actor.py`, `authz.py`, `service.py`, `viewer.py`, `roles.py`, `signatures.py` | `Actor` from the session (`user:` / `web:anonymous` / `cli:` / `agent:` / `im:` / `webhook:`); one `authz.check(actor, permission, subject=)` over `config/rbac.yaml`, shadow by default (`rbac_enforce`; `enforce: always` rules bite anyway; approvers are identity-bound). `signatures.py` = HMAC for both intakes. Viewers, roles, keys: Architecture |
| `llm/` | `refs`, `presets`, `models`, `registry`, `factory`, `direct`, `catalog`, `probe`, `embeddings`, `model_settings`, `errors` | Model providers (N35): `refs.parse_ref` / `is_ref`; tables `model_providers` (key + headers encrypted, out of the DB scrub) and `provider_models`; `registry` (merge-style update, 409 `in_use`, audited, never the key); `factory.build_model`; `direct.send` (the one chat-request builder) / `complete_text`; `catalog` (lists, refreshed at startup); `probe.test` / `test_draft` (a form tested before saving, nothing written); `embeddings` (KB vectors, `vectors_current`); `model_settings.problem()`; `errors.safe_error_text` (an SDK error as class + status — its text can quote the key; agent error answers and `track_agent` use it, `SdkErrorFilter` the log handlers). Every provider write drops cached chat agents |
| `cost.py` | — | Pure token → USD (`compute_cost(model, tokens)` never raises; a provider reference is priced from its `provider_models` row) |
| `models.py` | — | SQLAlchemy models + startup migrations (`init_db`: SQLite WAL, 30 s busy wait). `runtime_settings` = key → JSON changed at runtime (`chat_upload`, `model_runtime`, `exec_switches`, `model_providers`) |
| `config.py` | — | Pydantic-settings schema + YAML source (`AIOPS_` prefix); values live in `config/settings.yaml` |
| `chat/` | `preprocessor.py`, `upload_config.py`, `attachments/*`, `tool_steps.py`, `context_block.py`, `stream_errors.py`, `send_to.py`, `channel.py` | Message preprocessing (refs from the typed text only; another account's refs withheld), attachments, the work log's summaries + display-only redaction, `/send_to`, `/channel` |
| `graph/` | `engine.py`, `algorithms.py`, `relations.py`, `query_service.py`, `evidence.py`, `api.py`, `tools.py` | SPOF, capacity, dependency, change sim; `relations.PROPAGATION` (mirrored by NewUI, `tests/fixtures/relation_propagation.json`); `query_service` = bounded reads over the latest published build + health overlay; `evidence.py` = the RCA tool `get_topology_evidence` (no LLM, fail-soft); `GET /api/graph/focus` |
| `galaxy/` | `rules.py`, `builder.py`, `hashing.py`, `api.py` | Relationship graph (Experimental): L1 rules (`provenance=rule`) published before the L3 LLM phase (`provenance=llm`, fail-closed verification, advisory only — never drives execution); content-hash incremental; `build_graph(trigger, llm=False)` = rule-only refresh; every build re-anchors open issues |
| `skills/` | `loader.py`, `security.py`, `tools.py`, `execution.py`, `sources.py`, `sandbox.py`, `curator.py`, `review.py` | Skills (below); `security.py` classifies shell / kubectl lines; `execution.py` = `run_on_host` / `run_kubectl` |
| `connectors/` | `base.py`, `ingest.py`, `k8s.py`, `runner.py` | Pull connectors (2.6.1), read-only, no LLM: `ingest.py` is the only writer (absent only inside kinds listed complete); `k8s.py` = one `kubectl get <kind> -o json` per kind, `raw_data` cut to `K8S_RAW_DATA_CONTRACT` |
| `security/` | `collectors.py`, `scoring.py`, `reachability.py`, `advisor.py`, `db_redaction.py` | Security review (2.5.0, by account since N20): scoring is pure, a source that could not be read never scores as a pass; reachability `reachable` / `not_reachable` / `undetermined` (missing data → undetermined); the advisor is fail-closed |
| `integrations/` | `alert_processor.py`, `parsers.py` | Webhook parsers fill only what the source carries (`AlertPayload.hints`, `observed_at`, `alarm_name`) |
| `notify/`, `im/`, `kb/`, `memory/`, `pipeline/`, `storage/` | — | Notifications (YAML channels); Feishu WS bot; KB vectors (case search); file-based agent memory; RAG + patrol; local / S3 storage |
| `acp/` | `client.py`, `backends/*` | Optional ACP enhanced backend (`enhanced_task`; Claude Code / Kiro / Codex; off by default; offered only when `agents/enhanced.enhanced_available()` — Claude Code on Bedrock not while Bedrock is off). `claude-agent-acp` needs Node ≥ 22 |

### Frontend (`src/agenticops/web/frontend/src/`)

| Directory | Contents |
|-----------|----------|
| `pages/` | The classic pages: Chat, Cases (`/app/issues`, the «在等我» tab first), IssueDetail / ChangeDetail (the work-item template: `StatusLine` + phase cards + facts rail), PlansAndChanges + PlanDetail, Resources, Reports, Schedules, Security, Galaxy, Settings, Users, ApiKeys, Setup, Login, … `/app` = `ShellSwitch` (classic or new frame); `HomeResolver` picks the landing page |
| `newui/` | The new interface (below) — its own chunks, styles and words |
| `components/` | Shared blocks: `ui/ConfirmDialog`, `ui/ModalFrame`, `ui/QueryState` (loading / failed / empty only after a successful empty answer / ready), `ui/Switch`, `ui/IconButton`, `CommandPalette`; `layout/` (AppShell, NewFrame, Sidebar, TopBar, AccountScope); `workitem/`, `issue/`, `change/`, `plans/`, `chat/`, `settings/`, `galaxy/`, `graph/LocalGraph` |
| `hooks/` | TanStack Query hooks (`useAttention`, `useNavCounts`, `useHealthIssues`, `useModelProviders`, …), the chat stream hooks, `useCloseOnEscape` |
| `lib/` | Pure helpers with unit tests in `src/__tests__/` — the pages' view models (`issuePhases`, `changePhases`, `issueDetailModel`, …), lists (`caseQueue`, `resourceTable`, `sessionList`), chat (`chatStream`, `workSteps`, `richBlocks`), `shellChoice` / `shellRoutes`, `settingsPage`, `modelRefs`, … Components stay thin |
| `api/` | `client.ts` (`apiFetch` keeps a `code`), `types.ts` |

**NewUI (MVP-2.9.0, `newui/`, `/app/new/*`):** lenses **Decide** (the queue = `GET /api/ui/attention?sort=severity`; one brief per row kind — `decide/briefs/registry.ts`, kinds in `tests/fixtures/attention_brief_kinds.json`, `lib/briefKind`), **Story** (one item's whole record), **Live** (`GET /api/ui/activity`: at work / due / ended, each lane says how the server knows — `basis`), **World** (the latest graph build on a map: `lib/world/layout` deterministic, `lib/world/scene.scene` the ONE result every number is read from, `reconcile` checks drawn + off-screen = asked every second;
3D via `world/Sky3.ts` on `3d-force-graph` pinned at `1.80.2`, loaded only by `WorldData.load3d()`), **All items** (`/app/new/items`) and the command bar (`/` or Cmd / Ctrl + K; goes to places, plain text ends with «ask an agent» into a new conversation's draft — never sent by itself). A page says only what the record holds; a decision in NewUI is sent after the 5 s undo window (`newui/lib/pending`). Details: release note N0–N19.

**The frame hosts classic pages (N16–N19):** `lib/shellChoice` (localStorage `aiops-shell:<user id>`; a person stays in the frame they are in for the tab's life — `shellFor`), ONE layout route `/app` → `ShellSwitch` → `AppShell` or `NewFrame`; the classic page renders in `NewFrame`'s `<main class="cl-host">` OUTSIDE `.nf`. `src/bridge.css` restates the classic tokens under `html.nf-on` (`__tests__/newuiBridge.test.ts`: every variable, contrast ≥ 4.5) — a fix for a hosted page goes there first.
`lib/shellRoutes.ROUTE_KINDS` gives every route of `App.tsx` a kind (hosted | native | lens | outside; a missing row fails `shellRoutes.test.ts`); `nativeTarget` redirects inside the host; router state `CLASSIC_EXIT` stays on the classic page. `App.tsx` / `ShellSwitch` reach `@/newui` only through `import()` and nothing under `newui/` imports `@/pages/` (`__tests__/shellChunks.test.ts`).

**Frontend rules the tests enforce** (read them before changing the area):
- NewUI styles: every selector in `newui.css` starts with `.nf`, every animation and container name with `nf-` (`__tests__/newuiCss.test.ts`); class `grid` is `tgrid`. NewUI words live in `newui/locales/{zh,en}.json` (never `src/locales`), every key used and every used key present (`__tests__/newuiLocales.test.ts`).
- Folder names `lib` / `parts` / `build` / `var` / `dist` are swallowed by the Python `.gitignore` anywhere — `newui/lib/` has a negation, `__tests__/newuiTracked.test.ts` fails on any other. A full-width space at the edge of a JSX text line is trimmed — write `{"　"}` (`__tests__/newuiJsxSpaces.test.ts`).
- No English sentence is written into a classic page: `__tests__/bareEnglish.test.ts` reads every classic `.tsx` with the TypeScript parser; every sentence goes into `src/locales/{zh,en}.json` (same keys, `locales.test.ts`).
- A list endpoint that answers `{items, total}` is listed in `__tests__/listShapes.test.ts` `PAGED`; change every caller in the same commit.
- A classic page fills a template only with `lib/placeholders.fillPlaceholders` — never `.replace("{name}", …)` (`__tests__/noReplaceFill.test.ts`, TypeScript parser).
- Every overlay / side panel / dialog animates in with `animate-[slideInRight_0.2s_ease-out]` and closes on Escape (a Radix primitive, `ModalFrame`, or `hooks/useCloseOnEscape` — only the overlay opened last closes, `lib/escapeStack`; `__tests__/overlayEscape.test.ts`). References: `chat/ContextPanel.tsx`, `chat/SaveReportDialog.tsx`.
- Every hand-written `<table>` scrolls sideways or is `table-fixed w-full` (`__tests__/wideTables.test.ts`); `.report-content` wraps long words with `break-word` (`__tests__/longWords.test.ts`).
- NewUI's top bar is ONE row at every width and language: everything rigid except `.pulsebox` (a size container) — never make the right-hand group shrinkable (`__tests__/newuiTopBar.test.ts`). Look at a round's pages BETWEEN the breakpoints too (761–1100 px), not only at 1440 / 1024 / 390.
- Shell keys: ONE native listener on `window` (`newui/shell/NewShell.tsx`); `newui/lib/keys.keyIntent` never fires while an IME composes, in a field or under a dialog; a key a bar handles calls `e.nativeEvent.stopPropagation()`. Enter sends only via `lib/composerKeys.shouldSend` (never while composing, incl. keyCode 229).

**Workspace (MVP-2.7.0 S2–S6, MVP-2.8.0 S1–S2):** `GET /api/ui/bootstrap` (contract `workspace-ui-1`: user, auth, features that are built, `upload_policy`); `GET` / `PATCH /api/users/me/preferences` with `If-Match` (428 without, 412 stale); theme / font size in `localStorage`; Outfit bundled (no external font). One account scope in the top bar per user (`lib/accountScope`); issue notes are append-only (`services/issue_notes.py`, `note_added`). The sidebar groups and counts: `lib/navGroups`, `GET /api/ui/nav-counts` (a failed count shows no number, never 0). Light theme = blue / white tokens; dark mode keeps the green primary (owner's call).

**Chat (2.7.1, 2.8.0):** the SSE loop (`web/app.py` `_generate`) records each tool step (`tool_start` / `tool_input` / `tool_end` with offsets and times, on `chat_messages.tool_calls`); `lib/workSteps.splitWork` splits narration from the answer; `create_main_agent(rich_output=True)` (Web only) asks for statistics as a markdown table, a ```` ```chart ```` block only when asked, flows as ```` ```mermaid ```` (`tests/test_main_agent_rich_output.py`); `mermaid` is its own chunk (`securityLevel: "strict"`). The conversation list is the server's (`services/chat_session_listing.page_sessions`: pinned first, sorted before the cut).

**Chat attachments (2026-11-07):** `POST /api/chat/attachments` stages a file (411 / 413 / 415 / 507); a subprocess worker (`python -m agenticops.chat.attachments.worker`, 120 s, `RLIMIT_AS` set by the child on Linux, no `AWS_*` — containment, **not a sandbox**) writes model-independent artifacts; a send binds staged files with a CAS only for a new dispatch. What each model gets is `delivery.build_turn` via `preamble.media_capabilities` (Claude: images + documents natively; GPT-6: images; others text). Bedrock's media limits are constants in `attachments/limits`, never settings; `AttachmentBudgetHook` keeps every request (history too) inside them. Files on disk are **not** DB-redacted — readable only by who may see the session, kept until it is deleted.

### Skills (`skills/`) — autonomous, self-optimizing (cycle③ 2026-05-31)

16 domain skills: linux-admin, network-engineer, kubernetes-admin, database-admin, elasticsearch, monitoring, log-analysis, aws-compute, aws-storage, local-os-operator, web-research, distributed-tracing, notification-operator, document-analysis, security-engineer, excel-operator. Each: SKILL.md + references/*.md. Guide: `skills/ADDING_SKILLS.md`. Scan and detect agents also have `activate_skill` for dynamic tool registration (a diagnosis / plan / detection registers only `READ_ONLY_SKILL_TOOLS`).

- **3-tier disclosure**: system-prompt XML (budget pinned by `tests/test_prompt_budget.py`) → `activate_skill` (full body) → `read_skill_reference`. Skills XML is a frozen snapshot at agent build (writes take effect next session — protects the prompt cache).
- **`skill_manage` writes are drafts only** (`add` / `improve` / `merge` / `deprecate` / `restore` / `search`; `created_by=agent`; gated by `skills_autonomous_write`); `create_skill(publish=True)` publishes directly, and only after the user confirms; provenance frontmatter (`created_by` user = pinned / agent / imported, `skill_version`, `status`, `improved_from`; `normalize_skill_frontmatter` backfills); every improve path records to `improvement_store.py`.
- **Skills Curator** (`curator.py`, zero LLM): ages unused agent / imported drafts `active → stale (30d) → archived (60d)`; human skills pinned; never deletes (`skills/.archive/`, `restore_skill`); reactivate-on-use (`touch_skill_used`).
- **Security-gated promotion** (`review.py` + `security.py`): `promote_skill` runs `scan_skill_bundle(pkg_dir)` — the SKILL.md body plus every packaged `.sh` (line-based, `classify_shell_command`) and `.py` (`ast`-based, binding-resolved); a non-directory or unparseable package fails closed; the prior version is archived, `rollback_skill` restores it; names via `_safe_skill_name`. Known limit: `_py_prepass` is reachability- and scope-blind — a deterministic pre-filter in front of a human, not resistance to an obfuscator. API: `POST /api/skills/{name}/rollback|restore`.
- **Wide loading (MVP-2.5.0)**: `skills/sources.import_skills(uri, names=None)` — http(s) archive or `SKILL.md`, `git+https://…[@ref][#subdir]`, local zip / tar.gz / dir; every directory holding a `SKILL.md` is one package; fail-closed per package (kebab-case name, no links, no traversing entry, extension allowlist — a file with NO extension rejects the package, count / byte caps), staged then `os.replace`d; lands as an `imported` draft, never published, no packaged script ever run. A HUMAN action: CLI `aiops skills import <uri> [--name N]`, `POST /api/skills/import-source`, Web UI Skills → Import → «URL / Git repo». Agents get no import tool.
- **Script sandbox** (`skills/sandbox.py`, default OFF, `run_skill_script` on the executor only while on): a published skill's own `*.py` / `*.sh`, env from an EMPTY dict (`PATH` / `HOME` / `LANG`), network isolation via `unshare -n` / `sandbox-exec` or a refusal (`skills_sandbox_require_isolation`), interpreter by suffix, `shell=False`, one-shot `mkdtemp`, timeout kills the group; output via a `selectors` loop (never `select.select` — fd ≥ 1024 — nor `communicate()`), stored up to `skills_sandbox_max_output_bytes` per stream. **Filesystem writes are NOT confined**; a `setsid()`'d grandchild is not reaped; the Linux branch is unexercised on darwin.

### Agent Memory (`memory/`) — self-optimizing, file-based (cycle② 2026-05-31)

File-based markdown memory under `agent-memory/<agent>/*.md` (+ `shared/`) is the **single core** for agent behavioral memory. **Not a DB** (the old `AgentMemory`/`AgentMemoryFact` tables + `web/memory_service.py` are frozen).

- **Frontmatter**: `agent, type(feedback|pattern|preference|baseline|umbrella), status(active|stale|archived), confidence(1-5), source, created_by(user|agent), created_at, last_confirmed, last_used, absorbed_into/absorbed_from, resource_pattern`.
- **Curator** (`curator.py`, zero LLM): size cap `memory_max_active` (15) forces self-merge at write time; `active → stale (30d) → archived (60d)` by `last_used`; never deletes (`<agent>/.archive/`, `restore_memory`); runs at each main-agent build (`memory_curator_enabled`).
- **Agent autonomy**: `memory_manage` (add / patch / merge / remove / search), `created_by=agent`, gated by `memory_autonomous_write`.
- **Injection**: frozen snapshot at agent build (`build_system_prompt`, top-`memory_max_active` by confidence then recency; `touch_last_used`); writes take effect next session.
- **Concurrency-safe writes**: `_atomic_write_text` writes a per-(pid, thread, counter) tmp then `os.replace` — parallel builds touch the same `shared/` files.
- **Deferred (YAGNI)**: an episodic vector tier; only `kb/vector_store.py` (KB case search) exists.

### Infrastructure (`infra/`)

| Directory | Purpose |
|-----------|---------|
| `cloud-deploy/` | CloudFormation template + deploy script |
| `eks-lab/` | EKS lab: 10 scenario scripts, alert rules, monitoring |

### Config Files

| File | Purpose |
|------|---------|
| `config/channels.yaml` | Messaging channels — alert/chat routing (sole source of truth, gitignored; managed via Settings → Messaging) |
| `config/im-apps.yaml` | IM app credentials (gitignored) |
| `config/setup.json.example` | JSON config template for `aiops init --config` |

## Key Configuration (`config.py`)

All settings use the `AIOPS_` env prefix; defaults live in `config/settings.yaml`. Values an admin changes at runtime go to `runtime_settings` (the chat_upload pattern); limit-type settings move there one at a time (owner, 2026-11-08).

| Setting | Default | Description |
|---------|---------|-------------|
| `bedrock_model_id` / `_cheap` / `_strong` | Sonnet 5.5 / Haiku 4.5 / Opus 5.5 | Tier fallbacks for an agent with no own model; never pinned in the environment |
| `agent_{name}_model_id` / `_max_tokens` / `_thinking_budget` | `""` / `0` / `0` | Per-agent model (a Bedrock id or `<provider>::<model>`), max tokens (0 = `bedrock_max_tokens`), thinking base budget (yaml: rca 4096) |
| `bedrock_max_tokens` / `bedrock_region` | `16384` / `us-east-1` | Max output tokens; Bedrock region |
| `embedding_model_ref` | `""` | The KB's vector model (`<provider>::<model>`); empty = Titan on Bedrock (N35) |
| `model_runtime` | `{stream_read_timeout_seconds: 600}` | How long a model stream may send nothing (60–3600 s); admin override in Settings → Model connection |
| `bedrock_cache_enabled` | `true` | Prompt caching on Anthropic models: message cache points + tool definitions (`CacheConfig(strategy="auto", tools_ttl=True, system_prompt_ttl=False)`) |
| `strands_context_manager_auto` | `true` | One `ContextOffloader` plugin on every agent build (`config.get_agent_context_plugins`); never pass `context_manager` — `tests/test_strands_parity.py` |
| `context_offload_max_result_tokens` / `_preview_tokens` | `1500` / `750` | Offloader thresholds; preview = the first 750 × 4 chars (`_slice_preview`); `WHOLE_RESULT_TOOLS` are never offloaded |
| `thinking_escalation_step` / `thinking_budget_min` | `4096` / `1024` | +1 tier per escalation (RCA: critical, rerun); below the minimum (or ≥ max_tokens) thinking is off |
| `thinking_effort_presets` | `{off:0, low:2048, standard:4096, high:8192, xhigh:12288, deep:12288, max:24576}` | Per-session chat effort (`chat_sessions.effort`, NULL = Auto); quote the keys in YAML — bare `off` is false |
| `log_dir` | `<project>/logs` | Where `backend.log` / `frontend.log` go; `tests/conftest.py` points it at a temp dir (a test must never touch the service's logs) |
| `database_url` | `sqlite:///...agenticops.db` | SQLite runs in WAL (local disk only; back up with the online API — the `.db` alone is not a full copy), 30 s busy wait |
| `event_loop_executor_threads` | `64` | The event loop's default pool, shared with every model stream and sync tool of the one process |
| `deployment_profile` / `scan_focus` | `local` / `all` | local or cloud; resource categories to scan |
| `api_auth_enabled` / `rbac_enforce` / `rbac_file` | `false` / `false` / `config/rbac.yaml` | Sign-in; RBAC enforce (false = shadow: denials audited as `authz.denied_shadow`); the permission matrix |
| `auto_rca_enabled` | `true` | Auto-trigger RCA |
| `auto_fix_enabled`, `executor_enabled`, `executor_auto_approve_l0_l1` | `true` | Defaults only — in force = `services/exec_switches.effective()`; an `AIOPS_*=false` in the real environment holds them off |
| `executor_hitl_enabled` | `false` | Strands `HumanInTheLoop` on the executor; no surface gives its confirmation yet — on, a run stops at its first mutating step and fails |
| `executor_total_timeout` / `executor_auto_resolve` | `1800` / `true` | Watchdog for every run (s); a passed fix resolves its issue (false = `fix_executed`) |
| `rca_min_confidence_for_autofix` | `0.6` | Below → `needs_review`, no auto-SRE; read-only in `GET /api/settings` (PATCH 400) |
| `rca_critic_enabled` / `rca_timeout_seconds` / `rca_max_iterations` | `true` / `900` / `40` | Critic after each RCA (refuted → ×0.5); RCA watchdog; event-loop turns |
| `rca_incident_memory_enabled` / `_max` | `true` / `3` | Prior same-fingerprint RCA conclusions in the RCA prompt |
| `rca_topology_context_enabled` | `true` | The RCA tool `get_topology_evidence` and its prompt section, together |
| `rca_topology_window_before_minutes` / `_after_minutes` | `30` / `10` | Window around the onset for observed blast radius and the evidence pack |
| `rca_k8s_recollect_min_age_seconds` / `_timeout_seconds` | `120` / `60` | Re-collect a K8s anchor's cluster first when older than this or than the onset; failure → evidence `stale` |
| `agent_steps_retention_days` | `30` | `agent_steps` rows kept (0 = forever) |
| `attention_long_wait_hours` / `attention_snooze_minutes` | `24` / `60` | «Waiting long» view; how long «later» keeps an item at the end of its group |
| `notifications_enabled` / `notifications_consolidated` | `true` / `true` | Auto-notifications; only the final report during Scan / Detect / RCA (false for debugging) |
| `signal_gate_enabled` / `signal_gate_llm_enabled` / `signal_gate_confidence_min` | `true` / `true` / `0.7` | All issue creation through the gate; the L2 gray-zone judge; its minimum confidence to merge |
| `noise_flap_threshold` / `noise_flap_window_minutes` | `3` / `30` | Same-fingerprint signals in the window after which further ones are noise |
| `signal_retention_days` | `30` | `alert_events` kept; pruned once per process-day in 500-row transactions, never inside the gate's transaction |
| `resource_scan_interval_minutes` | `60` | The `resource-scan` schedule (seeded once, never overwritten); a run with an account whose credentials failed is `failed` |
| `patrol_graph_checks_enabled` | `true` | SPOF + capacity checks in the health patrol (their issues have auto-RCA off) |
| `k8s_connector_enabled` / `k8s_discovery_interval_minutes` | `true` / `10` | The K8s pull connector and its `k8s-discovery` schedule (seeded once) |
| `k8s_kubeconfig_max_age_seconds` / `k8s_connector_max_output_bytes` | `3600` / `20000000` | Reuse a private kubeconfig below this age; byte cap per `kubectl get <kind>` (above = partial) |
| `galaxy_enabled` / `galaxy_build_interval_minutes` / `galaxy_model_id` | `true` / `60` / `""` | Galaxy builds and cadence; its LLM (empty = cheap tier; the yaml sets Opus 5.5) |
| `galaxy_batch_size` / `galaxy_confidence_min` / `galaxy_drop_rate_alert` | `40` / `0.5` / `0.05` | LLM batch size; minimum edge confidence; drop rate that logs a WARNING |
| `galaxy_llm_exclude_types` / `galaxy_builds_keep` / `galaxy_expand_node_cap` | leaf types + `K8s_*` / `24` / `200` | Types the LLM skips (K8s relations are rule-derived); build rows kept (plus the running, latest LLM and published); `/expand` cap |
| `identity_alarm_name_patterns` / `identity_type_families` | EKS alarm regex / `{EKS: [EKS, EKS_Cluster]}` | Alarm name → cluster / namespace for anchoring; types that are one resource when account + region + short id match |
| `graph_query_node_cap` / `_edge_cap` / `graph_query_max_depth` | `200` / `500` / `2` | GraphQueryService caps (abnormal nodes kept first); neighborhood depth (`potential_impact` fixed at 3) |
| `policy_graph_impact_enforce` | `false` | Policy blast radius from the graph; false = shadow (`shadow_blast_radius`, rules never see it); read-only in `GET /api/settings` |
| `change_management_enabled` / `change_auto_approve_standard` | `true` / `false` | The ITSM change flow (tools, API, CLI, pages); a policy `auto_approve` may approve without a human only when this agrees |
| `change_review_timeout_seconds` | `600` | SRE change-review watchdog (timeout → back to `draft`, `review_failed`) |
| `webhook_secret` / `change_intake_secret` | `''` (env only) | Alert-webhook token or HMAC (empty = unchecked, startup WARNING); change-intake HMAC (empty = endpoint 404) |
| `intake_signature_window_seconds` | `300` | Accepted `X-AIOps-Timestamp` skew for both signed intakes |
| `audit_retention_days` / `command_audit_enabled` | `365` / `true` | `audit_logs` + `command_audits` kept (0 = forever); the write-tier command ledger |
| `security_review_enabled` / `security_poll_interval_minutes` / `security_posture_interval_minutes` | `true` / `10` / `60` | Security review; fast poll; slow posture snapshot |
| `security_reachability_nacl_enabled` / `security_advisor_enabled` / `security_advisor_critic_enabled` | `true` | NACLs in reachability (missing → undetermined); the advisor; its critic (refuted → dropped) |
| `security_snapshot_retention_days` / `security_model_id` | `90` / `""` | Snapshots kept; the advisor's model (empty = cheap tier) |
| `report_translation_model_id` | `""` | zh / en report translation (empty = cheap tier) |
| `chat_upload` | yaml block (`max_files: 20`, `max_file_mb: 50`, …) | Attachment limits; admin override in Settings → Chat attachments; Bedrock's media limits are constants |
| `chat_attachments_dir` | `""` | Attachment files; empty = `<data_dir>/chat_attachments` (yaml only) |
| `feishu_ws_enabled` | `false` | Feishu WebSocket long connection |
| `skills_enabled` / `skills_autonomous_write` / `skills_curator_enabled` | `true` | Skills; agent drafts via `skill_manage`; the Curator |
| `skills_draft_stale_days` / `skills_draft_archive_days` / `skills_security_scan_on_promote` | `30` / `60` / `true` | Draft ageing; the bundle scan before publishing |
| `skills_import_enabled` / `_max_package_bytes` / `_max_files` / `_timeout_seconds` | `true` / `2097152` / `50` / `60` | Importing from URL / git / zip and its caps |
| `skills_import_allowed_extensions` | `[.md,.py,.sh,.txt,.json,.yaml,.yml,.csv]` | Allowlist; a file with NO extension rejects the package |
| `skills_sandbox_enabled` / `_timeout_seconds` / `_max_output_bytes` | `false` / `60` / `20000` | The script sandbox (and `run_skill_script`); its timeout; output cap per stream in BYTES |
| `skills_sandbox_require_isolation` / `skills_sandbox_interpreters` | `true` / `{.py: python, .sh: /bin/bash}` | Refuse without `unshare -n` / `sandbox-exec`; suffix → interpreter |
| `memory_max_active` / `memory_stale_days` / `memory_archive_days` | `15` / `30` / `60` | Agent memory cap and ageing (`memory_autonomous_write`, `memory_curator_enabled`) |
| `acp_enhanced_enabled` / `acp_enhanced_backend` / `acp_use_bedrock` | `false` / `claude-code` / `true` | The ACP enhanced backend (`CLAUDE_CODE_USE_BEDROCK=1`) |
| `acp_timeout_seconds` / `acp_auto_approve_permissions` | `300` / `true` | Per-turn timeout; allow_once on the backend's permission requests |
| `acp_kiro_command` / `acp_kiro_args`, `acp_codex_command` / `acp_codex_args` | `kiro-cli` / `["acp","--trust-all-tools"]`, `npx` / `["-y","@zed-industries/codex-acp"]` | Kiro and Codex launch (Codex needs `OPENAI_API_KEY`) |

## HealthIssue State Machine

10 states: `open` → `investigating` → `acknowledged` → `root_cause_identified` → `fix_planned` → `fix_approved` → `fix_executing` → `fix_executed` → `resolved`, plus `dismissed` (any non-terminal state → `dismissed`; `dismissed → open` reopens). Transitions enforced by `validate_status_transition()` (409 on invalid).

**One write path (MVP-2.6.1)**: every status write goes through `services/issue_state.transition_issue(session, id, new, actor=, reason=, expected=, note=)` — `note` (MVP-2.9.0) is the text a PERSON typed, stored on the event's detail and the only thing a page quotes under that person's name; the edge is validated, the row moves with `UPDATE … WHERE status=:expected` (0 rows → `IssueStatusConflict`, 409), and a `status_changed` timeline event is added in the caller's transaction. `tests/test_issue_status_writes.py` scans `src/` and fails on any other write.
Back-edges to `root_cause_identified`: from `fix_approved` (the plan changed after approval, the run never started), `fix_executing` (the run failed) and `fix_executed` (verification failed or acceptance was rejected) — the issue can get a new fix plan. The agent tool `update_health_issue_status` moves an issue neither into nor out of `fix_approved` / `fix_executing` / `fix_executed`: the plan's approval, its run and the human acceptance move those. `dismissed` suppresses repeats of its fingerprint but is not open (see `signal_gate` above); `dismissed → open` reopens.

## Change / Plan State Machines (MVP-2.6.0)

**ChangeRequest** (12 states), enforced by `validate_change_transition()` (409 on invalid):
`draft → under_review → {planned | needs_clarification | rejected}`; `planned → approved`; `approved → executing`;
`executing → {completed | failed | rolled_back | needs_review}`; `needs_review → {completed | failed}` (human verdict —
a redo is a NEW change request). Terminal: `completed`/`failed`/`rolled_back`/`rejected`/`cancelled`. `under_review → draft`
is the watchdog rollback, keyed by `review_attempt` (late rollbacks are 0-row no-ops).

**FixPlan** (both kinds), enforced by `validate_plan_transition()`:
`draft → {pending_approval | approved | rejected}`; `pending_approval → {approved | rejected}`;
`approved → {executing | rejected}` (reject-from-approved = withdrawn); `executing → {executed | failed}`. Replaces the
old 6 direct status assignments; `FIXPLAN_*_STATUSES` dedup sets unchanged.

ChangeRequest moves (`change_service._claim`), HealthIssue moves (MVP-2.6.1: `services/issue_state.transition_issue`,
the single writer) and a fix run's acceptance (`fix_executions.verification_status = pending_acceptance`; a change's
acceptance rides on its request's claim) use `UPDATE … WHERE id=:id AND status=:expected` + a rowcount check (409 on
0 rows) to block a concurrent double-approve / double-execute. FixPlan status writes too (MVP-2.7.0 S3): `transition_plan`
validates the edge, then moves a persistent plan with `UPDATE … WHERE status=<the status it read>` — 0 rows raises
`PlanStatusConflict` (an `InvalidStatusTransition`, so every caller's 409 applies); a non-persistent object is assigned.

**Plan content + verdict (MVP-2.6.1)**: a content write restamps `content_hash`, and a changed hash bumps `plan_version`.
Approval records `approved_hash` / `approved_version` and must quote the hash the approver saw; `get_approved_fix_plan`
recomputes it and refuses a drifted plan (the run is aborted with "content changed after approval"). After a run,
`verification.evaluate` gives ONE verdict, stored on `fix_executions.verification_status`: `passed` (succeeded and every
declared post-check passed), `failed` (the run did not succeed, or a post-check failed — not the same as rolled back) or
`pending_acceptance` (no post-checks, a declared check with no result or more than one, a result for an undeclared
check or without a `check_id`, an approval drift, a warning, a step without a success report). MVP-2.7.0: results
bind one to one by `check_id` (`verification.bind_results`; a declared check's id is its position `pc-n`), never by
count or position. `post_checks` are read only through `verification.declared_checks` (the same `decode_legacy_json`
FixPlanResponse uses, so page and verdict count the same checks); results and step results go through
`verification.as_results` (a list is kept, a dict is one entry, a JSON string is parsed first, anything else is no
entries — a result of the wrong shape is missing, never a pass). The business status, the
execution status and the verdict are three separate facts. A fix: `passed` → `resolved` (or `fix_executed` with
`executor_auto_resolve=false`), `pending_acceptance` → `fix_executed`, `failed` → `root_cause_identified` + the RCA
disputed. `save_execution_result` moves the issue only when it is in `fix_approved`, `fix_executing` or
`fix_executed`, with a CAS on the status it read: a stale run leaves an issue that has moved off its fix where it is
— no hop and no RCA dispute. A change: `passed` → `completed`, a succeeded run otherwise → `needs_review`
with `needs_review_reason`. A pending verdict notifies `execution_pending_acceptance`; a human accepts or rejects it
(`POST /api/fix-executions/{id}/accept`, CLI `/accept`), authorized as the plan kind's approval (`webhook:*` never) —
a change's acceptance goes through `resolve_review`, still the only human writer of its terminal state. An empty
approval hash is the same 409 "reload" (a plan stored without one is stamped by it). No path approves the plan of a
`resolved` / `dismissed` issue (reopen it first), and no path RUNS an approved plan unless its issue is waiting for that
run (MVP-2.9.0 N27: `issue_state.run_refusal` — `fix_approved`; closed, reopened or moved → withdraw and plan again). `mark_fix_failed` takes `save_execution_result`'s origin gate plus an
ownership check (a run of another issue, or of a change, is refused), and refuses a run that succeeded unless its
verification failed. Only an issue's latest run can be accepted (an older one is 409). The Web/API fix and change
approve routes and acceptance check 404 → authz 403 → state 409 → hash 409; CLI `/approve` and the agent tool
`approve_fix_plan` still check the state before authz.

## Build & Run

```bash
# Syntax check
python3 -m py_compile src/agenticops/web/app.py
python3 -m py_compile src/agenticops/models.py
python3 -m py_compile src/agenticops/config.py

# Frontend
cd src/agenticops/web/frontend && npx tsc --noEmit && npm run build

# Run
aiops chat                          # interactive REPL
aiops chat "check health"           # headless
uvicorn agenticops.web.app:app --reload --port 8000  # API server (deployed: exactly ONE process, --workers 1)

# Init
aiops init --yes                    # non-interactive local
aiops init --config setup.json      # zero-prompt from JSON
aiops quickstart --yes              # full auto: init + start

# Tests
python -m pytest tests/ -v
python -m pytest tests/test_fix_plan_consolidation.py -v
```

## Git & GitHub

- Repo: https://github.com/LiboMa/agenticops-chat (private)
- **Always use `git push --no-verify`** to bypass Code Defender hooks
- **Always Test the code** before commit it


## WHEN Code Development, vibe coding
1.有问题向我提问 
2.不要生成无关代码. 
3.从最简单的方案入手 
4.写第一行代码前，把模糊指令转化为可量化的标准
5.不碰与需求无关的代码，每行改动都对应明确的要求. 
6. Each Time, 请从Plan Mode 开始
7. each time when after finsh the development phase, auto-update the docs/ workflows, and readme or related documentation, keep it updated.
   **双语 README 同步**：`README.md` 与 `README_CN.md` 是同一份文档的两种语言——任何一处的改动必须在**同一提交内**
   同步到另一处（段落一一对应、表格行一一对应、链接相同）。文档地图与"living / 历史快照"划分见 `docs/README.md`。
8. use .venv as default python env, source it as needed.
9. **可达面必须逐行列清**：新增任何用户可达能力时，spec/plan 里必须把 CLI / Web API /
   **Web UI**(`web/frontend/src/pages/*.tsx`) / Agent tool / Schedule / Notification
   六个面逐行列出，每行显式写「做」或「非目标」——留空视为遗漏，不是默认不做。
   **`Web API` 与 `Web UI` 永远是两行**，写成一个「Web」就是这条规则要防的那个 bug
   (2026-09-07 技能广域加载: spec §7 三行 CLI/Web/Agent 看着完备,「Web」实际只指端点,
   结果 26 个 commit 前端零改动,而 `pages/Skills.tsx` 早有一个只收文件上传的 Import 按钮)。
   任何点名了 actor 的决定(「人类动作」/「只给 agent」),下一个问题必须是「该 actor 从哪个面到达它」。
   汇报完成前自查一次:新增 `/api/` 端点而 `web/frontend/` 零改动时,要么指出对应 UI 改动,
   要么明确声明「无 UI,理由是 X」,不许沉默通过(提示,非硬闸门——agent/调度专用端点无 UI 是对的)。
