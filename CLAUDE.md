# AgenticOps Development Session Notes

## Project Overview

AgenticOps (`aiops`) — CLI + Web AI operations assistant with multi-agent architecture (Strands SDK on AWS Bedrock). Provides `aiops chat` interactive REPL, a React web dashboard with streaming chat, resource scanning, anomaly detection, fix planning, and reporting across AWS accounts.

**User-facing docs:** `docs/WORKFLOW.md` — Mermaid diagrams of all workflows + 10 quick-start tutorials

## Architecture

```
CLI (aiops chat)  ──┐
                    ├──► Main Agent (orchestrator) ──► Sub-Agents (scan, detect, rca, sre, executor, reporter)
Web Dashboard ──────┘         │
  (React + SSE)               ├──► AWS via STS AssumeRole
                              ├──► CloudWatch, CloudTrail, EKS, VPC, ELB, ...
                              ├──► SQLite metadata DB
                              ├──► Graph Engine (NetworkX)
                              │       ├──► Collectors (EC2, RDS, Lambda, EKS, ECS, ElastiCache, TG)
                              │       ├──► Algorithms (reachability, impact, SPOF, capacity, dependency chain, change sim)
                              │       └──► Serializers (ReactFlow JSON, agent summaries)
                              └──► Agent Skills (SKILL.md packages)
                                      ├──► Loader (discovery, YAML parsing, XML generation)
                                      ├──► Security (shell + kubectl command classification)
                                      ├──► Tools (activate_skill, read_skill_reference, list_skills)
                                      └──► Execution (run_on_host via SSM/SSH, run_kubectl on EKS)
```

- **Agents-as-tools pattern**: Main agent routes to 6 specialist sub-agents exposed as `@tool` functions
- **Tiered model config**: `bedrock_model_id` (Sonnet 4.6), `bedrock_model_id_cheap` (Haiku 4.5), `bedrock_model_id_strong` (Opus 4.6)
- **All 7 agents** use centralized config: `settings.bedrock_model_id*`, `settings.bedrock_max_tokens`, `settings.bedrock_window_size`
- **Conversation management**: `SlidingWindowConversationManager(window_size=40, per_turn=True)` on all agents to prevent `MaxTokensReachedException`
- **Dynamic output rules**: `contextvars.ContextVar` holds detail level (concise/medium/detailed); `build_prompt_with_skills()` injects level-appropriate OUTPUT FORMAT RULES at agent creation time

## Key Files

### Backend

| File | Purpose |
|------|---------|
| `src/agenticops/cli/main.py` | Main CLI entry point (~3750 lines), chat loop, slash commands |
| `src/agenticops/cli/context.py` | `ChatContext` class — chat session state |
| `src/agenticops/cli/display.py` | `ThinkingDisplay` class — spinner/progress; `TokenUsage` class |
| `src/agenticops/cli/formatters.py` | Table styles, markdown/json rendering helpers |
| `src/agenticops/web/app.py` | FastAPI backend (~2500 lines), 80 endpoints |
| `src/agenticops/web/session_manager.py` | Per-session agent manager for web chat (TTL cleanup) |
| `src/agenticops/chat/preprocessor.py` | Shared message preprocessor: I#/R# refs, @file, file upload |
| `src/agenticops/chat/file_reader.py` | File content extraction (text, DOCX, PDF, images) |
| `src/agenticops/chat/send_to.py` | Shared `/send_to` command processor (CLI + Web + IM) |
| `src/agenticops/config.py` | Centralized `pydantic-settings` config (env vars with `AIOPS_` prefix) |
| `src/agenticops/models.py` | SQLAlchemy models (HealthIssue, FixPlan, Report, LocalDoc, IMAlias, ChatSession, ChatMessage, etc.) |
| `src/agenticops/graph/collectors.py` | AWS data collectors for graph compute enrichment (EC2, RDS, Lambda, EKS, ECS, ElastiCache, TG) |
| `src/agenticops/skills/__init__.py` | Agent Skills package init — exports all public functions |
| `src/agenticops/skills/loader.py` | Skill discovery, YAML parsing, XML generation, output rules, prompt helper |
| `src/agenticops/skills/security.py` | Three-tier security classification for shell + kubectl commands |
| `src/agenticops/skills/tools.py` | 3 @tool functions: activate_skill, read_skill_reference, list_skills |
| `src/agenticops/skills/execution.py` | 2 @tool functions: run_on_host (SSM/SSH), run_kubectl (EKS) |
| `src/agenticops/services/pipeline_service.py` | Auto-fix pipeline: RCA → SRE → Approve(L0/L1) → Execute |
| `src/agenticops/services/rca_service.py` | Auto-RCA trigger on HealthIssue creation |
| `src/agenticops/services/executor_service.py` | Background executor polling for pre-queued FixExecutions |
| `src/agenticops/services/resolution_service.py` | Post-resolution RAG pipeline + case distillation |
| `src/agenticops/services/notification_service.py` | Fire-and-forget auto-notifications on pipeline events |
| `src/agenticops/notify/im_config.py` | IM app YAML config + channel YAML config (ChannelConfig, load_channels, save_channel, mtime cache) |
| `src/agenticops/notify/notifier.py` | Multi-channel notification system (Slack, Email, SNS, Feishu, DingTalk, WeCom, Webhook) — reads from YAML only |
| `src/agenticops/chat/channel.py` | Shared `/channel` command processor (list, show, test, set) — CLI, Web, IM |
| `config/channels.yaml` | **Sole source of truth** for notification channels (gitignored, real config) |
| `config/channels.yaml.example` | Template for channels.yaml with `${VAR}` placeholders |
| `config/im-apps.yaml` | IM app credentials (gitignored) |
| `config/im-apps.yaml.example` | Template for im-apps.yaml with `${VAR}` placeholders |

### Agents (all in `src/agenticops/agents/`)

| Agent | Purpose |
|-------|---------|
| `main_agent.py` | Orchestrator — routes to sub-agents, exposes `create_main_agent()` |
| `scan_agent.py` | Resource discovery (EC2, RDS, Lambda, S3, ECS, EKS, DynamoDB, SQS, SNS, VPC, ...) |
| `detect_agent.py` | Health monitoring via CloudWatch alarms, metrics, z-score anomaly detection |
| `rca_agent.py` | Root cause analysis with knowledge base lookup |
| `sre_agent.py` | SRE assistant for operational queries |
| `executor_agent.py` | Fix plan execution (L0-L4 with approval gates) |
| `reporter_agent.py` | Report generation (daily/weekly/on-demand) |

### Frontend (React + TypeScript + Tailwind)

| Directory | Contents |
|-----------|----------|
| `src/agenticops/web/frontend/src/pages/` | 16 pages: Dashboard, Chat, Resources, Anomalies, AnomalyDetail, FixPlans, FixPlanDetail, Reports, ReportDetail, Network, Schedules, ScheduleDetail, Notifications, NotificationLogs, Accounts, AuditLog |
| `src/agenticops/web/frontend/src/hooks/` | 22 hooks (TanStack Query): useChat, useChatSessions, useChatSession, useSchedules, useNotifications, useResources, useFixPlans, useAnomalies, useStats, etc. |
| `src/agenticops/web/frontend/src/components/chat/` | 5 components: ChatInput, MessageList, SessionList, TokenMetrics, ToolCallChip |
| `src/agenticops/web/frontend/src/components/layout/` | AppShell, Sidebar, Header |
| `src/agenticops/web/frontend/src/api/` | `client.ts` (apiFetch), `types.ts` (all TypeScript interfaces) |

**Note**: `ChatContext` is defined in both `context.py` AND duplicated in `main.py` (~line 1568). Both must be kept in sync.

## API Endpoints (81 total)

| Group | Count | Base Path |
|-------|-------|-----------|
| Health Issues | 7 | `/api/health-issues` |
| Fix Plans | 6 | `/api/fix-plans` |
| Schedules | 7 | `/api/schedules` |
| Notifications | 7 | `/api/notifications` |
| Chat (SSE) | 5 | `/api/chat/sessions` |
| Reports | 5 | `/api/reports` |
| Resources | 5 | `/api/resources` |
| Network/Topology | 6 | `/api/topology`, `/api/vpc-topology` |
| Graph Engine | 12 | `/api/graph/vpc`, `/api/graph/region`, `/api/graph/multi-region` |
| SRE Analysis | 5 | `/api/graph/vpc/{id}/enriched`, `/api/graph/vpc/{id}/spof`, `/api/graph/vpc/{id}/capacity-risk`, `/api/graph/vpc/{id}/dependency-chain`, `/api/graph/vpc/{id}/change-simulation` |
| Anomalies (compat) | 5 | `/api/anomalies` |
| Accounts | 5 | `/api/accounts` |
| Audit Log | 2 | `/api/audit-log` |
| Stats/Health | 3 | `/api/stats`, `/api/health` |
| Auth | 3 | `/api/auth` |
| IM Aliases + Bots | 4 | `/api/im-aliases`, `/api/im/bots` |
| Local Docs | 2 | `/api/local-docs` |
| SPA | 1 | `/app/{path}` |

### Chat SSE Streaming

The web chat uses Server-Sent Events for real-time streaming:

```
POST /api/chat/sessions/{id}/messages
→ Accepts: application/json OR multipart/form-data (with file upload)
→ SSE events: text (per-token), tool_start, tool_end, done (with token usage), error
```

Each session gets its own `Agent` instance via `ChatSessionManager` (lazy creation, 30-min TTL cleanup).

### Chat Preprocessing Pipeline

All chat messages (CLI + Web) pass through `agenticops.chat.preprocessor.preprocess_message()`:

1. **@file/path resolution** (CLI only): `@/tmp/error.log` → reads file, wraps in `<attached_file>` XML block
2. **File upload injection** (Web only): uploaded file content → `<attached_file>` XML block
3. **I#N reference resolution**: `I#42` → queries HealthIssue DB → appends `<referenced_issue>` context
4. **R#N reference resolution**: `R#17` → queries AWSResource DB → appends `<referenced_resource>` context

### Headless Chat Mode

```bash
aiops chat "what is the status of my services?"   # positional arg
aiops chat -q "check health of prod"               # -q/--query flag
echo "scan us-east-1" | aiops chat                  # piped stdin
aiops chat "analyze I#42 and check R#17"            # with references
aiops chat "review this log @/tmp/error.log"        # with file attachment
aiops chat -d concise "quick status of prod"        # concise output
aiops chat --detail detailed "deep dive on I#42"    # detailed output
```

- `sys.stdout.isatty()` controls Rich vs plain text output
- Errors/warnings go to stderr; stdout is clean for piping

## Configuration (`config.py`)

All settings use `pydantic-settings` with `AIOPS_` env prefix. Defaults in code, optional `.env` override.

| Setting | Default | Description |
|---------|---------|-------------|
| `bedrock_model_id` | `global.anthropic.claude-sonnet-4-6-v1` | Default Bedrock model (Sonnet 4.6) for reasoning agents |
| `bedrock_model_id_cheap` | `global.anthropic.claude-haiku-4-5-20251001-v1:0` | Economy model (Haiku 4.5) for scan/detect/reporter |
| `bedrock_model_id_strong` | `global.anthropic.claude-opus-4-6-v1` | Strong model (Opus 4.6) reserved for complex scenarios |
| `bedrock_max_tokens` | `16384` | Max output tokens for all agents |
| `bedrock_window_size` | `40` | Sliding window conversation manager size |
| `bedrock_region` | `us-east-1` | AWS region for Bedrock |
| `cors_origins` | `""` | Comma-separated CORS origins (empty = dev-mode) |
| `cors_max_age` | `3600` | CORS preflight cache seconds |
| `executor_enabled` | `true` | Enable fix execution |
| `api_auth_enabled` | `false` | Enable API key auth middleware |
| `embedding_enabled` | `true` | Enable vector embeddings |
| `database_url` | `sqlite:///.../data/agenticops.db` | SQLite path |
| `skills_dir` | `PROJECT_ROOT / "skills"` | Directory containing Agent Skills packages |
| `skills_enabled` | `true` | Enable Agent Skills integration |
| `agent_output_detail` | `medium` | Default agent output detail level: concise, medium, or detailed |
| `auto_rca_enabled` | `true` | Auto-trigger RCA on new HealthIssue |
| `auto_fix_enabled` | `true` | Auto-fix pipeline: RCA → SRE → Approve → Execute |
| `notifications_enabled` | `true` | Auto-notifications on pipeline events |
| `executor_auto_approve_l0_l1` | `true` | Auto-approve L0/L1 fix plans |

## Graph Module

### Node Types (graph/types.py)

| Type | Category | Description |
|------|----------|-------------|
| VPC, SUBNET, ROUTE_TABLE, INTERNET_GATEWAY, NAT_GATEWAY | Network | Core VPC networking primitives |
| TRANSIT_GATEWAY, TGW_ATTACHMENT, PEERING, VPC_ENDPOINT | Network | Cross-VPC/cross-region connectivity |
| SECURITY_GROUP, LOAD_BALANCER | Network | Security and traffic management |
| EC2_INSTANCE, RDS_INSTANCE, LAMBDA_FUNCTION | Compute | Compute/service resources |
| EKS_CLUSTER, EKS_NODE, EKS_POD, EKS_SERVICE | Kubernetes | EKS topology (pod/service deferred) |
| ECS_CLUSTER, ECS_SERVICE, ECS_TASK | Containers | ECS topology |
| TARGET_GROUP, ELASTICACHE_CLUSTER | Data/Routing | ALB targets, caching |

### Edge Types

| Type | Style | Description |
|------|-------|-------------|
| CONTAINS, ROUTES_TO, ASSOCIATED_WITH, ATTACHED_TO | solid | Structural network relationships |
| PEERS_WITH, HOSTED_IN, REFERENCES, SERVES | solid/dashed | Connectivity and placement |
| RUNS_ON, MEMBER_OF | dotted | Compute-to-infrastructure relationships |
| TARGETS, CONNECTS_TO | solid/dashed | Service dependencies (TG → targets, SG-inferred) |

### SRE Algorithms (graph/algorithms.py)

| Algorithm | Input | Output | Description |
|-----------|-------|--------|-------------|
| `dependency_chain_analysis` | fault_node_id | DependencyChainResult | Reverse BFS — finds all upstream dependents |
| `detect_spof` | graph | SPOFReport | Articulation points + bridges |
| `capacity_risk_analysis` | threshold | CapacityRiskReport | Subnet IP exhaustion + EKS pod limits |
| `simulate_change` | edge_source, edge_target | ChangeSimulationResult | Before/after reachability diff |

### Collectors (graph/collectors.py)

| Function | AWS Calls | Returns |
|----------|-----------|---------|
| `collect_vpc_compute(region, vpc_id)` | EC2, RDS, Lambda, ELBv2, ElastiCache | ec2_instances, rds_instances, lambda_functions, target_groups, elasticache_clusters |
| `collect_eks_topology(region, cluster_name)` | EKS describe/list | cluster, nodegroups |
| `collect_ecs_topology(region, cluster_name)` | ECS describe/list | cluster, services, tasks |

## Skills Directory

```
skills/
├── ADDING_SKILLS.md      # How-to guide for adding new skills (zero code changes)
├── linux-admin/          # Linux sysadmin troubleshooting (process, disk, memory, network)
│   ├── SKILL.md
│   └── references/       # process-management.md, disk-io-analysis.md, memory-troubleshooting.md
├── network-engineer/     # CCIE-level networking (routing, firewall, TCP, VPN, MTU)
│   ├── SKILL.md
│   └── references/       # routing-troubleshooting.md, firewall-analysis.md, tcp-diagnostics.md
├── kubernetes-admin/     # K8s admin (pods, nodes, CNI, CoreDNS, PVC, HPA)
│   ├── SKILL.md
│   └── references/       # pod-troubleshooting.md, node-diagnostics.md, eks-networking.md
├── database-admin/       # RDS, DynamoDB, ElastiCache (slow queries, replication, deadlocks)
│   ├── SKILL.md
│   └── references/       # mysql-diagnostics.md, postgresql-diagnostics.md, dynamodb-patterns.md, elasticache-redis.md
├── elasticsearch/        # Elasticsearch/OpenSearch (cluster health, DSL, JVM, ILM, snapshots)
│   ├── SKILL.md
│   └── references/       # dsl-query-patterns.md, cluster-operations.md
├── monitoring/           # CloudWatch, Prometheus, SLI/SLO, alert fatigue
│   ├── SKILL.md
│   └── references/       # cloudwatch-best-practices.md, metric-selection-guide.md
├── log-analysis/         # CloudWatch Insights, pod logs, system logs, error patterns
│   ├── SKILL.md
│   └── references/       # cloudwatch-insights-queries.md, log-patterns.md
├── aws-compute/          # EC2, ECS, EKS, Lambda troubleshooting
│   ├── SKILL.md
│   └── references/       # ec2-troubleshooting.md, ecs-task-placement.md, lambda-optimization.md
├── aws-storage/          # S3, EBS, EFS, FSx troubleshooting
│   ├── SKILL.md
│   └── references/       # s3-access-troubleshooting.md, ebs-performance.md, efs-mount-issues.md
└── local-os-operator/    # Local file operations (read configs, tail logs, search files)
    └── SKILL.md          # YAML tools: field → dynamic tool registration on activation
```

## Closed-Loop Validation Roadmap (Active)

**Goal**: 4 weeks to validate 10 real incident cases with end-to-end auto-remediation on EKS Lab.
**Constraint**: All testing on VPC bastion host — no public endpoint exposure.

| Phase | Week | Status | Scope |
|-------|------|--------|-------|
| **Phase 0**: Cost + Detection Hardening | W1 前半 | **DONE** | Tiered models ($14→$3/cycle), fingerprint dedup, Prometheus/CW parsers, alert rules, K8s fix skills |
| **Phase 1**: EKS Lab + Cases 1-3 | W1 后半 + W2 | **DONE** | Deploy lab, OOM kill, Bad Image, Redis crash — 3/3 at 5/5 |
| **Phase 2**: Cases 4-10 + Pipeline Polish | W3 | **DONE** | DiskPressure, PodPending, Readiness, CoreDNS, PVC, HPA, ServiceCrash — 7/7 at 5/5 |
| **Phase 3**: Automation + Docs | W4 | **DONE** | `run-all-scenarios.sh`, `docs/cases/*.md`, 2 critical bug fixes, AlertEvent dedup |

**Result**: 10/10 cases at 5/5 — all acceptance criteria met (2026-03-06)
**Acceptance**: ≥7/10 auto-fix ✅ (10/10), ≤3min detect ✅ (~2min avg), ≤10min resolve ✅ (~6.3min avg), ≤$3/cycle ✅

**Key files**:
- `infra/eks-lab/scenarios/` — 10 case inject/verify scripts + `common.sh` + `run-all-scenarios.sh`
- `docs/cases/` — 10 case docs + cost report
- `metadata_tools.py` — `mark_fix_executed()` early return fix (Bug #1)
- `web/app.py` — `_process_webhook_alert()` AlertEvent dedup bypass for terminal issues (Bug #2)
- `infra/eks-lab/monitoring/alert-rules.yaml` — 10 PrometheusRule alerts
- `infra/eks-lab/monitoring/prometheus-values.yaml` — AlertManager webhook receiver
- `skills/kubernetes-admin/SKILL.md` — Fix/Remediation decision trees (8 paths)

## Recent Changes

### 2026-03-03: YAML-Only Channel Config (DB Eliminated)

**Architecture**: `config/channels.yaml` is now the **sole source of truth** for ALL notification channel configuration. The `notification_channels` DB table is no longer used for config reads/writes. `NotificationLog` remains in DB for audit.

**Channel YAML infrastructure** (`notify/im_config.py`):
- `ChannelConfig` dataclass: `name`, `channel_type`, `config`, `is_enabled`, `severity_filter`
- `load_channels()` / `get_channel(name)` — mtime-cached YAML reads
- `save_channel()` / `delete_channel()` — YAML writes with cache invalidation
- `_CHANNEL_RESERVED_KEYS` pattern: `type`, `enabled`, `severity_filter` are top-level; everything else → `config` dict
- Env var interpolation (`${VAR}`) via shared `_interpolate_env()`

**NotificationManager refactored** (`notify/notifier.py`):
- Removed: `NotificationChannel` DB model, `resolve_channel_config()`, `_IM_CHANNEL_TYPES`, `sync_im_channels_from_yaml()`
- `send_notification()` — loads channels from `load_channels()`, filters by name/enabled/severity
- `_log_notification()` — writes audit log to DB with `channel_name` (string)
- `test_channel(name)` — reads from `get_channel()` YAML
- `NotificationLog` model changed: `channel_id` → `channel_name` (with DB migration + backfill)

**API endpoints** (`web/app.py`) — 6 channel endpoints refactored:
- Routes changed from `/{channel_id}` (int) to `/{channel_name}` (string)
- All CRUD operations backed by YAML `save_channel()`/`delete_channel()`
- Response schema simplified: removed `id`, `created_at`, `updated_at`
- Logs endpoint: `channel_id` filter → `channel_name` filter

**`/channel` command** (`chat/channel.py`) — YAML-backed:
- Removed `_channel_sync()` subcommand (no longer needed)
- `_channel_show()` / `_channel_set()` use `im_config.get_channel()` / `save_channel()` directly
- `_channel_list()` reads from `load_channels()`

**Other changes**:
- `chat/send_to.py`: `resolve_target()` reads from YAML instead of DB
- `tools/metadata_tools.py`: `list_send_targets()` reads from YAML
- `models.py`: Migration adds `channel_name` column to `notification_logs`, backfills from old `channel_id` FK
- `config.py`: added `channels_config` setting (default: `PROJECT_ROOT / "config" / "channels.yaml"`)
- `.gitignore`: added `config/channels.yaml`

**Frontend** (types.ts, useNotifications.ts, Notifications.tsx, NotificationLogs.tsx):
- `NotificationChannel` interface: removed `id`, `created_at`, `updated_at`
- All hooks/mutations use `name` (string) instead of `id` (number)
- `NotificationLog` interface: `channel_id` → `channel_name`

**Config files**: `config/channels.yaml` (gitignored, real config), `config/channels.yaml.example` (committed template)

### 2026-03-02: Auto-Notifications + `/send_to` Chat Command

**Auto-Notifications** (`services/notification_service.py`, 7 trigger points):
- Fire-and-forget notifications at 7 pipeline event points via daemon threads (same pattern as `pipeline_service.py`)
- `notify_event()` — core function: checks `settings.notifications_enabled`, runs `NotificationManager.send_notification()` in daemon thread with new event loop
- 7 convenience functions: `notify_issue_created`, `notify_rca_completed`, `notify_fix_planned`, `notify_fix_approved`, `notify_execution_result`, `notify_report_saved`, `notify_schedule_result`
- Wired into: `metadata_tools.py` (5 triggers), `report_tools.py` (1), `scheduler.py` (2 — success/failure)
- Gated by `settings.notifications_enabled` (AIOPS_NOTIFICATIONS_ENABLED, default: true)

**New Models** (`models.py`):
- `LocalDoc` — tracks files written by `write_local_file` tool (file_path unique, file_type, size_bytes, created_by)
- `IMAlias` — maps friendly names to IM chat IDs (name unique, platform, chat_id, app_name)
- `write_local_file` now auto-registers LocalDoc records via `_register_local_doc()` helper in `file_tools.py`

**`/send_to` Command** (`chat/send_to.py`, CLI, Web, IM):
- Syntax: `/send_to <target> #R<id>, #D<id>, "text"`
- Target resolution: NotificationChannel (by name) → IMAlias (by name)
- Content resolution: `#R<id>` → Report content, `#D<id>` → LocalDoc file content, free text
- CLI: `_slash_send_to()` handler, registered as `send_to` and `sendto` in SLASH_COMMANDS
- Web: Intercepted in `api_send_chat_message()` before agent dispatch, returns SSE stream
- IM (app.py): Intercepted in `_handle_im_message()` before agent dispatch
- IM (feishu_ws.py): Intercepted in `_process_and_reply()` before agent dispatch

**API Endpoints** (5 new):
- `GET /api/im-aliases` — list all IM aliases
- `POST /api/im-aliases` — create IM alias
- `DELETE /api/im-aliases/{id}` — delete IM alias
- `GET /api/local-docs` — list tracked local docs
- `GET /api/local-docs/{id}` — get local doc detail

### 2026-03-02: Phase 0 — Tiered Models, Fingerprint Dedup, Prometheus Webhook, Alert Rules

**Tiered Model Configuration** (`config.py`, 3 agent files):
- `bedrock_model_id` default changed from Opus 4.6 → Sonnet 4.6
- New `bedrock_model_id_cheap` (Haiku 4.5) for detect_agent, scan_agent, reporter_agent
- New `bedrock_model_id_strong` (Opus 4.6) reserved for complex scenarios
- Expected cost: $14/cycle → ~$2-3/cycle (80% reduction)

**HealthIssue Fingerprint Deduplication** (`models.py`, `metadata_tools.py`):
- SHA-256 fingerprint of (source, resource_id, normalised title) with 5-minute dedup window
- New columns: `fingerprint`, `occurrence_count`, `first_seen`, `last_seen`
- DB auto-migration in `init_db()` for existing tables

**Prometheus + CloudWatch Alert Parsers** (`integrations/parsers.py`, `web/app.py`):
- `parse_prometheus()` — AlertManager webhook format (labels, annotations, fingerprint)
- `parse_cloudwatch()` — SNS notification format (AlarmName, NewStateValue, Trigger)
- `detect_source()` heuristics updated: Prometheus distinguished from Grafana by `labels.alertname`
- Webhook `valid_sources` expanded to 6: datadog, pagerduty, grafana, prometheus, cloudwatch, generic

**AlertManager + Alert Rules** (`infra/eks-lab/monitoring/`):
- `prometheus-values.yaml` — AlertManager webhook receiver → bastion VPC IP, route grouping, Watchdog silenced
- `alert-rules.yaml` — 10 PrometheusRule CRD alerts: KubePodCrashLooping, KubePodNotReady, KubeDeploymentReplicasMismatch, NodeNotReady, NodeDiskPressure, TargetDown, HighErrorRate, HighLatencyP99, KubePodOOMKilled, KubePVCPending

**Kubernetes Skill Enhancement** (`skills/kubernetes-admin/`):
- SKILL.md: 8 fix/remediation decision trees (OOM, ImagePull, ReplicasMismatch, NodeNotReady, CoreDNS, HPA, PVC, ServiceCrash)
- `references/pod-troubleshooting.md`: OOM remediation commands + ImagePullBackOff section

### 2026-03-01: Dynamic Skill-Based Tool Loading + local-os-operator Skill

**Dynamic Tool Registration** (`skills/loader.py`, `skills/tools.py`):
- Skills can now declare `tools:` in YAML frontmatter — list of dotted paths to `@tool` functions
- `activate_skill()` accepts Strands SDK auto-injected `agent` parameter
- On activation: resolves tool paths via `importlib`, registers them via `agent.tool_registry.process_tools()`
- Idempotent: skips tools already in registry (safe to activate same skill twice)
- `resolve_skill_tools(skill_name)` in `loader.py` — imports and returns `@tool` function objects
- `SkillMetadata.tools` field added to dataclass

**local-os-operator Skill** (`skills/local-os-operator/`):
- 5 dynamically registered tools: `read_local_file`, `tail_local_file`, `search_local_file`, `list_local_directory`, `file_stat`
- Security blocklists: SSH keys, AWS creds, `.env`, `.pem`, etc. (enforced by `tools/file_tools.py`)
- Decision trees: config file discovery, log investigation, IaC inspection, file metadata checks
- Tools NOT statically loaded — agents activate on demand via `activate_skill("local-os-operator")`

**Agent Prompt Updates** (SRE, Executor, RCA):
- Removed static `file_tools` imports and tool list entries from all 3 agents
- Updated LOCAL FILE sections to reference `activate_skill("local-os-operator")` for dynamic loading

### 2026-03-01: Auto-Fix Pipeline + Multi-Backend Executor + Tool Output Truncation

**Tool Output Truncation** (`tools/metadata_tools.py`):
- Root cause fix for "内容过大被截断" errors: metadata tools returned unbounded JSON, overflowing agent context window after 30+ tool calls
- Added `_truncate()` with `MAX_RESULT_CHARS=4000` (single records) and `MAX_LIST_RESULT_CHARS=6000` (list queries)
- All 8 `json.dumps` return sites wrapped with truncation; truncation message guides agent to use `get_*` with specific ID
- Reduced default query limits: `list_health_issues` 50→20, `get_managed_resources` 200→50
- Matches existing pattern in `aws_cli_tool.py` (2000/4000) and `skills/execution.py` (4000)

**Auto-Fix Pipeline** (`services/pipeline_service.py`, `metadata_tools.py`, `config.py`):
- End-to-end pipeline: RCA → SRE → Approve(L0/L1) → Execute → Resolve
- Three trigger hooks wired into metadata tools:
  - `save_rca_result()` → `trigger_auto_sre()` (SRE agent in daemon thread)
  - `save_fix_plan()` → `trigger_auto_approve()` (L0/L1 sync DB update → chains to execute)
  - `approve_fix_plan()` → `trigger_auto_execute()` (Executor agent in daemon thread)
- Three independent gates: `auto_fix_enabled` (master), `executor_auto_approve_l0_l1`, `executor_enabled`
- L2/L3 plans require human approval → pipeline pauses at `fix_planned` status
- On execution success: auto-resolve HealthIssue + trigger RAG pipeline (existing)

**Multi-Backend Executor** (`agents/executor_agent.py`):
- Executor Agent now supports AWS CLI + SSM/SSH host commands + kubectl
- TOOL SELECTION routes by step type (`action`/`runner_type` field) or command prefix inference
- SKILL ACTIVATION loads domain knowledge before host/kubectl execution
- 4 new tools: `run_on_host`, `run_kubectl`, `activate_skill`, `read_skill_reference`
- Dynamic output rules via `build_prompt_with_skills(prompt, agent_type="executor")`

### 2026-02-28: Configurable Agent Output Detail Level

**Core mechanism** (config.py, skills/loader.py):
- `agent_output_detail` pydantic setting (default: `medium`, env: `AIOPS_AGENT_OUTPUT_DETAIL`)
- `contextvars.ContextVar` holds runtime detail level; `get_detail_level()` / `set_detail_level()` helpers
- `VALID_DETAIL_LEVELS = ("concise", "medium", "detailed")`
- `_OUTPUT_RULES` dict — 3 level templates: concise (~500 tok), medium (~1500 tok), detailed (~4000 tok)
- `_RCA_ADDENDA` / `_SRE_ADDENDA` — agent-specific structure guidance per level
- `get_output_rules(agent_type)` reads ContextVar, returns combined rules
- `build_prompt_with_skills(base_prompt, agent_type="generic")` now injects dynamic output rules

**Agent changes** (rca_agent.py, sre_agent.py):
- Removed hardcoded `OUTPUT FORMAT RULES` blocks from both system prompts
- Both now call `build_prompt_with_skills(..., agent_type="rca"|"sre")` for dynamic injection

**CLI** (main.py, context.py):
- `ChatContext.detail_level` replaces `verbose` (boolean → tri-state string)
- `/detail [concise|medium|detailed]` slash command (cycles when no arg)
- `/verbose` redirects to `/detail` handler for backward compatibility
- `--detail / -d` flag on `aiops chat` command for headless mode
- ContextVar set before each agent call in both interactive and headless paths

**Web API** (app.py):
- `ChatMessageCreate.detail_level` optional field
- Extracted from JSON body or multipart form data
- ContextVar set before agent call in SSE generator

### 2026-02-28: Optimization Sprint — State Machine, API Auth, Code Cleanup

**HealthIssue State Machine** (`models.py`, `metadata_tools.py`, `app.py`):
- `VALID_ISSUE_STATUSES` — 9 valid states (open → resolved lifecycle)
- `_ISSUE_TRANSITIONS` — directed adjacency map of allowed transitions
- `validate_status_transition()` — raises `InvalidStatusTransition` on illegal moves
- Enforced in: `update_health_issue_status` tool + 2 API endpoints (returns 409 Conflict)

**API Authentication Middleware** (`config.py`, `app.py`):
- Opt-in via `AIOPS_API_AUTH_ENABLED=true` (default: false)
- `APIAuthMiddleware` gates all `/api/*` except public paths (`/api/health`, `/api/auth/*`)
- Uses existing `auth/` module (User, APIKey, Session models + AuthService)

**Code Cleanup** (`cli/main.py`):
- Removed duplicate `ChatContext` class (~67 lines) — import at line 65 was already correct
- Removed duplicate `ThinkingDisplay`/`ProgressTracker` (~279 lines) — `display.py` import at line 69 was already correct
- Net reduction: -203 lines

**Test Suite** (`tests/`):
- `test_state_machine.py` — 75 tests (transitions, validation, tool integration)
- `test_detail_level.py` — 31 tests (ContextVar, rules generation, ChatContext)
- Total: 108 new tests, all passing

### 2026-02-28: Multimodal Chat + Elasticsearch Skill

**Multimodal File Processing** (chat pipeline):
- Images (.png/.jpeg/.gif/.webp) and documents (.pdf/.docx/.csv/.xlsx etc.) sent as native Strands SDK `ContentBlock` instead of placeholder text
- `file_reader.py`: `IMAGE_FORMAT_MAP`, `DOCUMENT_FORMAT_MAP`, `is_image_file()`, `is_document_file()`, `read_file_as_image_bytes()`, `read_upload_image_bytes()`, `read_file_as_document_bytes()`, `read_upload_document_bytes()`
- `preprocessor.py`: returns `str` for text-only (backward compat), `list[ContentBlock]` when media present
- `app.py`: web upload routing branches by file type (image/document/text)
- `main.py`: UX log "Attached N media file(s) for analysis"
- Test suite: `tests/test_multimodal.py` (37 tests)

**Elasticsearch Skill** (skills/elasticsearch/):
- `SKILL.md`: cluster health (red/yellow), shard allocation, DSL optimization, JVM heap, circuit breakers, ILM, snapshot/restore, AWS OpenSearch specifics
- `references/dsl-query-patterns.md`: full-text, filtering, bool, aggregations, anti-patterns, SRE queries
- `references/cluster-operations.md`: rolling restart, scaling, index management, thread pool tuning

**Skills Documentation** (skills/ADDING_SKILLS.md):
- Step-by-step guide for adding new skills (zero code changes)
- YAML frontmatter reference, SKILL.md template, agent routing table

### 2026-02-27: Agent Skills Integration

**Skills Python Layer** (src/agenticops/skills/):
- `loader.py` — SKILL.md discovery, YAML frontmatter parsing, `<available_skills>` XML generation, `build_prompt_with_skills()` prompt helper
- `security.py` — Three-tier shell + kubectl command classification (readonly/write/blocked), mirrors aws_cli_tool.py pattern
- `tools.py` — 3 @tool functions: `list_skills`, `activate_skill`, `read_skill_reference` (progressive disclosure)
- `execution.py` — 2 @tool functions: `run_on_host` (SSM/SSH), `run_kubectl` (EKS) with security enforcement

**Config** (config.py):
- `skills_dir` (default: PROJECT_ROOT / "skills") and `skills_enabled` (default: true)

**Agent Integration** (3 agents modified):
- RCA agent: skills XML in prompt + activate_skill, read_skill_reference, run_on_host, run_kubectl
- SRE agent: same as RCA
- Main agent: skills XML in prompt + list_skills, activate_skill, read_skill_reference (NO execution tools — pure router)
- Main agent routing rule 9: host-level troubleshooting → dispatch to rca_agent or sre_query
- Main agent routing rule 9.5: skills listing and activation

**Skill Packages** (skills/):
- 9 domain skills: linux-admin, network-engineer, kubernetes-admin, database-admin, elasticsearch, monitoring, log-analysis, aws-compute, aws-storage
- Each: SKILL.md with YAML frontmatter + references/*.md deep-dive files
- ~900 tokens added to system prompts (available_skills XML); skill body loaded on demand (~3-5K tokens)
- Guide: `skills/ADDING_SKILLS.md` — template and step-by-step for adding new skills (zero code changes)

### 2026-02-26: SRE Analysis & Extended Topology Graph

**Graph Compute Enrichment** (graph/types.py, graph/engine.py, graph/collectors.py):
- 12 new NodeTypes (EC2, RDS, Lambda, EKS cluster/node/pod/service, ECS cluster/service/task, TargetGroup, ElastiCache)
- 4 new EdgeTypes (RUNS_ON, TARGETS, CONNECTS_TO, MEMBER_OF)
- 3 collector functions bridge AWS APIs to graph dicts (decoupled from engine)
- 3 enrich_with_* methods on InfraGraph: compute, EKS, ECS
- SG-inferred CONNECTS_TO edges between compute nodes

**SRE Algorithms** (graph/algorithms.py):
- `dependency_chain_analysis()` — reverse BFS from fault node
- `detect_spof()` — articulation points + bridges
- `capacity_risk_analysis()` — subnet IP + EKS pod capacity
- `simulate_change()` — edge removal reachability diff

**API Endpoints** (graph/api.py):
- `GET /api/graph/vpc/{id}/enriched` — VPC graph with compute resources
- `POST /api/graph/vpc/{id}/dependency-chain` — fault dependency chain
- `GET /api/graph/vpc/{id}/spof` — single points of failure
- `GET /api/graph/vpc/{id}/capacity-risk` — capacity risks
- `POST /api/graph/vpc/{id}/change-simulation` — edge removal simulation

**Agent Tools** (graph/tools.py, sre_agent.py, main_agent.py):
- 4 new @tool functions: analyze_dependency_chain, detect_single_points_of_failure, analyze_capacity_risk, simulate_edge_removal
- SRE agent updated with new tools + system prompt
- Main agent updated with detect_single_points_of_failure + analyze_capacity_risk + routing rule 8.5

**Frontend** (6 new node components, SreAnalysisPanel, enriched toggle):
- 12 new ReactFlow node types with color-coded components
- SRE Analysis Panel: SPOF detection, capacity risk, dependency chain, change simulation
- Enriched graph toggle on Network page

### 2026-02-26: Chat Enhancements — Headless Mode, File Input, References

**Headless Chat Mode** (`cli/main.py`):
- `aiops chat "query"` / `aiops chat -q "query"` — single-shot mode, print response and exit
- Pipe support: `echo "query" | aiops chat` — detects non-interactive stdin
- `_run_headless()` — Rich output for TTY, plain text for pipes (errors to stderr)
- Token usage summary printed after headless response

**@file/path CLI Input** (`chat/preprocessor.py`, `chat/file_reader.py`):
- `@/path/to/file` in messages → reads file content, injects as `<attached_file>` XML block
- Supports: .txt, .log, .md, .json, .yaml, .csv, .py, .sh, .pdf, .docx, images
- PDF via pymupdf/pypdf (optional), DOCX via python-docx (optional), 512KB text limit
- File refs extracted and removed from user text before sending to agent

**Web Chat File Upload** (`web/app.py`, `ChatInput.tsx`, `useChat.ts`):
- `POST /api/chat/sessions/{id}/messages` now accepts `multipart/form-data` with file field
- ChatInput: paperclip button + hidden file input + attachment indicator chip
- useChat: branches between JSON and FormData based on file presence
- ChatMessage model: new `attachments` JSON column (auto-migrated)
- MessageList: renders attachment badges on user messages

**I#/R# Reference Resolution** (`chat/preprocessor.py`, `metadata_tools.py`, `main_agent.py`):
- `I#42` → queries HealthIssue by ID → appends `<referenced_issue>` context block
- `R#17` → queries AWSResource by ID → appends `<referenced_resource>` context block
- New tool: `get_resource_by_id(resource_id)` in metadata_tools (mirrors `get_health_issue`)
- Main agent system prompt updated with CONTEXT BLOCKS section
- Preprocessing shared by both CLI and Web via `preprocess_message()`

**New files**: `src/agenticops/chat/__init__.py`, `chat/preprocessor.py`, `chat/file_reader.py`
**Dependencies**: `python-multipart>=0.0.7` (required), `python-docx>=1.0.0` + `pymupdf>=1.24.0` (optional `[files]`)

### 2025-02-14: Chat UI Experience Optimization

**Changes** (`main.py` + `context.py`):
- Smart output truncation with `print_with_truncation()` (terminal-aware)
- Removed fake thinking animation (no `time.sleep()`)
- Simplified response display (Rule separator instead of Panel borders)
- `/pager auto|on|off|<N>`, `/less` with markdown rendering

### 2026-02-22: Chat + Backend API Improvements

**Changes** (`main.py` + `app.py`):
- Spinner animation fix (braille cycle: `_DynamicRenderable` + Rich `Live`)
- Token tracking from Strands `AgentResult.metrics`
- 27 new API endpoints (HealthIssue, FixPlan, Schedule, Notification)
- Anomaly → HealthIssue migration (legacy URLs preserved)

### 2026-02-26: Agent Hardening + Streaming Web Chat + Frontend Expansion

**Agent token overflow fix** (all 7 agents):
- Added `max_tokens=settings.bedrock_max_tokens` (8192) to all `BedrockModel` instances
- Added `SlidingWindowConversationManager(window_size=settings.bedrock_window_size, per_turn=True)` to all agents
- Centralized to `config.py` — no more hardcoded values

**Backend hardening** (`app.py`):
- Production CORS from `settings.cors_origins` (was dev-only wildcard)
- Pagination standardized across 7 list endpoints (`settings.default_list_limit` / `settings.max_list_limit`)
- Enhanced `/api/health` — checks DB connectivity, AWS credentials (STS), disk space; returns `healthy`/`degraded`/`unhealthy`

**Streaming web chat** (new feature):
- `session_manager.py` — `ChatSessionManager` with per-session `Agent` instances, lazy creation, TTL cleanup (30 min), thread-safe
- `models.py` — `ChatSession` + `ChatMessage` SQLAlchemy models (auto-created by `init_db()`)
- `app.py` — 5 chat endpoints with SSE streaming via `sse-starlette`
- `pyproject.toml` — Added `sse-starlette>=2.0.0` dependency

**Frontend pages** (new):
- Schedules: list page with CRUD modals + detail page with execution history + "Run Now"
- Notifications: channel list with CRUD + test-send + log viewer with filters
- Chat: session sidebar + message bubbles + SSE streaming + tool call chips + token metrics
- Sidebar: added Chat (chat icon), Schedules (calendar), Notifications (bell) nav items
- Router: 8 new lazy-loaded routes

## Git & GitHub

- Repo: https://github.com/LiboMa/agenticops-chat (private)
- Branch: `main`

## Build & Test

```bash
# Backend syntax check
cd /path/to/AgenticOps
python3 -m py_compile src/agenticops/web/app.py
python3 -m py_compile src/agenticops/web/session_manager.py
python3 -m py_compile src/agenticops/models.py
python3 -m py_compile src/agenticops/config.py
python3 -m py_compile src/agenticops/agents/main_agent.py

# Frontend type check + build
cd src/agenticops/web/frontend
npx tsc --noEmit
npm run build

# Run CLI chat (interactive)
aiops chat

# Run CLI chat (headless)
aiops chat "check health of prod"
aiops chat -q "scan us-east-1"
aiops chat -d concise "quick status"
echo "list issues" | aiops chat

# Run API server
uvicorn agenticops.web.app:app --reload --port 8000

# Verify API:
# curl http://localhost:8000/api/health
# curl http://localhost:8000/api/health-issues
# curl http://localhost:8000/api/fix-plans
# curl http://localhost:8000/api/schedules
# curl http://localhost:8000/api/notifications/channels
# curl http://localhost:8000/api/chat/sessions
# curl http://localhost:8000/api/anomalies  (legacy compat)
# curl http://localhost:8000/api/stats

# Test web file upload:
# curl -X POST http://localhost:8000/api/chat/sessions/{id}/messages \
#   -F "content=analyze this log" -F "file=@/tmp/error.log"

# Install dependencies
# uv sync  OR  pip install sse-starlette>=2.0.0 python-multipart>=0.0.7
# Optional: pip install python-docx pymupdf  (for DOCX/PDF support)
```
