# AgenticOps — Project Statistics

**Version**: 0.9.0-beta
**Date**: 2026-04-04
**Branch**: `main`

---

## Code Metrics

### Total

| Layer | Files | Lines of Code |
|-------|------:|-------------:|
| Backend (Python) | ~130 | 50,471 |
| Frontend (TypeScript/React) | 90 | 13,560 |
| Tests | 61 | 21,275 |
| Skills (Markdown) | 48 | — |
| Infrastructure | 97 | — |
| **Total** | **~426** | **85,300+** |

### Backend Breakdown (`src/agenticops/`)

| Module | Files | LOC | Description |
|--------|------:|----:|-------------|
| `tools/` | 17 | 7,479 | Agent tools: metadata DB CRUD, AWS CLI wrapper, network, graph tools |
| `web/` | 5 | 6,926 | FastAPI app (~152 endpoints), schemas, SSE streaming |
| `cli/` | 6 | 6,863 | Typer CLI: chat REPL, slash commands, init wizard, display |
| `graph/` | 10 | 4,031 | Infrastructure graph engine (NetworkX): SPOF, capacity, dependencies |
| `notify/` | 4 | 2,495 | Multi-channel notifications: email/SES, Slack, Feishu, webhook |
| `agents/` | 9 | 2,099 | 7 Strands SDK agents (main + 6 specialists) |
| `im/` | 10 | 1,895 | IM bot integration (Feishu WebSocket, Slack) |
| `integrations/` | 6 | 1,825 | Webhook alert processing, source parsers (Prometheus/CW/Datadog) |
| `skills/` | 8 | 1,702 | Skill loader, security classifier, execution engine |
| `pipeline/` | 6 | 1,371 | Pipeline orchestrator, health patrol, RAG pipeline |
| `services/` | 8 | 1,365 | Auto-fix pipeline, auto-RCA, notification, resolution services |
| `kb/` | 5 | 1,114 | Vector storage (SQLite/pgvector/S3), knowledge base |
| `chat/` | 5 | 1,101 | Message preprocessor, file upload, /send_to, /channel |
| `models.py` | 1 | 1,077 | SQLAlchemy ORM: 14 models (CloudAccount, HealthIssue, FixPlan, ...) |
| `agent/` | 2 | 1,066 | Legacy OpsAgent (pre-Strands, kept for compatibility) |
| `scan/` | 4 | 959 | AWS resource scanner (AWSScanner) |
| `providers/` | 6 | 887 | Multi-cloud provider abstraction (AWS/Azure/GCP/Alicloud) |
| `config.py` | 1 | 791 | Pydantic-settings config, YAML loader, model tier system |
| `detect/` | 3 | 748 | Anomaly detector: rule engine + statistical (Z-score, IQR) |
| `scheduler/` | 2 | 666 | Cron scheduler, execution tracking, stale cleanup |
| `report/` | 2 | 601 | Report generator: daily, anomaly, inventory, network health |
| `monitor/` | 3 | 574 | CloudWatch metrics collector |
| `analyze/` | 2 | 345 | RCA engine (Bedrock LLM-powered root cause analysis) |
| `storage/` | 2 | 186 | Storage backends (local/S3) |
| `checker/` | 2 | 155 | Parallel multi-account agentic health checker |

### Frontend Breakdown (`src/agenticops/web/frontend/src/`)

| Directory | Files | LOC | Description |
|-----------|------:|----:|-------------|
| `pages/` | 10 | 5,252 | Dashboard, Chat, Issues, Schedules, Reports, Settings, etc. |
| `components/` | 37 | 5,317 | Chat, layout (AppShell, Sidebar), DataTable, CronBuilder, badges |
| `hooks/` | 35 | 1,617 | TanStack Query hooks for all API resources |
| `api/` | 2 | 652 | API client, TypeScript type definitions |
| `lib/` | 6 | 410 | Utilities: date formatting, cron helpers, cn() |

---

## Key Counts

| Metric | Count |
|--------|------:|
| API endpoints | 152 |
| Test functions | 1,200 |
| Test files | 61 |
| Agent skills | 15 (+1 draft) |
| SQLAlchemy models | 14 |
| Strands agents | 7 (main + scan, detect, rca, sre, executor, reporter) |
| Pipeline types | 5 (FullScan, Monitoring, DailyReport, HealthPatrol, AgentChain) |
| Git commits | 227 |
| Python dependencies | 42 |
| JS dependencies | 22 |

---

## Architecture Overview

```
                    ┌─────────────┐      ┌─────────────┐
                    │  CLI (aiops) │      │ Web Dashboard│
                    │  Typer REPL  │      │ React + SSE  │
                    └──────┬───────┘      └──────┬───────┘
                           │                     │
                    ┌──────▼─────────────────────▼──────┐
                    │         Main Agent (Router)        │
                    │  Strands SDK · Opus/Sonnet/Haiku   │
                    └──┬────┬────┬────┬────┬────┬───────┘
                       │    │    │    │    │    │
              ┌────────▼┐ ┌▼────▼┐ ┌▼────▼┐ ┌▼────────┐
              │  Scan   │ │Detect│ │ RCA  │ │   SRE   │
              │  Agent  │ │Agent │ │Agent │ │  Agent  │
              └────┬────┘ └──┬───┘ └──┬───┘ └────┬────┘
                   │         │        │          │
              ┌────▼─────────▼────────▼──────────▼────┐
              │          Provider Abstraction          │
              │   AWS · Azure · GCP · Alicloud         │
              └────────────────┬──────────────────────┘
                               │
                ┌──────────────▼──────────────────┐
                │        Cloud Resources           │
                │  EC2 · S3 · RDS · EKS · VPC · …  │
                └──────────────────────────────────┘
```

**Auto-Fix Pipeline**: HealthIssue → RCA → SRE → Approve (L0-L4) → Execute → Resolve

**HealthIssue State Machine**: open → investigating → acknowledged → root_cause_identified → fix_planned → fix_approved → fix_executing → fix_executed → resolved (9 states)

---

## Roadmap

### Completed (v1.0.0 MVP)

- [x] Multi-agent architecture (Strands SDK, 7 agents)
- [x] Multi-cloud provider abstraction (AWS, Azure, GCP, Alicloud stubs)
- [x] Multi-account support with parallel scanning
- [x] Auto-fix pipeline with L0-L4 risk levels
- [x] React web dashboard (15 pages, 152 API endpoints)
- [x] Interactive CLI with slash commands
- [x] 15 domain skills with dynamic tool registration
- [x] Infrastructure graph engine (SPOF, capacity risk, dependency analysis)
- [x] Cron scheduler with visual cron builder
- [x] Dual alert intake (webhook + IM bot)
- [x] Notification system (email, Slack, Feishu, webhook)
- [x] Report generation (daily, inventory, network health)
- [x] Per-agent model configuration (Opus/Sonnet/Haiku tiers)
- [x] Prompt caching on all agents
- [x] Agent memory system (file-based behavioral constraints)
- [x] MCP server integration

### Planned (v1.0.1)

- [ ] **Large file refactoring**: Split `app.py` (6.9K LOC) and `cli/main.py` (6.9K LOC) into routers/modules
- [ ] **Azure/GCP provider implementations**: Full credential chain + scanner for Azure and GCP
- [ ] **OpenTelemetry integration**: Distributed tracing for agent calls and pipeline execution
- [ ] **Knowledge base RAG**: Vector search over past incidents for smarter RCA
- [ ] **FixPlan approval workflow UI**: Visual approval/rejection with comments in web dashboard
- [ ] **Persistent chat sessions**: Resume previous chat conversations with full context

### Future (v1.1+)

- [ ] Multi-tenant support (team/org isolation)
- [ ] Custom skill authoring via web UI
- [ ] Alert correlation engine (group related alerts into incidents)
- [ ] Cost optimization agent (RI/SP recommendations, unused resource detection)
- [ ] Compliance scanning (CIS benchmarks, custom policies)
- [ ] Mobile notifications (push via APNs/FCM)
- [ ] Plugin marketplace for community skills
