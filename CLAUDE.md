# AgenticOps Development Session Notes

## Project Overview

AgenticOps (`aiops`) — CLI + Web AI operations assistant with multi-agent architecture (Strands SDK on AWS Bedrock). Provides `aiops chat` interactive REPL, a React web dashboard with streaming chat, resource scanning, anomaly detection, fix planning, and reporting across AWS accounts.

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
- **All 7 agents** use centralized config: `settings.bedrock_model_id`, `settings.bedrock_max_tokens`, `settings.bedrock_window_size`
- **Conversation management**: `SlidingWindowConversationManager(window_size=40, per_turn=True)` on all agents to prevent `MaxTokensReachedException`

## Key Files

### Backend

| File | Purpose |
|------|---------|
| `src/agenticops/cli/main.py` | Main CLI entry point (~3750 lines), chat loop, slash commands |
| `src/agenticops/cli/context.py` | `ChatContext` class — chat session state |
| `src/agenticops/cli/display.py` | `ThinkingDisplay` class — spinner/progress; `TokenUsage` class |
| `src/agenticops/cli/formatters.py` | Table styles, markdown/json rendering helpers |
| `src/agenticops/web/app.py` | FastAPI backend (~2370 lines), 75 endpoints |
| `src/agenticops/web/session_manager.py` | Per-session agent manager for web chat (TTL cleanup) |
| `src/agenticops/chat/preprocessor.py` | Shared message preprocessor: I#/R# refs, @file, file upload |
| `src/agenticops/chat/file_reader.py` | File content extraction (text, DOCX, PDF, images) |
| `src/agenticops/config.py` | Centralized `pydantic-settings` config (env vars with `AIOPS_` prefix) |
| `src/agenticops/models.py` | SQLAlchemy models (HealthIssue, FixPlan, Report, ChatSession, ChatMessage, etc.) |
| `src/agenticops/graph/collectors.py` | AWS data collectors for graph compute enrichment (EC2, RDS, Lambda, EKS, ECS, ElastiCache, TG) |
| `src/agenticops/skills/__init__.py` | Agent Skills package init — exports all public functions |
| `src/agenticops/skills/loader.py` | Skill discovery, YAML parsing, XML generation, prompt helper |
| `src/agenticops/skills/security.py` | Three-tier security classification for shell + kubectl commands |
| `src/agenticops/skills/tools.py` | 3 @tool functions: activate_skill, read_skill_reference, list_skills |
| `src/agenticops/skills/execution.py` | 2 @tool functions: run_on_host (SSM/SSH), run_kubectl (EKS) |

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

## API Endpoints (75 total)

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
```

- `sys.stdout.isatty()` controls Rich vs plain text output
- Errors/warnings go to stderr; stdout is clean for piping

## Configuration (`config.py`)

All settings use `pydantic-settings` with `AIOPS_` env prefix. Defaults in code, optional `.env` override.

| Setting | Default | Description |
|---------|---------|-------------|
| `bedrock_model_id` | `global.anthropic.claude-opus-4-6-v1` | Bedrock model ID |
| `bedrock_max_tokens` | `8192` | Max output tokens for all agents |
| `bedrock_window_size` | `40` | Sliding window conversation manager size |
| `bedrock_region` | `us-east-1` | AWS region for Bedrock |
| `cors_origins` | `""` | Comma-separated CORS origins (empty = dev-mode) |
| `cors_max_age` | `3600` | CORS preflight cache seconds |
| `executor_enabled` | `false` | Enable fix execution |
| `embedding_enabled` | `true` | Enable vector embeddings |
| `database_url` | `sqlite:///.../data/agenticops.db` | SQLite path |
| `skills_dir` | `PROJECT_ROOT / "skills"` | Directory containing Agent Skills packages |
| `skills_enabled` | `true` | Enable Agent Skills integration |

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
├── monitoring/           # CloudWatch, Prometheus, SLI/SLO, alert fatigue
│   ├── SKILL.md
│   └── references/       # cloudwatch-best-practices.md, metric-selection-guide.md
├── log-analysis/         # CloudWatch Insights, pod logs, system logs, error patterns
│   ├── SKILL.md
│   └── references/       # cloudwatch-insights-queries.md, log-patterns.md
├── aws-compute/          # EC2, ECS, EKS, Lambda troubleshooting
│   ├── SKILL.md
│   └── references/       # ec2-troubleshooting.md, ecs-task-placement.md, lambda-optimization.md
└── aws-storage/          # S3, EBS, EFS, FSx troubleshooting
    ├── SKILL.md
    └── references/       # s3-access-troubleshooting.md, ebs-performance.md, efs-mount-issues.md
```

## Recent Changes

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
- 8 domain skills: linux-admin, network-engineer, kubernetes-admin, database-admin, monitoring, log-analysis, aws-compute, aws-storage
- Each: SKILL.md with YAML frontmatter + references/*.md deep-dive files
- ~800 tokens added to system prompts (available_skills XML); skill body loaded on demand (~3-5K tokens)

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
