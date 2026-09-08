# AgenticOps — Development Guide

## Project Overview

AgenticOps (`aiops`) — CLI + Web AI operations assistant with multi-agent architecture (Strands SDK on AWS Bedrock). Provides `aiops chat` interactive REPL, React web dashboard with streaming chat, resource scanning, anomaly detection, fix planning, and reporting across AWS accounts.

**User-facing docs:** `docs/WORKFLOW.md` (Mermaid diagrams + tutorials), `docs/MVP-1.0.0-RELEASE.md` (feature report), `docs/MVP-2.2.0-RELEASE.md` (Signal Gate noise reduction + RCA quality quintet), `docs/MVP-2.2.1-RELEASE.md` (effort/thinking policy — backend escalation + per-session chat override), `docs/MVP-2.5.0-RELEASE.md` (latest: Cloud Security Review — dual-frequency posture + CIS scoring + NACL-aware three-state reachability + evidence-grounded advisor; E2E in `docs/MVP-2.5.0-E2E-REPORT.md`)

**Live E2E evidence:** `docs/MVP-2.2.0-CHAOS-E2E-REPORT.md` (L1 chaos: image/config/network on a real EKS cluster), `docs/MVP-2.2.1-CHAOS-L2-E2E-REPORT.md` (L2 chaos: production-named faults; Signal Gate dedup + effort escalation validated live). Fault scripts: `infra/eks-chaos-lab/chaos/` (L1), `infra/eks-chaos-lab/faults-l2/` (L2).

## Protected Files

- **`RAW-Idea-latest-v3.md`** — Core idea document. **NEVER delete, move, or modify.**
- **`RAW-Creative-Idea.md`** — Core idea document. **NEVER delete, move, or modify.**
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
                              └──► Agent Skills (SKILL.md packages) — 15 domain skills
```

- **Agents-as-tools**: Main agent routes to 6 specialist sub-agents exposed as `@tool` functions
- **Tiered models**: `bedrock_model_id` (default Sonnet 4.6 — mid tier for router/executor), `bedrock_model_id_cheap` (Haiku 4.5), `bedrock_model_id_strong` (Opus 4.6). Per-agent overrides live in `config/settings.yaml` (`agent_*_model_id`) and win over tier defaults — the committed defaults run main on **Opus 5**, sre on **Fable 5.1**, rca/executor on Opus 4.6, scan/detect/reporter on Sonnet 4.6. **Claude 5 family**: Opus 5 / Sonnet 5 / Fable 5.1 are `INFERENCE_PROFILE`-only (reach them as `global.anthropic.*`). Their **single-segment version ids** (`claude-opus-5`, no minor) are handled by the cost-key and picker-label regexes and by `MODEL_WINDOW_DEFAULTS` — a family missing there silently bills $0 and falls back to the global window. `MODEL_WINDOW_DEFAULTS` matching is first-substring-wins, so a specific family must precede its prefix (`claude-fable-5-1` before `claude-fable-5`); `tests/test_claude5_bedrock_models.py` pins this. **Multi-provider**: OpenAI (ChatGPT-family) Bedrock models are first-class — dynamic listing covers Anthropic + OpenAI (`gpt-oss-*` ON_DEMAND raw ids; `gpt-5.6-*` via `global.openai.*` inference profiles); Anthropic-only request features (prompt-cache cachePoints, extended thinking) are capability-gated per model family in `agents/preamble.bedrock_model_kwargs` and never sent to non-Claude models.
- **Extended-thinking request shape is model-dependent** (`agents/preamble.supports_adaptive_thinking`, keyed on the version parsed from the model id): Claude **≥ 4.6** takes adaptive thinking — `{"thinking":{"type":"adaptive"},"output_config":{"effort":"low|medium|high|xhigh|max"}}` — and **400s on the legacy `budget_tokens`** field; Claude **< 4.6** (Haiku 4.5 and older) is the reverse, rejecting `adaptive`. `thinking_fields_for_budget(budget, max_tokens, model_id)` therefore takes the model id as a **required** argument: the shapes are mutually exclusive and guessing wrong fails the request rather than degrading. The budget stays the internal currency (so MVP-2.2.1 escalation is unchanged) and maps to an effort tier: 2048 low, 4096 medium, 8192 high, 12288 xhigh, above that max. Non-Anthropic ids keep the `budget_tokens` shape on purpose — that is what `bedrock_model_kwargs` reads to build their native `reasoning_effort`.
- **Auto-fix pipeline**: HealthIssue → RCA → post-RCA quality gate (evidence check → critic → confidence ≥ 0.6) → SRE → Approve(L0/L1) → Execute → Resolve. Low-confidence/refuted RCA → `needs_review`, no auto-fix
- **Signal Gate (MVP-2.2.0)**: ALL issue creation (webhook/agent/REST) flows through `services/signal_gate.process_signal` — L1 deterministic rules (fingerprint-v2 = account|provider|resource|issue_type|upstream-key, flapping, cooldown, resource+type merge) + L2 cheap-LLM gray-zone judge (merge-or-new ONLY, never noise, fail-open). Every event = one auditable Signal row (`alert_events`); `GET /api/signals` + promote endpoint
- **Dual alert intake**: Webhook (Prometheus/CloudWatch/Datadog) + IM Agent (Feishu/Slack)
- **FixPlan dedup**: One issue → one active plan (draft=update, locked=reject, terminal=allow new)

## 凭证安全铁律 (multi-account credential safety)

平台是多 AWS 账户。任何"业务/扫描/执行"路径必须遵守:
1. **不得裸用 `boto3.Session()` / `boto3.client()` 跑跨账户调用** —— 必须经 provider 层
   (`get_provider(account).resolve_credentials()` → `cli_tool()/sdk_session()`)取**目标账户**凭证。
   (例外:Bedrock 控制面 `get_bedrock_session()`、账户 test-connection、`list_available_profiles` 可读 `~/.aws`。)
2. **凭证解析失败 = 显式报错,绝不静默回退到 ambient(进程默认)凭证** —— 多账户下 ambient 只对应某一个账户,
   降级 = 在错误账户上执行。`environment` 源类型是唯一合法的"用本地默认链"声明(经 provider 层解析 + GetCallerIdentity
   校验,属解析成功),除此之外**没有任何 ambient 回退路径**。
3. **账户寻址执行(account-addressed),不再用隐式 ContextVar**:业务工具(`run_on_host`/`run_kubectl`/`run_aws_cli`、
   `describe_*`、network/eks/cloudwatch/cloudtrail)都带显式 `account` 参数。解析顺序:显式 `account` → 按目标资源
   反查库存(`run_on_host` 按 instance-id、`run_kubectl` 按 cluster-name)→ 单账户默认(`resolve_default_account`,
   恰一个启用账户)→ fail-closed 列出账户名。子进程注入前先 strip 所有 `AWS_*`,再只注入解析出账户的 frozen 凭证
   (+ 需要时回注 region)。统一入口:`credentials/resolver.get_subprocess_env_for_account(account[, region])` ——
   `run_aws_cli/_readonly`、`run_on_host(ssm)`、`aws eks update-kubeconfig` 都经它取目标账户 env。**无任何"无上下文回退
   ambient"分支**(旧 `_active_account_var` ContextVar 已删:Strands 同步工具在 `asyncio.to_thread`+`copy_context` 里跑,
   工具内的 ContextVar 写入跨不出工具边界)。主机访问降级阶梯:`run_on_host(method="auto")` SSM → 分类失败 → SSH。
4. **缓存 key 必须含 account**:`credentials/resolver` 双写 `{provider}:{name}:{region}` 与 `{account_id}:{region}`,
   禁止 region-only 取 session。会话缓存单一归属:`aws_tools._session_cache` 即 `providers/base._session_cache`(同一
   dict,线程安全);`SessionFactory._cache` 仅服务 Bedrock 控制面 + test-connection,另属一类。
5. **AssumeRole 会话自动刷新**:`providers/aws._build_assume_role_session` 用 botocore 原生
   `AssumeRoleCredentialFetcher` + `DeferredRefreshableCredentials`,长任务自动续期,勿退回手搓静态 Session+TTL。
6. **纵深校验**:`resolve_credentials` 在 `credentials.account_id` 存在时校验 `GetCallerIdentity().Account` 必须匹配,
   否则 fail-closed(防错号执行);未配置 `account_id` 则不校验(行为不变)。

## Key Modules

### Backend (`src/agenticops/`)

| Module | Key Files | Purpose |
|--------|-----------|---------|
| `cli/` | `main.py`, `context.py`, `display.py`, `formatters.py`, `init_helpers.py` | CLI entry, chat loop, slash commands, init wizard |
| `web/` | `app.py`, `session_manager.py`, `routers/cost.py` | FastAPI (~70 endpoints), per-session agents, SSE streaming; concurrent chat sessions via frontend `chatStream` store; cursor-paginated + virtualized history; `GET /api/cost/summary` (real-time token/cost aggregation); unified Settings **Messaging** tab via `/api/messaging/*` (facade over channels.yaml + im-apps.yaml + NotificationLog; old `/api/notifications/*` + `/api/settings/{channels,im-apps}` deprecated) |
| `agents/` | `main_agent.py`, `scan_agent.py`, `detect_agent.py`, `rca_agent.py`, `sre_agent.py`, `executor_agent.py`, `reporter_agent.py` | 7 agents (1 router + 6 specialists) |
| `tools/` | `metadata_tools.py`, `aws_cli_tool.py` | Agent tools: DB CRUD, AWS CLI wrapper |
| `services/` | `pipeline_service.py`, `rca_service.py`, `rca_quality.py`, `signal_gate.py`, `notification_service.py`, `pipeline_events.py`, `resolution_service.py`, `executor_service.py`, `cost_service.py` | Auto-fix pipeline, auto-RCA + post-RCA quality gate (evidence check → critic → confidence gate), **Signal Gate** (unified dedup/noise judgment for ALL issue-creation paths: L1 deterministic rules + L2 gray-zone LLM merge-only), notifications, event timeline, token/cost aggregation |
| `cost.py` | — | Pure token→USD cost computation via `config.token_cost_table`; `compute_cost(model, tokens)` never raises |
| `models.py` | — | SQLAlchemy models: HealthIssue, FixPlan, RCAResult, Report, etc. |
| `config.py` | — | Pydantic-settings config (`AIOPS_` env prefix) |
| `chat/` | `preprocessor.py`, `file_reader.py`, `send_to.py`, `channel.py` | Message preprocessing, file upload, I#/R# refs, /send_to, /channel |
| `graph/` | `engine.py`, `algorithms.py`, `collectors.py`, `types.py`, `api.py`, `tools.py` | Infrastructure graph: SPOF, capacity risk, dependency chain, change sim |
| `galaxy/` | `models.py`, `hashing.py`, `rules.py`, `builder.py`, `api.py` | Resource relationship graph (LLM-hybrid, PoC, **Experimental**): L1 code rules (containment/ID-ref/tag-group, `provenance=rule`) + L3 LLM semantic enrichment (Haiku, temp=0) with **fail-closed verification** (endpoints must exist in inventory + evidence grounded in `raw_data`, either endpoint); content-hash incremental builds ($0 when unchanged); `provenance`-gated trust (llm edges advisory-only, never drive execution); build history pruned to `galaxy_builds_keep`. Independent of `graph/`. Endpoints `/api/galaxy/{rebuild,status,overview,expand,graph}`. Frontend `/galaxy`: **Canvas starfield** (d3-force, fixed Nebula-Violet theme, ~1300 nodes) — pulse for warning/critical, dashed llm edges; single-click → right key-info panel; issue → centered Dialog; "view raw_data" → 2nd right-side panel with collapsible `JsonTree` (`components/galaxy/`) |
| `skills/` | `loader.py`, `security.py`, `tools.py`, `execution.py`, `evolution.py`, `curator.py`, `review.py`, `improvement_store.py` | Skill discovery (XML-escaped, YAML colon-fallback, kebab-case name validation, 200-char index), security classification, run_on_host/run_kubectl, autonomous create/improve, Curator lifecycle, security-gated promote/rollback, improvement audit |
| `notify/` | `notifier.py`, `im_config.py` | Multi-channel notifications, YAML channel config |
| `im/` | `feishu_ws.py` | IM bot (Feishu WebSocket), alert channel routing |
| `kb/` | `vector_store.py` | Vector storage (SQLite/pgvector/S3) — KB case search only |
| `memory/` | `agent_memory.py`, `curator.py`, `migrate_backfill.py` | File-based self-optimizing agent memory (Hermes-style); single core, no DB |
| `pipeline/` | `rag_pipeline.py`, `orchestrator.py`, `health_patrol.py` | RAG pipeline, patrol orchestrator |
| `integrations/` | `alert_processor.py`, `parsers.py` | Webhook alert processing, source parsers |
| `security/` | `collectors.py`, `scoring.py`, `reachability.py`, `posture_snapshot.py`, `incremental_poll.py`, `advisor.py` | **Cloud Security Review engine (MVP-2.5.0)** — dual-frequency deterministic collection (slow `SecurityPostureSnapshot` + fast `SecurityIncrementalPoll` cursor-based, both account-addressed through the provider layer, fail-soft per collector/source) + **reproducible CIS scoring** (`scoring.py` pure: no random/time/LLM; reachability & recommendations never alter scores) + **NACL-aware three-state ingress reachability** (`reachable`/`not_reachable`/`undetermined`; missing route/NACL data → `undetermined`, never `not_reachable` — conservative bias) + **evidence-grounded advisor** (`advisor.py`, the only LLM component: parse→ground-to-inventory→per-rec critic→fail-closed persist, ungrounded/refuted/any-exception → 0 rows). All issue creation flows through `signal_gate.process_signal` (fingerprint-v2 dedup). Tables `security_snapshots`/`security_recommendations`/`security_poll_cursors`. Endpoints `/api/security/{summary,trend,findings,recommendations,attack-paths}`; report `security-review`; frontend `/app/security` + Dashboard highlight card |
| `storage/` | `backend.py` | Storage backends (local/S3) for reports + KB |
| `acp/` | `types.py`, `registry.py`, `jsonrpc.py`, `mapping.py`, `client.py`, `backends/{claude_code,kiro_cli,codex}.py` | Optional ACP enhanced backend (MVP-1.3.0) — protocol-agnostic `EnhancedBackend` abstraction + registry; self-implemented JSON-RPC/stdio `AcpClient` (per-provider `protocol_version`); 3 providers: `claude-code` (Bedrock), `kiro-cli` (`kiro-cli acp`), `codex` (`codex-acp`, needs `OPENAI_API_KEY`). `enhanced_task` async-gen tool (`agents/enhanced.py`) streams live via `ToolStreamEvent`→SSE, conditionally into main/sre. Provider chosen in Settings→Enhanced Backend. Default off (`acp_enhanced_enabled`) |

### Frontend (`src/agenticops/web/frontend/src/`)

| Directory | Contents |
|-----------|----------|
| `pages/` | 15 pages: Dashboard, Chat, IssuesAndPlans, IssueDetail, Resources(detail), ReportDetail, Reports, ScheduleDetail, Schedules, AgentMetrics, Skills, SkillDetail, Settings, Login, Galaxy |
| `hooks/` | 25+ TanStack Query hooks (incl. chatStream-backed useSessionStream/useChatMessages, useMessaging, useCostSummary, useTraceTimeline, useGalaxy) |
| `components/` | Chat components, layout (AppShell, Sidebar, Header), `galaxy/` (GalaxyNodePanel, GalaxyIssueDialog, GalaxyRawDataPanel, JsonTree) |
| `api/` | `client.ts`, `types.ts` |

**Popup/panel house rule (2026-07-04):** every overlay/side-panel/dialog ① animates in with `animate-[slideInRight_0.2s_ease-out]` (keyframe in tailwind.config.ts) and ② closes on ESC (window keydown listener bound while open, or Radix primitive which has it built in). Reference implementations: `chat/ContextPanel.tsx`, `chat/SaveReportDialog.tsx`.

### Skills (`skills/`) — autonomous, self-optimizing (cycle③ 2026-05-31)

15 domain skills: linux-admin, network-engineer, kubernetes-admin, database-admin, elasticsearch, monitoring, log-analysis, aws-compute, aws-storage, local-os-operator, web-research, distributed-tracing, notification-operator, document-analysis, security-engineer. Each: SKILL.md + references/*.md. Guide: `skills/ADDING_SKILLS.md`. Scan and detect agents also have `activate_skill` for dynamic tool registration.

**Hermes-style autonomy** (mirrors the cycle② memory pattern; skills are EXECUTABLE so promotion is security-gated):
- **3-tier progressive disclosure** (preserved): system-prompt XML (~911 tok measured 2026-06; pinned by `tests/test_prompt_budget.py` skills-XML budget) → `activate_skill` (full body) → `read_skill_reference` (deep-dive).
- **`skill_manage` tool** (`tools.py`, mirrors `memory_manage`): agent self-curation via `add`/`improve`/`merge`/`deprecate`/`restore`/`search`. Agent writes land as **drafts only** (`created_by=agent`), never auto-published. Gated by `skills_autonomous_write`.
- **Provenance frontmatter**: `created_by` (user=pinned / agent), `created_at`, `last_improved_at`, `improved_from` (genealogy), `skill_version`, `status` (active/stale/deprecated/archived). `normalize_skill_frontmatter` backfills old SKILL.md non-destructively; the 15 human skills are `created_by=user` (pinned). `[AGENT]` tag in `list_skills` XML.
- **Skills Curator** (`curator.py`, zero LLM): ages UNUSED `created_by=agent` drafts `active→stale(30d)→archived(60d)` by `last_used`; **human skills pinned (never touched)**; **never deletes** (moves to `skills/.archive/`, recoverable via `restore_skill`); **reactivate-on-use** (`touch_skill_used` on `activate_skill`). Runs at main-agent build (gated by `skills_curator_enabled`).
- **Security-gated promotion** (`review.py` + `security.py`): `promote_skill` scans the draft body (`scan_skill_safety` — flags blocked-tier commands in fenced bash) before publishing; archives the prior published version to `skills/.archive/<name>__<ts>/` (multi-gen, recoverable). `rollback_skill` restores the most recent archived version. Skill names sanitized (`_safe_skill_name`, path-traversal guard).
- **Improvement audit loop** (`improvement_store.py`): all three improve paths (`improve_skill` tool, `skill_manage improve`, `services/skill_improvement_service`) record to the improvement store for genealogy.
- **Frozen-snapshot injection**: skills XML loaded once at agent build; writes take effect next session (protects Bedrock prompt-cache, consistent with memory).
- **Config** (settings.yaml): `skills_autonomous_write`, `skills_curator_enabled`, `skills_draft_stale_days`, `skills_draft_archive_days`, `skills_security_scan_on_promote`.
- **API**: `POST /api/skills/{name}/rollback`, `POST /api/skills/{name}/restore` (+ existing promote/review/improve).

**Wide loading + script sandbox (MVP-2.5.0, 2026-09-08)**

- **Wide loading (URL / git / zip)**: `skills/sources.py` — `import_skills(uri, names=None)` fetches an `http(s)` archive or bare `SKILL.md`, a git repo (`git+https://…[@ref][#subdir]`, `--depth 1`, `.git` stripped), or a local zip/tar.gz/directory; recursively discovers EVERY directory holding a `SKILL.md` (a hit is not descended into, so a skill's own `references/SKILL.md` never becomes a second package). Per-package fail-closed checks: kebab-case name (validated against the destination draft dir), no symlinks, no archive entry that is absolute/traversing/a link, extension allowlist (**a file with NO extension rejects the whole package** — `_validate_package` checks every suffix against `skills_import_allowed_extensions`), file-count and byte caps; then staging + `os.replace` atomic rename so there is never a half-installed skill. Everything lands in `skills_draft_dir` with `created_by=imported` + `source_uri`/`source_ref`/`imported_at` — never published, never injected, and **no packaged script is ever executed during import** (no `install.sh` hook). Importing is a HUMAN action: `aiops skills import <uri> [--name N]` or `POST /api/skills/import-source` (the older `POST /api/skills/import` remains the multipart upload path). Agents get no import tool. `imported` skills age like `agent` drafts under the Curator; `user` skills stay pinned.
- **Bundle security gate**: `promote_skill` calls `security.scan_skill_bundle(pkg_dir)` — the SKILL.md body (as before) PLUS every packaged `.sh` and `.py`. **The two halves are the same gate at two different precisions, not one shape:** `.py` is **`ast`-based and binding-resolved** (a rule fires on what a name actually resolves to, so `model.eval()`/`df.eval()`/`session.exec()` are clean where the old regex hard-blocked them — a deliberate trade, and `eval`/`exec` reached through an *unresolvable* receiver is therefore also clean), while `.sh` is still **line-based** (`classify_shell_command` per line, so it still flags a blocked command quoted in prose). A non-directory `pkg_dir` and an unparseable `.py` both fail **closed**; `tier` is always `"blocked"` today. **Known limitation, one root cause with three faces:** `_py_prepass` collects bindings with `ast.walk` over the whole tree, so it is **reachability-blind and scope-blind** — a statement that can never execute still contributes bindings. Its three surfaced members are alias-map merging, import bindings being last-write-wins (fail-**closed**: `_py_resolve` falls back to the source spelling) and constant dead-reassignment (fail-**open**: value and rule both lost). **The honest claim:** this is a deterministic pre-filter in front of a human promote, not resistance to a determined obfuscator; closing the `_py_prepass` class needs scope- and control-flow-aware binding analysis, which is a different project.
- **Script sandbox** (`skills/sandbox.py`, default **OFF**): `run_script(skill, script, args, stdin_text)` runs a **published** skill's own `*.py`/`*.sh` with the env built from an EMPTY dict (exactly `PATH`/`HOME`/`LANG`, so no `AWS_*` can structurally appear), network isolation via `unshare -n` (Linux) / `sandbox-exec` (macOS) — and when neither exists it **refuses to run** while `skills_sandbox_require_isolation` is true, rather than claiming an isolation it does not have. Interpreter comes from a suffix allowlist (never a shebang, never the exec bit, `shell=False`), cwd is a one-shot `mkdtemp` deleted afterwards, timeout kills the process group. Output capture is a `selectors` loop (**never `select.select`** — its `FD_SETSIZE` limit silently loses ALL output above fd 1023 — and **never `communicate()`**, whose `TimeoutExpired` join measured 2.99 GB RSS in the service process on a plain output flood): it keeps *draining* past the cap so a child cannot deadlock us, while *storing* at most `skills_sandbox_max_output_bytes` per stream (**BYTES**, so CJK output is a byte budget). Every refusal is a `RuntimeError`; **filesystem writes are NOT confined** (the service user's normal access) — that limit is why the bundle scan's destructive-filesystem rules are a real boundary, not defence-in-depth. Exposed to the executor agent as `run_skill_script` (absent from the tool list while the sandbox is off); no credentials and no network inside, so cloud actions still go through `run_aws_cli`/`run_on_host`/`run_kubectl`.
- **Known gaps (documented, not fixed)**: nothing tests the KNOWN LIMITATIONS block's own claims; multi-valued bindings would close the constant member and most disclosed import residuals, at the cost of new fold semantics for every path rule. A `setsid()`'d grandchild is not reaped (no cgroup, no PID namespace) — the returned stderr says so instead of claiming a clean kill. The Linux `unshare -n` branch is unexercised on darwin.

### Agent Memory (`memory/`) — self-optimizing, file-based (cycle② 2026-05-31)

File-based markdown memory under `agent-memory/<agent>/*.md` (+ `shared/`) is the **single core** for agent behavioral memory. **Not a DB** (the old `AgentMemory`/`AgentMemoryFact` DB tables + `web/memory_service.py` are frozen/deprecated — they were a dead injection path).

- **Frontmatter**: `agent, type(feedback|pattern|preference|baseline|umbrella), status(active|stale|archived), confidence(1-5), source, created_by(user|agent), created_at, last_confirmed, last_used, absorbed_into/absorbed_from, resource_pattern`.
- **Hermes-style Curator** (`curator.py`, zero LLM): size-cap (`memory_max_active`, default 15) forces self-merge at write time; background lifecycle `active→stale(30d)→archived(60d)` by `last_used`; **never deletes** (archives to `<agent>/.archive/`, recoverable via `restore_memory`); **reactivate-on-use** (touched on injection). Runs at each main-agent build (gated by `memory_curator_enabled`).
- **Agent autonomy**: `memory_manage` tool (add/patch/merge/remove/search) lets agents self-curate; agent-written memories tagged `created_by=agent` (provenance, human-auditable). Gated by `memory_autonomous_write`.
- **Injection**: frozen-snapshot — loaded once at agent build via `build_system_prompt`, top-`memory_max_active` by confidence then recency; writes take effect NEXT session (protects Bedrock prompt-cache). Injection also `touch_last_used`s each memory (reactivate-on-use).
- **Concurrency-safe writes**: `_atomic_write_text` writes a **per-(pid,thread,counter)-unique** tmp then `os.replace` (atomic, last-writer-wins). Required because parallel agent builds all touch the same `shared/` memories at once — a fixed tmp name previously raced (`FileNotFoundError` on `os.replace`).
- **Config** (settings.yaml): `memory_max_active`, `memory_stale_days`, `memory_archive_days`, `memory_autonomous_write`, `memory_curator_enabled`.
- **Deferred (YAGNI)**: episodic semantic-recall tier (vectors) — only `kb/vector_store.py` for KB case search today; S3 Vectors is a future cloud-only option, not built.

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

All settings use `AIOPS_` env prefix. Key ones:

| Setting | Default | Description |
|---------|---------|-------------|
| `bedrock_model_id` | `global.anthropic.claude-sonnet-4-6` | Default (mid) tier — main router + executor. `config/settings.yaml` overrides per-agent (e.g. main → Opus 5, sre → Fable 5.1) |
| `bedrock_model_id_cheap` | `global.anthropic.claude-haiku-4-5-20251001-v1:0` | Economy tier (Haiku 4.5) — tier default for scan/detect/reporter (settings.yaml may raise to Sonnet) |
| `bedrock_model_id_strong` | `global.anthropic.claude-opus-4-6-v1` | Strong tier (Opus 4.6) — tier default for RCA/SRE |
| `bedrock_max_tokens` | `16384` | Max output tokens |
| `bedrock_region` | `us-east-1` | AWS Bedrock region |
| `database_url` | `sqlite:///...agenticops.db` | Database URL |
| `auto_rca_enabled` | `true` | Auto-trigger RCA |
| `auto_fix_enabled` | `true` | Auto-fix pipeline |
| `executor_auto_approve_l0_l1` | `true` | Auto-approve L0/L1 |
| `executor_hitl_enabled` | `false` | Add a Strands `HumanInTheLoop` intervention as a 2nd SDK-level approval gate on executor (default off; primary gate stays `get_approved_fix_plan` + DB state machine). Read-only tools allow-listed; mutating tools raise interrupt |
| `notifications_enabled` | `true` | Auto-notifications |
| `notifications_consolidated` | `true` | Suppress per-issue notifications during Scan/Detect/RCA; only final report sent. Set `false` for dev/debug |
| `bedrock_cache_enabled` | `true` | Prompt caching on all agents |
| `strands_context_manager_auto` | `true` | Strands SDK auto context management (SummarizingConversationManager + ContextOffloader) on all 8 agent builds. Coexists with per-agent `conversation_manager` (SDK preserves ours, only adds ContextOffloader). Offloads oversized tool results (AWS CLI/describe) to keep context bounded |
| `agent_{name}_model_id` | `""` | Per-agent model override (7 agents: main/scan/detect/rca/sre/executor/reporter) |
| `agent_{name}_max_tokens` | `0` | Per-agent max_tokens override (0 = use bedrock_max_tokens) |
| `deployment_profile` | `local` | local or cloud |
| `skills_enabled` | `true` | Agent Skills |
| `skills_autonomous_write` | `true` | Allow agents to self-create/improve skills via `skill_manage` (drafts only) |
| `skills_curator_enabled` | `true` | Skills Curator lifecycle (agent drafts stale/archive; human skills pinned) |
| `skills_draft_stale_days` | `30` | Days an unused agent draft stays before stale |
| `skills_draft_archive_days` | `60` | Additional days after stale before an agent draft is archived |
| `skills_security_scan_on_promote` | `true` | Security-scan a skill before draft→published (blocks dangerous run_on_host) |
| `skills_import_enabled` | `true` | Allow importing skills from URL/git/zip (CLI + `/api/skills/import-source`) |
| `skills_import_max_package_bytes` | `2097152` | Max bytes per imported package (also the download cap) |
| `skills_import_max_files` | `50` | Max files per imported package |
| `skills_import_allowed_extensions` | `[.md,.py,.sh,.txt,.json,.yaml,.yml,.csv]` | Extension allowlist; a file with NO extension rejects the whole package |
| `skills_import_timeout_seconds` | `60` | Download / `git clone` timeout |
| `skills_sandbox_enabled` | `false` | Enable running skill-owned `*.py`/`*.sh` in the restricted sandbox (also gates whether the executor agent sees `run_skill_script`) |
| `skills_sandbox_timeout_seconds` | `60` | Per-run sandbox timeout (kills the process group) |
| `skills_sandbox_max_output_bytes` | `20000` | Truncation cap for sandbox stdout and stderr each, in **bytes** (not characters) |
| `skills_sandbox_require_isolation` | `true` | Refuse to run when no `unshare -n` / `sandbox-exec` is available |
| `skills_sandbox_interpreters` | `{.py: python, .sh: /bin/bash}` | Suffix → interpreter allowlist (`python` = `sys.executable`) |
| `acp_enhanced_enabled` | `false` | Enable the optional ACP enhanced-task backend (delegate complex tasks to Claude Code/Kiro) |
| `acp_enhanced_backend` | `claude-code` | Default enhanced backend provider |
| `acp_use_bedrock` | `true` | Run the enhanced backend on Bedrock (`CLAUDE_CODE_USE_BEDROCK=1`) |
| `acp_timeout_seconds` | `300` | Per-turn timeout for an enhanced-backend subprocess |
| `acp_auto_approve_permissions` | `true` | Auto-approve the backend's permission requests (allow_once) |
| `acp_kiro_command` / `acp_kiro_args` | `kiro-cli` / `["acp","--trust-all-tools"]` | Kiro CLI ACP launch (uses kiro's own login) |
| `acp_codex_command` / `acp_codex_args` | `npx` / `["-y","@zed-industries/codex-acp"]` | Codex ACP launch (needs `OPENAI_API_KEY`) |
| `scan_focus` | `all` | Resource categories filter |
| `patrol_graph_checks_enabled` | `true` | SPOF + capacity-risk graph analysis step in health patrol (prevention; findings create HealthIssues with auto_rca off) |
| `rca_topology_context_enabled` | `true` | Inject topology context (neighbors, blast radius, recent graph changes) into RCA invocation prompts |
| `galaxy_enabled` | `true` | Enable Galaxy graph build pipeline + `/api/galaxy` + post-scan/hourly triggers |
| `galaxy_build_interval_minutes` | `60` | Auto `galaxy-auto-build` schedule cadence |
| `galaxy_model_id` | `""` | Override model for Galaxy LLM enrichment (empty = `bedrock_model_id_cheap`) |
| `galaxy_batch_size` | `40` | Max resources per LLM enrichment batch |
| `galaxy_confidence_min` | `0.5` | Minimum confidence to keep an LLM edge |
| `galaxy_drop_rate_alert` | `0.05` | LLM-edge drop rate that logs a WARNING (drift smoke detector) |
| `galaxy_expand_node_cap` | `200` | Max nodes per `/expand` before truncation |
| `galaxy_llm_exclude_types` | `[IAMRole,KMS,S3,ECR_Repository]` | Relationship-sparse leaf types excluded from LLM enrichment |
| `galaxy_builds_keep` | `24` | Newest build rows retained (older pruned after each build to bound DB growth) |
| `signal_gate_enabled` | `true` | Route all HealthIssue creation through the Signal Gate (false = legacy dedup only) |
| `signal_gate_llm_enabled` | `true` | L2 gray-zone LLM merge judgment (cheap tier, merge-or-new only) |
| `signal_gate_confidence_min` | `0.7` | Min LLM confidence to accept a gray-zone merge (below → promote) |
| `noise_flap_threshold` / `noise_flap_window_minutes` | `3` / `30` | Same-fingerprint signals in window at/after which further ones are noise |
| `signal_retention_days` | `30` | Signal (alert_events) row retention |
| `rca_min_confidence_for_autofix` | `0.6` | RCA confidence below this → needs_review, no auto-SRE |
| `rca_critic_enabled` | `true` | Cheap-model adversarial critic after each RCA (refuted → ×0.5 confidence) |
| `rca_timeout_seconds` | `900` | RCA watchdog (timeout → failed event + needs_review) |
| `rca_incident_memory_enabled` / `rca_incident_memory_max` | `true` / `3` | Inject prior same-fingerprint RCA conclusions (with verdicts) into the RCA prompt |
| `rca_max_iterations` | `40` | Max event-loop turns per RCA run |
| `agent_{name}_thinking_budget` | `0` | Extended-thinking base budget tokens (yaml enables rca=4096); 0 = off, and escalation never turns it on |
| `thinking_escalation_step` | `4096` | Tokens added per escalation tier (MVP-2.2.1: RCA gets +1 tier for critical severity, +1 for a rerun after needs_review/disputed — they stack) |
| `thinking_budget_min` | `1024` | Bedrock minimum; a budget below this (or ≥ max_tokens) disables thinking instead of sending an illegal request |
| `thinking_effort_presets` | `{off:0, low:2048, standard:4096, high:8192, xhigh:12288, deep:12288, max:24576}` | Named effort levels backing the per-session chat override (`chat_sessions.effort`, NULL = Auto). On Claude ≥ 4.6 the budget maps to an `output_config.effort` tier (see the adaptive-thinking note above); `max` is clamped to `max_tokens - thinking_budget_min` first. Keys must be quoted in YAML — bare `off` parses as boolean false |
| `security_review_enabled` | `true` | Enable the cloud security review engine (dual-frequency collect + CIS scoring + reachability) |
| `security_poll_interval_minutes` | `10` | Fast-frequency `SecurityIncrementalPoll` schedule interval |
| `security_posture_interval_minutes` | `60` | Slow-frequency `SecurityPostureSnapshot` schedule interval |
| `security_reachability_nacl_enabled` | `true` | Include NACL evaluation in ingress reachability; missing NACL data → `undetermined` |
| `security_advisor_enabled` | `true` | Enable the evidence-grounded LLM recommendation advisor (Stage 5) |
| `security_advisor_critic_enabled` | `true` | Adversarial critic over each recommendation; refuted → dropped (fail-closed) |
| `security_snapshot_retention_days` | `90` | Days of `SecuritySnapshot` rows retained before pruning |
| `security_model_id` | `""` | Override model for the security advisor; empty = `bedrock_model_id_cheap` |

## HealthIssue State Machine

9 states: `open` → `investigating` → `acknowledged` → `root_cause_identified` → `fix_planned` → `fix_approved` → `fix_executing` → `fix_executed` → `resolved`. Transitions enforced by `validate_status_transition()` (409 on invalid).

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
uvicorn agenticops.web.app:app --reload --port 8000  # API server

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
