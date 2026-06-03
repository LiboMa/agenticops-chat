# AgenticOps — Development Guide

## Project Overview

AgenticOps (`aiops`) — CLI + Web AI operations assistant with multi-agent architecture (Strands SDK on AWS Bedrock). Provides `aiops chat` interactive REPL, React web dashboard with streaming chat, resource scanning, anomaly detection, fix planning, and reporting across AWS accounts.

**User-facing docs:** `docs/WORKFLOW.md` (Mermaid diagrams + tutorials), `docs/MVP-1.0.0-RELEASE.md` (feature report), `docs/MVP-1.1.1-RELEASE.md` (latest: concurrent chat sessions + fast open)

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
- **Tiered models**: `bedrock_model_id` (Sonnet 4.6 or Opus 4.6), `bedrock_model_id_cheap` (Haiku 4.5), `bedrock_model_id_strong` (Opus 4.6). Sonnet 4.6 (`global.anthropic.claude-sonnet-4-6`) available as mid-tier option for router/executor.
- **Auto-fix pipeline**: HealthIssue → RCA → SRE → Approve(L0/L1) → Execute → Resolve
- **Dual alert intake**: Webhook (Prometheus/CloudWatch/Datadog) + IM Agent (Feishu/Slack)
- **FixPlan dedup**: One issue → one active plan (draft=update, locked=reject, terminal=allow new)

## Key Modules

### Backend (`src/agenticops/`)

| Module | Key Files | Purpose |
|--------|-----------|---------|
| `cli/` | `main.py`, `context.py`, `display.py`, `formatters.py`, `init_helpers.py` | CLI entry, chat loop, slash commands, init wizard |
| `web/` | `app.py`, `session_manager.py` | FastAPI (~70 endpoints), per-session agents, SSE streaming; concurrent chat sessions via frontend `chatStream` store; cursor-paginated + virtualized history; unified Settings **Messaging** tab via `/api/messaging/*` (facade over channels.yaml + im-apps.yaml + NotificationLog; old `/api/notifications/*` + `/api/settings/{channels,im-apps}` deprecated) |
| `agents/` | `main_agent.py`, `scan_agent.py`, `detect_agent.py`, `rca_agent.py`, `sre_agent.py`, `executor_agent.py`, `reporter_agent.py` | 7 agents (1 router + 6 specialists) |
| `tools/` | `metadata_tools.py`, `aws_cli_tool.py` | Agent tools: DB CRUD, AWS CLI wrapper |
| `services/` | `pipeline_service.py`, `rca_service.py`, `notification_service.py`, `pipeline_events.py`, `resolution_service.py`, `executor_service.py` | Auto-fix pipeline, auto-RCA, notifications, event timeline |
| `models.py` | — | SQLAlchemy models: HealthIssue, FixPlan, RCAResult, Report, etc. |
| `config.py` | — | Pydantic-settings config (`AIOPS_` env prefix) |
| `chat/` | `preprocessor.py`, `file_reader.py`, `send_to.py`, `channel.py` | Message preprocessing, file upload, I#/R# refs, /send_to, /channel |
| `graph/` | `engine.py`, `algorithms.py`, `collectors.py`, `types.py`, `api.py`, `tools.py` | Infrastructure graph: SPOF, capacity risk, dependency chain, change sim |
| `skills/` | `loader.py`, `security.py`, `tools.py`, `execution.py`, `evolution.py`, `curator.py`, `review.py`, `improvement_store.py` | Skill discovery (XML-escaped, YAML colon-fallback, kebab-case name validation, 200-char index), security classification, run_on_host/run_kubectl, autonomous create/improve, Curator lifecycle, security-gated promote/rollback, improvement audit |
| `notify/` | `notifier.py`, `im_config.py` | Multi-channel notifications, YAML channel config |
| `im/` | `feishu_ws.py` | IM bot (Feishu WebSocket), alert channel routing |
| `kb/` | `vector_store.py` | Vector storage (SQLite/pgvector/S3) — KB case search only |
| `memory/` | `agent_memory.py`, `curator.py`, `migrate_backfill.py` | File-based self-optimizing agent memory (Hermes-style); single core, no DB |
| `pipeline/` | `rag_pipeline.py`, `orchestrator.py`, `health_patrol.py` | RAG pipeline, patrol orchestrator |
| `integrations/` | `alert_processor.py`, `parsers.py` | Webhook alert processing, source parsers |
| `storage/` | `backend.py` | Storage backends (local/S3) for reports + KB |

### Frontend (`src/agenticops/web/frontend/src/`)

| Directory | Contents |
|-----------|----------|
| `pages/` | 15 pages: Dashboard, Chat, Resources, Anomalies, AnomalyDetail, FixPlans, FixPlanDetail, Reports, ReportDetail, Schedules, ScheduleDetail, Notifications, NotificationLogs, Accounts, AuditLog |
| `hooks/` | 23 TanStack Query hooks |
| `components/` | Chat components, layout (AppShell, Sidebar, Header) |
| `api/` | `client.ts`, `types.ts` |

### Skills (`skills/`) — autonomous, self-optimizing (cycle③ 2026-05-31)

15 domain skills: linux-admin, network-engineer, kubernetes-admin, database-admin, elasticsearch, monitoring, log-analysis, aws-compute, aws-storage, local-os-operator, web-research, distributed-tracing, notification-operator, document-analysis, security-engineer. Each: SKILL.md + references/*.md. Guide: `skills/ADDING_SKILLS.md`. Scan and detect agents also have `activate_skill` for dynamic tool registration.

**Hermes-style autonomy** (mirrors the cycle② memory pattern; skills are EXECUTABLE so promotion is security-gated):
- **3-tier progressive disclosure** (preserved): system-prompt XML (~460 tok total, measured — no per-agent filtering needed) → `activate_skill` (full body) → `read_skill_reference` (deep-dive).
- **`skill_manage` tool** (`tools.py`, mirrors `memory_manage`): agent self-curation via `add`/`improve`/`merge`/`deprecate`/`restore`/`search`. Agent writes land as **drafts only** (`created_by=agent`), never auto-published. Gated by `skills_autonomous_write`.
- **Provenance frontmatter**: `created_by` (user=pinned / agent), `created_at`, `last_improved_at`, `improved_from` (genealogy), `skill_version`, `status` (active/stale/deprecated/archived). `normalize_skill_frontmatter` backfills old SKILL.md non-destructively; the 15 human skills are `created_by=user` (pinned). `[AGENT]` tag in `list_skills` XML.
- **Skills Curator** (`curator.py`, zero LLM): ages UNUSED `created_by=agent` drafts `active→stale(30d)→archived(60d)` by `last_used`; **human skills pinned (never touched)**; **never deletes** (moves to `skills/.archive/`, recoverable via `restore_skill`); **reactivate-on-use** (`touch_skill_used` on `activate_skill`). Runs at main-agent build (gated by `skills_curator_enabled`).
- **Security-gated promotion** (`review.py` + `security.py`): `promote_skill` scans the draft body (`scan_skill_safety` — flags blocked-tier commands in fenced bash) before publishing; archives the prior published version to `skills/.archive/<name>__<ts>/` (multi-gen, recoverable). `rollback_skill` restores the most recent archived version. Skill names sanitized (`_safe_skill_name`, path-traversal guard).
- **Improvement audit loop** (`improvement_store.py`): all three improve paths (`improve_skill` tool, `skill_manage improve`, `services/skill_improvement_service`) record to the improvement store for genealogy.
- **Frozen-snapshot injection**: skills XML loaded once at agent build; writes take effect next session (protects Bedrock prompt-cache, consistent with memory).
- **Config** (settings.yaml): `skills_autonomous_write`, `skills_curator_enabled`, `skills_draft_stale_days`, `skills_draft_archive_days`, `skills_security_scan_on_promote`.
- **API**: `POST /api/skills/{name}/rollback`, `POST /api/skills/{name}/restore` (+ existing promote/review/improve).

### Agent Memory (`memory/`) — self-optimizing, file-based (cycle② 2026-05-31)

File-based markdown memory under `agent-memory/<agent>/*.md` (+ `shared/`) is the **single core** for agent behavioral memory. **Not a DB** (the old `AgentMemory`/`AgentMemoryFact` DB tables + `web/memory_service.py` are frozen/deprecated — they were a dead injection path).

- **Frontmatter**: `agent, type(feedback|pattern|preference|baseline|umbrella), status(active|stale|archived), confidence(1-5), source, created_by(user|agent), created_at, last_confirmed, last_used, absorbed_into/absorbed_from, resource_pattern`.
- **Hermes-style Curator** (`curator.py`, zero LLM): size-cap (`memory_max_active`, default 15) forces self-merge at write time; background lifecycle `active→stale(30d)→archived(60d)` by `last_used`; **never deletes** (archives to `<agent>/.archive/`, recoverable via `restore_memory`); **reactivate-on-use** (touched on injection). Runs at each main-agent build (gated by `memory_curator_enabled`).
- **Agent autonomy**: `memory_manage` tool (add/patch/merge/remove/search) lets agents self-curate; agent-written memories tagged `created_by=agent` (provenance, human-auditable). Gated by `memory_autonomous_write`.
- **Injection**: frozen-snapshot — loaded once at agent build via `build_system_prompt`, top-`memory_max_active` by confidence then recency; writes take effect NEXT session (protects Bedrock prompt-cache).
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
| `config/channels.yaml` | Notification channels (sole source of truth, gitignored) |
| `config/im-apps.yaml` | IM app credentials (gitignored) |
| `config/setup.json.example` | JSON config template for `aiops init --config` |

## Key Configuration (`config.py`)

All settings use `AIOPS_` env prefix. Key ones:

| Setting | Default | Description |
|---------|---------|-------------|
| `bedrock_model_id` | `global.anthropic.claude-opus-4-6-v1` | Default model (Opus 4.6). Can set to `global.anthropic.claude-sonnet-4-6` for cost savings on router/executor |
| `bedrock_model_id_cheap` | `global.anthropic.claude-haiku-4-5-20251001-v1:0` | Economy model (Haiku 4.5) |
| `bedrock_model_id_strong` | `global.anthropic.claude-opus-4-6-v1` | Strong model (Opus 4.6) for RCA/SRE |
| `bedrock_max_tokens` | `16384` | Max output tokens |
| `bedrock_region` | `us-east-1` | AWS Bedrock region |
| `database_url` | `sqlite:///...agenticops.db` | Database URL |
| `auto_rca_enabled` | `true` | Auto-trigger RCA |
| `auto_fix_enabled` | `true` | Auto-fix pipeline |
| `executor_auto_approve_l0_l1` | `true` | Auto-approve L0/L1 |
| `notifications_enabled` | `true` | Auto-notifications |
| `notifications_consolidated` | `true` | Suppress per-issue notifications during Scan/Detect/RCA; only final report sent. Set `false` for dev/debug |
| `bedrock_cache_enabled` | `true` | Prompt caching on all agents |
| `agent_{name}_model_id` | `""` | Per-agent model override (7 agents: main/scan/detect/rca/sre/executor/reporter) |
| `agent_{name}_max_tokens` | `0` | Per-agent max_tokens override (0 = use bedrock_max_tokens) |
| `deployment_profile` | `local` | local or cloud |
| `skills_enabled` | `true` | Agent Skills |
| `skills_autonomous_write` | `true` | Allow agents to self-create/improve skills via `skill_manage` (drafts only) |
| `skills_curator_enabled` | `true` | Skills Curator lifecycle (agent drafts stale/archive; human skills pinned) |
| `skills_draft_stale_days` | `30` | Days an unused agent draft stays before stale |
| `skills_draft_archive_days` | `60` | Additional days after stale before an agent draft is archived |
| `skills_security_scan_on_promote` | `true` | Security-scan a skill before draft→published (blocks dangerous run_on_host) |
| `scan_focus` | `all` | Resource categories filter |
| `agent_output_detail` | `medium` | concise/medium/detailed |

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
