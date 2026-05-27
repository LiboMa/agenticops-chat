# AgenticOps

Agent-First Cloud Operations Platform — multi-agent AI operations with interactive CLI, React dashboard, IM integration, and autonomous remediation.

> **Version**: 1.0.1 | **Release Notes**: [docs/MVP-1.0.1-RELEASE.md](docs/MVP-1.0.1-RELEASE.md) | [v1.0.0](docs/MVP-1.0.0-RELEASE.md)

## Overview

AgenticOps (`aiops`) uses 7 specialized AI agents (built on [Strands Agents SDK](https://github.com/strands-agents/strands-agents) + AWS Bedrock Claude 4.5/4.6) to scan, monitor, detect, analyze, and remediate issues across AWS infrastructure — fully automated, from alert to resolution.

**Three access points**: CLI (`aiops chat`), React Web Dashboard, IM Bots (Feishu/Slack/DingTalk/WeCom)

## Key Capabilities

| Capability | Description |
|------------|-------------|
| **Scan** | 20+ AWS service types: EC2, Lambda, RDS, S3, ECS, EKS, DynamoDB, SQS, SNS, VPCs, subnets, SGs, route tables, NAT/TGW, Load Balancers |
| **Monitor & Detect** | CloudWatch alarms/metrics, Z-score anomaly detection, Prometheus/CloudWatch/Datadog webhook intake |
| **Root Cause Analysis** | LLM-powered RCA with CloudTrail correlation, network topology, Knowledge Base search |
| **Auto-Fix Pipeline** | HealthIssue → RCA → SRE → Approve(L0/L1) → Execute → Resolve — fully autonomous for low-risk fixes |
| **Agent Skills** | 15 domain skills with self-improvement: auto-creation from resolved cases, LLM-driven refinement, draft/promote workflow |
| **Agent Metrics** | Per-agent and per-model token consumption tracking, call logs, trace timeline |
| **Network Topology** | VPC graph engine with SPOF detection, capacity risk, dependency chain, change simulation |
| **Knowledge Base** | Hybrid vector (Titan V2) + keyword search; auto-distills resolved cases into reusable SOPs |
| **Report** | Daily/weekly/incident/inventory reports with multi-channel distribution |
| **Scheduled Pipelines** | Cron-based task scheduling: FullScan, Monitoring, DailyReport, HealthPatrol, AgentChain (prompt-driven) |
| **Notify** | Slack, Email/SES, SNS, Feishu, DingTalk, WeCom, Webhook — YAML-configured |
| **IM Bots** | Feishu/Slack WebSocket bots with alert channel routing (agent-verified, not regex) |
| **MCP Servers** | Claude Desktop-compatible MCP integration — manage via Chat/CLI/Web, hot-reload, graceful degradation |
| **Dynamic Models** | Bedrock API auto-discovery of available Claude models (cached), per-agent assignment, CLI/Web switching |

## Multi-Agent Architecture

```
CLI (aiops chat)  ──┐
                    ├──► Main Agent (orchestrator) ──► Sub-Agents
Web Dashboard ──────┤         │
  (React + SSE)     │         ├──► Scan Agent ──► AWS service APIs
IM Bots ────────────┘         ├──► Detect Agent ──► CloudWatch, Prometheus
  (Feishu/Slack)              ├──► RCA Agent ──► CloudTrail, KB, Skills
                              ├──► SRE Agent ──► Fix plan generation (READ-ONLY)
                              ├──► Executor Agent ──► AWS CLI, SSM/SSH, kubectl
                              └──► Reporter Agent ──► Reports, KB distillation
```

| Agent | Model Tier | Role |
|-------|------------|------|
| **Main** | Opus 4.6 | Pure router — dispatches to specialists |
| **RCA** | Opus 4.6 | Root cause analysis with Skills + KB |
| **SRE** | Opus 4.6 | Fix plan generation (never executes) |
| **Executor** | Sonnet 4.6 | Multi-backend execution (AWS/SSM/kubectl) |
| **Scan** | Sonnet 4.6 | Resource discovery |
| **Detect** | Sonnet 4.6 | Health monitoring + anomaly detection |
| **Reporter** | Haiku 4.5 | Report generation (cost-optimized) |

Per-agent model overrides via `config/settings.yaml` or `AIOPS_AGENT_{NAME}_MODEL_ID` env vars.
Available models fetched dynamically from Bedrock (`/api/models`). Switch via CLI `/model` or Web Settings.

### Auto-Fix Pipeline

```
Alert ──► HealthIssue ──► RCA Agent ──► SRE Agent ──► Auto-Approve (L0/L1) ──► Executor ──► Resolve
                                                       ↓ L2/L3: Human Approval
```

**Three independent gates**: `auto_fix_enabled` (master), `executor_auto_approve_l0_l1`, `executor_enabled`

**FixPlan dedup**: One issue → one active plan. Draft=update-in-place, Locked=reject, Terminal=allow new.

### HealthIssue Lifecycle

```
open → investigating → acknowledged → root_cause_identified → fix_planned
  → fix_approved → fix_executing → fix_executed → resolved
```

State machine enforced — invalid transitions return 409.

## Quick Start

### 1. Install

```bash
pip install -e .
# Optional cloud backends:
pip install -e ".[cloud]"    # pgvector + psycopg2
```

### 2. Initialize (3 options)

```bash
# Interactive guided setup
aiops init

# Non-interactive local setup
aiops init --yes

# Zero-prompt from JSON config
aiops init --config setup.json

# One-click: init + start + optional scan
aiops quickstart --yes
```

### 3. Start Services

```bash
# Service mode (background daemon)
aiops service start

# Or direct web dashboard
aiops web
# Dashboard at http://localhost:8000
```

### 4. Interactive Chat

```bash
# Interactive REPL with 30+ slash commands
aiops chat

# Headless mode
aiops chat "check health of prod"
aiops chat -q "scan us-east-1" -d concise
echo "list issues" | aiops chat

# With file attachment
aiops chat "analyze this log @/tmp/error.log"

# With issue/resource references
aiops chat "deep dive on I#42 and check R#17"
```

### 5. Basic Operations

```bash
aiops run scan --services EC2,Lambda,RDS,S3
aiops run detect
aiops issues
aiops run analyze 1
aiops run report --type daily
```

## CLI Reference

### Core Commands

| Command | Description |
|---------|-------------|
| `aiops init [--config FILE]` | Initialize — guided wizard or JSON config |
| `aiops quickstart [--yes]` | One-click: init + start + optional scan |
| `aiops chat [QUERY] [-d LEVEL] [-f FOCUS]` | Interactive/headless AI chat |
| `aiops service start\|stop\|status\|restart\|logs` | Background service management |
| `aiops web [--host H] [--port P]` | Launch web dashboard |
| `aiops issues [--severity S] [--status S]` | List health issues |
| `aiops issue <id>` | Show issue detail |
| `aiops arch [-o FORMAT]` | System architecture (tree/markdown/json) |
| `aiops export <entity> [-o FORMAT]` | Export data |
| `aiops version` | Show version |

### CRUD Commands

```bash
aiops get accounts|resources|issues|reports|schedules|channels
aiops describe account|resource|issue|report <id>
aiops create account|schedule|channel <name> [options]
aiops update account|issue|schedule <id> [options]
aiops delete account|schedule <id>
aiops run scan|detect|analyze|report|schedule|notify [options]
```

### Chat Slash Commands (30+)

```
/help                    Show all commands
/scan                    Scan resources
/detect                  Run detection
/analyze <id>            Run RCA
/fix <id>                Generate fix plan
/approve <id>            Approve fix plan
/execute <id>            Execute approved plan
/focus <categories>      Set scan focus (computing,networking,databases,...)
/detail concise|medium|detailed  Output detail level
/model opus|sonnet|haiku Runtime model switch
/skill list|activate     Agent Skills management
/workflow full-scan|daily|incident  Multi-step workflows
/channel list|show|test|set  Notification channel management
/send_to <target> <content>  Send to IM/notification channel
/tokens                  Token usage stats
/export                  Export data
```

## Web Dashboard

React SPA with 13 pages, served by FastAPI at `http://localhost:8000`.

**Tech stack**: React 18, TypeScript, Tailwind CSS, TanStack Query, Vite

| Page | Description |
|------|-------------|
| **Dashboard** | Overview stats, critical issues, recent activity |
| **Chat** | SSE streaming chat with file upload, session management |
| **Issues & Plans** | Health issues + fix plans in unified view with severity/status filtering |
| **Issue Detail** | Issue detail + pipeline timeline + RCA + action bar |
| **Resources** | AWS resource inventory with type/region filtering |
| **Resource Detail** | Resource metadata, tags, related issues |
| **Schedules** | CRUD + execution history + "Run Now" + cron builder |
| **Schedule Detail** | Execution logs, pipeline config |
| **Reports** | Report browser by type (daily/incident/inventory) |
| **Agent Metrics** | Per-agent & per-model token consumption, call logs, trace timeline |
| **Skills** | Skill catalog with domain filtering, draft/published status |
| **Skill Detail** | Markdown viewer, inline editor, LLM improve, review diff, promote |
| **Settings** | Runtime config, MCP servers, model presets, notification channels |

## API Reference

80+ REST API endpoints served by FastAPI. Full OpenAPI docs at `http://localhost:8000/docs`.

| Category | Base Path | Count |
|----------|-----------|-------|
| Health Issues | `/api/health-issues` | 8 |
| Fix Plans | `/api/fix-plans` | 6 |
| Chat (SSE) | `/api/chat/sessions` | 5 |
| Resources | `/api/resources` | 5 |
| Schedules | `/api/schedules` | 7 |
| Notifications | `/api/notifications` | 7 |
| Agent Logs/Metrics | `/api/agent-logs` | 3 |
| Skills | `/api/skills` | 7 |
| Graph/Topology | `/api/graph` | 12 |
| Accounts | `/api/accounts` | 5 |
| Auth | `/api/auth` | 3 |
| Audit | `/api/audit` | 3 |
| Settings/MCP | `/api/settings` | 8 |
| Stats/Health | `/api/stats`, `/api/health` | 3 |
| IM/Webhooks | `/api/im`, `/api/webhooks` | 8+ |

## Agent Skills

15 domain skills loaded on demand (~636 tokens in system prompt, ~3-5K per activation):

| Skill | Domain |
|-------|--------|
| `linux-admin` | Process, disk, memory, network diagnostics |
| `network-engineer` | CCIE-level routing, firewall, TCP, VPN, MTU |
| `kubernetes-admin` | Pods, nodes, CNI, CoreDNS, PVC, HPA |
| `database-admin` | RDS, DynamoDB, ElastiCache, slow queries |
| `elasticsearch` | Cluster health, DSL, JVM, ILM, snapshots |
| `monitoring` | CloudWatch, Prometheus, SLI/SLO |
| `log-analysis` | CloudWatch Insights, pod/system logs |
| `aws-compute` | EC2, ECS, EKS, Lambda troubleshooting |
| `aws-storage` | S3, EBS, EFS, FSx troubleshooting |
| `local-os-operator` | Local file read/search/tail (dynamic tools) |
| `web-research` | Public URL fetch, SSL checks, service status pages |
| `distributed-tracing` | X-Ray, OpenTelemetry, trace correlation |
| `document-analysis` | PDF/doc parsing, report generation |
| `notification-operator` | Multi-channel notification routing and delivery |
| `security-engineer` | IAM, SecurityHub, GuardDuty, compliance checks |

**Self-improving skills**: Skills auto-create from resolved cases and improve via LLM refinement. Draft → Review (diff) → Promote workflow in the web UI.

Add new skills with zero code changes — see `skills/ADDING_SKILLS.md`.

## Graph Engine

NetworkX-based infrastructure graph with SRE analysis algorithms:

| Algorithm | Purpose |
|-----------|---------|
| `dependency_chain_analysis` | Reverse BFS — all upstream dependents of a fault node |
| `detect_spof` | Articulation points + bridges |
| `capacity_risk_analysis` | Subnet IP exhaustion + EKS pod limits |
| `simulate_change` | Before/after reachability diff |

12 compute node types (EC2, RDS, Lambda, EKS, ECS, ElastiCache, etc.) with SG-inferred connectivity edges.

## Dual Alert Intake

| Pipeline | Flow | LLM Cost |
|----------|------|----------|
| **Webhook** | Prometheus/CloudWatch/Datadog → `alert_processor` → HealthIssue → RCA pipeline | None |
| **IM Agent** | IM message → Main Agent (5-step verification) → `create_health_issue` → same pipeline | Yes |

HealthIssue fingerprint (SHA-256) prevents duplicates across both pipelines.

## Configuration

Primary config: `config/settings.yaml` (YAML, single source of truth).

**Priority**: env vars (`AIOPS_*`) > `.env` file > `settings.yaml` > Python Field defaults.

| Variable | Default | Description |
|----------|---------|-------------|
| `AIOPS_BEDROCK_MODEL_ID` | `global.anthropic.claude-opus-4-6-v1` | Default model (Opus 4.6) |
| `AIOPS_BEDROCK_MODEL_ID_CHEAP` | `...claude-haiku-4-5-20251001-v1:0` | Economy model (Haiku 4.5) |
| `AIOPS_BEDROCK_REGION` | `us-east-1` | AWS Bedrock region |
| `AIOPS_DATABASE_URL` | `sqlite:///...agenticops.db` | Database URL |
| `AIOPS_AUTO_FIX_ENABLED` | `true` | Auto-fix pipeline master switch |
| `AIOPS_AUTO_RCA_ENABLED` | `true` | Auto-trigger RCA on new issues |
| `AIOPS_EXECUTOR_AUTO_APPROVE_L0_L1` | `true` | Auto-approve low-risk plans |
| `AIOPS_EXECUTOR_ENABLED` | `true` | Enable fix execution |
| `AIOPS_NOTIFICATIONS_ENABLED` | `true` | Auto-notifications |
| `AIOPS_SKILLS_ENABLED` | `true` | Agent Skills integration |
| `AIOPS_SCAN_FOCUS` | `all` | Resource categories filter |
| `AIOPS_AGENT_OUTPUT_DETAIL` | `medium` | Output detail level |
| `AIOPS_DEPLOYMENT_PROFILE` | `local` | `local` or `cloud` |
| `AIOPS_BEDROCK_CACHE_ENABLED` | `true` | Prompt caching on all agents |
| `AIOPS_MCP_SERVERS_CONFIG` | `config/mcp-servers.json` | MCP servers config path |

## Validated: 10/10 Cases Passed

Closed-loop validation on EKS Lab (2026-03-06):

| Metric | Target | Actual |
|--------|--------|--------|
| Auto-fix rate | >=7/10 | **10/10** |
| Detection time | <=3 min | **~2 min** |
| MTTR | <=10 min | **~6.3 min** |
| Cost/cycle | <=$3 | **~$2-3** |

Cases: OOM Kill, Bad Image, Network Policy, DiskPressure, Pod Pending, Unhealthy Targets, CoreDNS Down, PVC Pending, HPA Maxed, Service Deleted.

## Project Structure

```
src/agenticops/
├── agents/          # 7 Strands agents (main, scan, detect, rca, sre, executor, reporter)
├── tools/           # Agent tools (metadata, AWS CLI, web, notification, cloudwatch)
├── services/        # Pipeline services (auto-fix, RCA, notifications, events, resolution)
├── graph/           # Infrastructure graph engine + SRE algorithms
├── skills/          # Skill loader, security, execution, improvement store
├── kb/              # Knowledge Base (vector store: SQLite/pgvector/S3)
├── cli/             # CLI entry + chat + init wizard + display
├── web/             # FastAPI backend + React SPA frontend
├── chat/            # Message preprocessing, file reader, /send_to, /channel
├── notify/          # Multi-channel notifications (YAML config)
├── im/              # IM bots (Feishu/Slack WebSocket)
├── integrations/    # Alert processor, source parsers
├── pipeline/        # Pipeline orchestrator, health patrol, presets
├── storage/         # Storage backends (local/S3)
├── scanner/         # Resource scanning engine
├── scan/            # AWS service scanner + region discovery
├── scheduler/       # Cron-based task scheduling
├── monitor/         # CloudWatch metrics collector
├── auth/            # Authentication (JWT + API keys)
├── audit/           # Audit trail service
├── models.py        # SQLAlchemy ORM models
└── config.py        # Pydantic settings (AIOPS_ env prefix)

skills/              # 15 domain skill packages (SKILL.md + references/)
config/              # settings.yaml, channels.yaml, im-apps.yaml, mcp-servers.json
iac/
└── deploy-sg/       # Terraform: CloudFront → ALB → EC2 (Singapore)
infra/
├── cloud-deploy/    # CloudFormation template + deploy script
└── eks-lab-tf/      # EKS lab Terraform (10 scenario validation)
Dockerfile           # Container image for ECS/EKS deployment
docs/                # WORKFLOW.md, MVP release notes, cases, use-cases
```

## AWS Deployment (Singapore)

One-click Terraform deployment: CloudFront → ALB → EC2 (t3.medium) in ap-southeast-1.

### Architecture

```
Internet (HTTPS) → CloudFront → ALB (SG: CF prefix-list only) → EC2 (private subnet, port 8000)
                                                                   ↓
                                                              EBS gp3 (SQLite)
                                                                   ↓
                                                          Bedrock API (us-east-1)
```

### Deploy

```bash
cd iac/deploy-sg

# Review plan
./deploy.sh plan

# Deploy (one-click)
./deploy.sh apply

# Destroy
./deploy.sh destroy
```

**Prerequisites**: AWS CLI configured, Terraform >= 1.5, `ap-southeast-1` access.

**Default login**: `admin` / `aiops2026` (changeable via `AIOPS_ADMIN_PASSWORD`)

### Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `region` | `ap-southeast-1` | AWS region |
| `instance_type` | `t3.medium` | EC2 instance type |
| `vpc_id` | `""` (new VPC) | Use existing VPC (optional) |
| `admin_password` | `aiops2026` | Admin user password |
| `bedrock_region` | `us-east-1` | Bedrock API region |

## Docker

```bash
# Build (for future ECS/EKS)
docker build -t agenticops .

# Run
docker run -p 8000:8000 \
  -e AIOPS_BEDROCK_REGION=us-east-1 \
  -e AIOPS_API_AUTH_ENABLED=true \
  -e AWS_ACCESS_KEY_ID=... \
  -e AWS_SECRET_ACCESS_KEY=... \
  agenticops
```

## Authentication

When `AIOPS_API_AUTH_ENABLED=true` (default for cloud deployments):

- **Login**: `POST /api/auth/login` with `{"email": "admin", "password": "aiops2026"}`
- **Session token**: Returned in login response, valid for 24 hours
- **API keys**: `POST /api/users/me/api-keys` for long-lived access
- **Protected routes**: All `/api/*` except `/api/health` and `/api/auth/login`
- **Frontend**: Login page at `/app/login`, auto-redirect on 401

Default admin user is auto-seeded on first startup when no users exist.

## Development

```bash
# Install
pip install -e ".[dev]"

# Run tests
pytest tests/ -v

# Syntax check
python3 -m py_compile src/agenticops/web/app.py

# Frontend type check + build
cd src/agenticops/web/frontend
npx tsc --noEmit && npm run build

# Run API server (dev)
uvicorn agenticops.web.app:app --reload --port 8000

# Run chat
aiops chat
```

## License

MIT
