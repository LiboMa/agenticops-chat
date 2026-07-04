# AgenticOps

**Agent-first cloud operations platform.** A team of specialized AI agents scans your AWS infrastructure, detects issues, finds root causes, plans fixes, and — for low-risk problems — remediates them autonomously. They also **learn**: every operation refines a self-optimizing memory and skill library.

> **Version**: 2.0.1 · **Latest release**: [Chat/Dashboard/Nav UX overhaul + Strands 1.45 context governance](docs/MVP-2.0.1-RELEASE.md) · **Full history** below.

Three ways in — all driving the same agents:

```
   CLI  (aiops chat)  ┐
   Web Dashboard      ├──►  Main Agent (router)  ──►  6 specialist agents  ──►  AWS
   IM Bots            ┘
   (Feishu/Slack/…)
```

---

## Design Principles

The whole system follows a few deliberate rules — they explain most of the design decisions below:

1. **Agents as tools.** The Main agent is a *pure router*; each specialist (Scan, Detect, RCA, SRE, Executor, Reporter) is exposed as a callable tool. No specialist talks to another directly.
2. **Read/plan/execute are separated.** SRE *plans* fixes but never touches infrastructure; only the Executor acts, and only after an approval gate. Risk-tiered: L0/L1 auto-approve, L2/L3 require a human.
3. **Tiered models for cost.** Opus for the heaviest reasoning (RCA, SRE, Executor), Sonnet for routing and high-throughput work (Main, Scan, Detect, Reporter), Haiku available as the economy tier. Per-agent overridable. Token & cost is tracked per-call with real-time dashboards (Web + `aiops cost` CLI).
4. **Agents learn, safely.** Memory and skills self-optimize within hard safety boundaries — agent writes land as drafts; promotion is security-gated; human-authored knowledge is pinned and never auto-touched.
5. **One source of truth for config.** `config/settings.yaml` defines everything; env vars override it. Code never hardcodes values.
6. **Simple by default.** SQLite + file-based memory locally; Postgres + S3 only when you opt into the cloud profile. No dependency added without a present-day need.

---

## What It Does

| Capability | Description |
|------------|-------------|
| **Scan** | 20+ AWS service types (EC2, Lambda, RDS, S3, ECS, EKS, DynamoDB, SQS/SNS, VPC/subnets/SGs, NAT/TGW, Load Balancers) |
| **Monitor & Detect** | CloudWatch alarms/metrics, Z-score anomaly detection, Prometheus/CloudWatch/Datadog webhook intake |
| **Root Cause Analysis** | LLM-powered RCA with CloudTrail correlation, infrastructure graph, and Knowledge Base search |
| **Auto-Fix Pipeline** | HealthIssue → RCA → SRE → Approve(L0/L1) → Execute → Resolve — autonomous for low-risk fixes |
| **Self-Optimizing Memory** | File-based agent memory that learns from each operation; agent self-curation, never-delete archival, prompt-cache-safe injection |
| **Autonomous Skills** | 15 domain skills the agents can create, improve, and merge — published only through a security-gated, human-auditable workflow |
| **Concurrent Chat** | Multiple conversations stream at once; sessions open instantly via cursor-paginated, virtualized history |
| **Chat Attachments** | Paste images (Cmd+V), drag-drop, and multi-file upload (up to 5) in the web composer; per-type size validation |
| **Knowledge Base** | Hybrid vector + keyword search; distills resolved cases into reusable SOPs |
| **Reports & Schedules** | Daily/weekly/incident/inventory reports; cron pipelines (FullScan, Monitoring, HealthPatrol, …) |
| **Messaging** | Unified Settings → Messaging tab: bot apps (Feishu/Slack/DingTalk/WeCom credentials), channels (Slack/Email/SES/SNS/Feishu/DingTalk/WeCom/Webhook), and delivery logs — schema-driven config with masked secrets, via `/api/messaging/*` |
| **MCP Servers** | Claude-Desktop-compatible MCP integration — manage via Chat/CLI/Web, hot-reload |
| **Graph Engine** | NetworkX infrastructure graph: SPOF detection, capacity risk, dependency chains, change simulation (agent tools) |

---

## Architecture

```
CLI (aiops chat)  ──┐
                    ├──► Main Agent (router) ──► Scan Agent    ──► AWS service APIs
Web Dashboard ──────┤        │                  Detect Agent  ──► CloudWatch, Prometheus
  (React + SSE)     │        │                  RCA Agent     ──► CloudTrail, KB, Skills, Graph
IM Bots ────────────┘        │                  SRE Agent     ──► Fix-plan generation (READ-ONLY)
                             │                  Executor Agent──► AWS CLI, SSM/SSH, kubectl
                             │                  Reporter Agent──► Reports, KB distillation
                             │
                             ├──► Agent Memory  (agent-memory/*.md — self-optimizing)
                             ├──► Agent Skills  (skills/*/SKILL.md — autonomous, security-gated)
                             ├──► SQLite / PostgreSQL  (metadata)
                             └──► MCP Servers  (optional external tools)
```

### The 7 Agents

Models are per-agent overrides in `config/settings.yaml` (`agent_*_model_id`), winning over the tier defaults in `config.py`. Committed defaults:

| Agent | Model (settings.yaml) | Role |
|-------|-----------------------|------|
| **Main** | Opus 4.8 | Pure router — dispatches to specialists |
| **RCA** | Opus 4.6 | Root cause analysis (Skills + KB + Graph) |
| **SRE** | Opus 4.8 | Fix-plan generation — **never executes** |
| **Executor** | Opus 4.8 | Multi-backend execution (AWS / SSM / kubectl) |
| **Scan** | Sonnet 4.6 | Resource discovery |
| **Detect** | Sonnet 4.6 | Health monitoring + anomaly detection |
| **Reporter** | Sonnet 4.6 | Report generation |

Defaults from `config/settings.yaml` — Opus for the heaviest reasoning (RCA, SRE, Executor), Sonnet elsewhere.

Models are fetched dynamically from Bedrock; override per agent in `config/settings.yaml` or via `AIOPS_AGENT_{NAME}_MODEL_ID`. Switch at runtime with CLI `/model` or Web Settings.

### Auto-Fix Pipeline

```
Alert ─► HealthIssue ─► RCA ─► SRE ─► Auto-Approve (L0/L1) ─► Executor ─► Resolve
                                       └► L2/L3: Human Approval
```

- **Three independent gates**: `auto_fix_enabled` (master) · `executor_auto_approve_l0_l1` · `executor_enabled`
- **One issue → one active fix plan**: draft = update-in-place, locked = reject, terminal = allow new
- **9-state HealthIssue lifecycle**, enforced by a state machine (invalid transitions → 409):
  `open → investigating → acknowledged → root_cause_identified → fix_planned → fix_approved → fix_executing → fix_executed → resolved`

### Dual Alert Intake

| Pipeline | Flow | LLM Cost |
|----------|------|----------|
| **Webhook** | Prometheus/CloudWatch/Datadog → `alert_processor` → HealthIssue → RCA pipeline | None |
| **IM Agent** | IM message → Main Agent (verification) → `create_health_issue` → same pipeline | Yes |

A SHA-256 fingerprint dedups issues across both pipelines.

### Self-Learning Layer

Agents improve over time, within strict safety boundaries:

- **Memory** (`agent-memory/<agent>/*.md`) — Hermes-style self-optimizing markdown memory. Agents `add/merge/search` via a `memory_manage` tool; a zero-LLM Curator ages unused memories (`active→stale→archived`) and **never deletes** (recoverable). Human-written memories outrank agent-written ones. Injected once at build time (prompt-cache-safe).
- **Skills** (`skills/<name>/SKILL.md`) — agents can `add/improve/merge` skills via `skill_manage`, but writes land as **drafts only**. `promote_skill` scans the skill body for dangerous shell commands before publishing; human-authored skills are **pinned** and never auto-modified. All changes are versioned and recoverable.

See [`docs/MVP-1.1.0-RELEASE.md`](docs/MVP-1.1.0-RELEASE.md) for the full memory + skills design.

---

## Quick Start

```bash
# 1. Install
pip install -e .                 # add ".[cloud]" for pgvector + Postgres

# 2. Initialize (pick one)
aiops init                       # interactive wizard
aiops init --yes                 # non-interactive local defaults
aiops init --config setup.json   # zero-prompt from JSON (template: config/setup.json.example)
aiops quickstart --yes           # one-click: init + start + optional scan

# 3. Start
aiops web                        # dashboard at http://localhost:8000
#   or: aiops service start      # background daemon

# 4. Chat
aiops chat                       # interactive REPL (30+ slash commands)
aiops chat "check health of prod"            # headless
aiops chat "analyze this log @/tmp/error.log"  # with file
aiops chat "deep dive on I#42 and check R#17"  # with issue/resource refs
```

Common operations:

```bash
aiops run scan --services EC2,Lambda,RDS,S3
aiops run detect
aiops issues
aiops run analyze 1
aiops run report --type daily
```

---

## Interfaces

### CLI

| Command | Description |
|---------|-------------|
| `aiops init / quickstart` | Initialize / one-click bring-up |
| `aiops chat [QUERY] [-d LEVEL] [-f FOCUS]` | Interactive or headless AI chat |
| `aiops service start\|stop\|status\|logs` | Background service management |
| `aiops web [--host H] [--port P]` | Launch web dashboard |
| `aiops issues` / `aiops issue <id>` | List / show health issues |
| `aiops get\|describe\|create\|update\|delete <entity>` | CRUD over accounts, resources, schedules, channels |
| `aiops run scan\|detect\|analyze\|report\|schedule\|notify` | Run a pipeline step |

In-chat slash commands (30+) cover scan/detect/analyze/fix/approve/execute, `/model`, `/skill`, `/workflow`, `/channel`, `/send_to`, `/tokens`, and more — type `/help`.

### Web Dashboard

React 18 + TypeScript + Tailwind + TanStack Query, served by FastAPI at `http://localhost:8000`. 13 pages (+ Login): Dashboard, Chat, Issues & Plans, Issue Detail, Resource Detail, Schedules, Schedule Detail, Reports, Report Detail, Agent Metrics, Skills, Skill Detail, Settings.

The **Chat** page streams multiple concurrent sessions (background streaming, instant open) — see [v1.1.1 notes](docs/MVP-1.1.1-RELEASE.md).

### API

80+ REST endpoints; full OpenAPI at `http://localhost:8000/docs`. Key groups: `/api/health-issues`, `/api/fix-plans`, `/api/chat/sessions` (SSE), `/api/resources`, `/api/schedules`, `/api/skills`, `/api/graph`, `/api/settings`, `/api/auth`.

---

## Configuration

`config/settings.yaml` is the single source of truth. **Priority**: `AIOPS_*` env vars > `.env` > `settings.yaml` > defaults.

| Variable | Default | Description |
|----------|---------|-------------|
| `AIOPS_BEDROCK_MODEL_ID` | `global.anthropic.claude-sonnet-4-6` | Default (mid) tier; per-agent overrides in `settings.yaml` |
| `AIOPS_BEDROCK_REGION` | `us-east-1` | Bedrock region |
| `AIOPS_DATABASE_URL` | `sqlite:///…/data/agenticops.db` | Database URL |
| `AIOPS_AUTO_FIX_ENABLED` | `true` | Auto-fix pipeline master switch |
| `AIOPS_EXECUTOR_AUTO_APPROVE_L0_L1` | `true` | Auto-approve low-risk plans |
| `AIOPS_MEMORY_AUTONOMOUS_WRITE` | `true` | Allow agents to self-write memory (drafts) |
| `AIOPS_SKILLS_AUTONOMOUS_WRITE` | `true` | Allow agents to self-create skills (drafts) |
| `AIOPS_SKILLS_SECURITY_SCAN_ON_PROMOTE` | `true` | Security-scan skills before publishing |
| `AIOPS_DEPLOYMENT_PROFILE` | `local` | `local` (SQLite/files) or `cloud` (Postgres/S3) |

---

## Deployment

| Target | Path | Command |
|--------|------|---------|
| **Docker** | `docker/` | `docker build -f docker/Dockerfile -t agenticops . && docker run -p 8000:8000 …` |
| **EC2** | `iac/ec2/` | `terraform apply` |
| **ECS (Fargate)** | `iac/ecs/` | `terraform apply` |
| **EKS** | `iac/eks/` | `terraform apply` |
| **One-click (Singapore)** | `iac/deploy-sg/` | `./deploy.sh apply` — CloudFront → ALB → EC2 in ap-southeast-1 |

```bash
docker run -d -p 8000:8000 \
  -v /data/agenticops:/app/data \
  -e AIOPS_ADMIN_PASSWORD=MyPassword \
  -e AIOPS_BEDROCK_REGION=us-east-1 \
  agenticops:latest
```

**Auth** (default-on for cloud profiles): login via `POST /api/auth/login` (`admin` / `aiops2026`, change with `AIOPS_ADMIN_PASSWORD`); 24h session tokens; API keys for long-lived access; all `/api/*` protected except `/api/health` and `/api/auth/login`.

**Singapore deployment access**: the one-click `deploy-sg` stack fronts the app with CloudFront. Use the CloudFront default domain (`./deploy.sh` prints `cloudfront_url`, e.g. `https://d1o50vxhknqf6d.cloudfront.net`) which is always reachable; a custom domain via Route53 + ACM is optional and requires a live domain. `deploy.sh redeploy [branch]` pulls + rebuilds + restarts on the instance via SSM. Note: the instance uses an auto-assigned public IP that changes on stop/start — drive ops via the instance ID / SSM, not a hard-coded IP.

Details: [`docker/README.md`](docker/README.md) · [`iac/ec2/README.md`](iac/ec2/README.md) · [`docs/WORKFLOW.md#deployment`](docs/WORKFLOW.md).

---

## Validation

Closed-loop validation on an EKS lab (10 fault scenarios — OOM, bad image, network policy, disk pressure, pod pending, unhealthy targets, CoreDNS down, PVC pending, HPA maxed, service deleted):

| Metric | Target | Actual |
|--------|--------|--------|
| Auto-fix rate | ≥ 7/10 | **10/10** |
| Detection time | ≤ 3 min | **~2 min** |
| MTTR | ≤ 10 min | **~6.3 min** |
| Cost / cycle | ≤ $3 | **~$2–3** |

---

## Project Structure

```
src/agenticops/
├── agents/       # 7 Strands agents (main, scan, detect, rca, sre, executor, reporter)
├── tools/        # Agent tools (metadata, AWS CLI, web, notification, cloudwatch)
├── services/     # Pipeline services (auto-fix, RCA, notifications, events, resolution)
├── memory/       # Self-optimizing file-based agent memory + Curator
├── skills/       # Skill loader, security, execution, Curator, promote/rollback
├── graph/        # Infrastructure graph engine + SRE algorithms
├── kb/           # Knowledge Base (vector store: SQLite/pgvector/S3)
├── cli/          # CLI entry + chat + init wizard
├── web/          # FastAPI backend + React SPA (frontend/)
├── chat/         # Message preprocessing, file reader, /send_to, /channel
├── notify/  im/  # Multi-channel notifications + IM bots (Feishu/Slack)
├── integrations/ # Alert processor, source parsers
├── pipeline/ scheduler/ monitor/ scanner/ scan/   # Pipelines, cron, metrics, scanning
├── auth/ audit/  # JWT/API-key auth, audit trail
├── models.py     # SQLAlchemy ORM models
└── config.py     # Pydantic settings (AIOPS_ env prefix)

agent-memory/     # Per-agent + shared markdown memory (self-optimizing)
skills/           # 15 domain skill packages (+ draft/ staging) — SKILL.md + references/
config/           # settings.yaml, channels.yaml, im-apps.yaml, mcp-servers.json
iac/              # Terraform: ec2/, ecs/, eks/, deploy-sg/, modules/
docs/             # WORKFLOW.md, MVP release notes, design docs, use-cases
```

---

## Release History

Most recent first. Each links to detailed notes.

| Version | Date | Highlights |
|---------|------|-----------|
| **[2.0.1](docs/MVP-2.0.1-RELEASE.md)** | 2026-07-04 | Frontend UX overhaul — Chat composer per-session **model switch** (detail-level knob removed) · **rich chat** (model-generated suggestion chips + in-place `I#` issue locate) · **nav sidebar 2.0** (expandable, drag-reorder, hover preview) · **dashboard 2.0** (5-block realtime stats, 10s polling) · **Strands 1.45** upgrade — `context_manager="auto"` (token savings + oversized-tool-result offload) + optional executor **HITL** safety gate |
| **[2.0.0](docs/MVP-2.0.0-RELEASE.md)** | 2026-06-19 | Governed Autonomy (policy engine) · ITSM bridge · Multi-cloud capability layer (SSH/Prometheus/Kubernetes providers) · self-improvement metrics · prevention triad (SPOF patrol + RCA topology + simulation gate) · **account-addressed credentials** (kills the ContextVar wrong-account defect; explicit account resolution, fail-closed, SSM→SSH access ladder) · SES/SMTP notifier key-mapping fix |
| **[1.1.1](docs/MVP-1.1.1-RELEASE.md)** | 2026-06-02 | Concurrent chat sessions + fast open; paste/drag-drop multi-attachment; open-webui-style chat UI refresh; agent window-config fix (Full Context + Web→YAML persist); unified **Messaging** settings (merged Notifications + IM Bots) |
| **[1.1.0](docs/MVP-1.1.0-RELEASE.md)** | 2026-05-31 | Autonomous **agent memory** (self-optimizing, Hermes-style) + autonomous **skills** (agent-created, security-gated promotion) |
| **[1.0.1](docs/MVP-1.0.1-RELEASE.md)** | 2026-05-27 | Loader/UX hardening; skill index recall improvements |
| **[1.0.0](docs/MVP-1.0.0-RELEASE.md)** | 2026-03-10 | First MVP — 7-agent architecture, auto-fix pipeline, web dashboard, 10/10 validation |

User-facing workflow guide with Mermaid diagrams: [`docs/WORKFLOW.md`](docs/WORKFLOW.md). Codebase health audit + loop-engineering roadmap: [`docs/AUDIT-2026-06.md`](docs/AUDIT-2026-06.md).

---

## Development

```bash
pip install -e ".[dev]"

pytest tests/ -v                              # tests
python3 -m py_compile src/agenticops/web/app.py   # backend syntax check
cd src/agenticops/web/frontend && npx tsc --noEmit && npm run build   # frontend
uvicorn agenticops.web.app:app --reload --port 8000   # dev API server
```

## License

MIT
