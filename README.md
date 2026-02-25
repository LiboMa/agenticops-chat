# AgenticOps

Agent-First Cloud Observability Platform for AWS — multi-agent AI operations with interactive CLI, React dashboard, and autonomous remediation.

## Overview

AgenticOps (`aiops`) is a production-grade platform that uses 7 specialized AI agents (built on [Strands Agents SDK](https://github.com/strands-agents/strands-agents) + AWS Bedrock Claude) to scan, monitor, detect, analyze, and remediate issues across your AWS infrastructure. It provides a kubectl-style CLI with an interactive chat REPL, a full-stack React SPA dashboard, and 60+ REST API endpoints.

## Key Capabilities

| Capability | Description |
|------------|-------------|
| **Scan** | Discover EC2, Lambda, RDS, S3, ECS, EKS, DynamoDB, SQS, SNS, VPCs, subnets, SGs, route tables, NAT gateways, Transit Gateways, and Load Balancers |
| **Monitor** | CloudWatch metrics, alarms, and log insights |
| **Detect** | Statistical anomaly detection (Z-score) and rule-based evaluation |
| **Analyze** | LLM-powered Root Cause Analysis with CloudTrail correlation, network topology, and Knowledge Base search |
| **Remediate** | Structured fix plans (L0-L3 risk levels) with approval workflow and autonomous execution |
| **Report** | Daily, incident, and inventory reports with KB case study distillation |
| **Network Topology** | VPC topology analysis, blackhole route detection, security group dependency mapping, reachability queries |
| **Knowledge Base** | Hybrid vector (Titan V2) + keyword search over SOPs, case studies, and runbook patterns |
| **Schedule** | Cron-based task scheduling for recurring operations |
| **Notify** | Multi-channel notifications (Slack, Email, SNS, Webhook) |
| **Auth** | User authentication (JWT sessions + API keys) |
| **Audit** | Complete audit trail for all operations |

## Multi-Agent Architecture

```
                        ┌─────────────────┐
                        │   Main Agent    │  Orchestrator
                        │  (routes tasks) │
                        └────────┬────────┘
               ┌────────┬───────┼───────┬────────┬────────┐
               v        v       v       v        v        v
          ┌────────┐ ┌──────┐ ┌─────┐ ┌─────┐ ┌────────┐ ┌──────────┐
          │  Scan  │ │Detect│ │ RCA │ │ SRE │ │Execute │ │ Reporter │
          │ Agent  │ │Agent │ │Agent│ │Agent│ │ Agent  │ │  Agent   │
          └────────┘ └──────┘ └─────┘ └─────┘ └────────┘ └──────────┘
          Resource    Health   Root    Fix Plan  Approved   Report
          discovery   monitor  cause   generation execution  generation
                                analysis (READ-ONLY) (L4 Auto)
```

| Agent | Role | Key Tools |
|-------|------|-----------|
| **Scan Agent** | Resource discovery and inventory | AWS service APIs (EC2, Lambda, RDS, S3, ECS, EKS, DynamoDB, SQS, SNS), VPC/network describe |
| **Detect Agent** | Health monitoring via CloudWatch | List alarms, get metrics, query logs, Z-score detection, rule evaluation |
| **RCA Agent** | Root Cause Analysis | CloudWatch metrics/logs, CloudTrail events, network topology, Knowledge Base search |
| **SRE Agent** | Fix plan generation (READ-ONLY, never executes) | Metadata tools, KB search, AWS read-only CLI |
| **Executor Agent** | Autonomous fix execution (L4 Auto Operation) | AWS CLI (write), 7-step safety protocol: verify -> gate -> pre-check -> execute -> post-check -> verify-fix -> record |
| **Reporter Agent** | Report generation and KB distillation | Report tools, metadata queries, case study writer |
| **Main Agent** | Orchestrator routing tasks to specialists | All sub-agents exposed as tools |

### HealthIssue Lifecycle

```
open -> investigating -> root_cause_identified -> fix_planned -> fix_approved -> fix_executed -> resolved
```

### Fix Plan Risk Levels

| Level | Description | Approval |
|-------|-------------|----------|
| **L0** | Informational (no changes) | Auto-approved |
| **L1** | Safe read-only diagnostics | Auto-approved |
| **L2** | Low-risk changes (restart, scale) | Manual approval required |
| **L3** | High-risk changes (config, IAM) | Manual approval + review required |

## Quick Start

### 1. Install

```bash
pip install -e .
```

### 2. Initialize

```bash
aiops init
```

### 3. Add AWS Account

```bash
aiops create account my-account \
  --account-id 123456789012 \
  --role-arn arn:aws:iam::123456789012:role/AgenticOpsRole \
  --regions us-east-1,us-west-2
```

> Only one account can be active at a time. Creating a new account automatically activates it and deactivates others.

### 4. Basic Operations

```bash
# Scan resources
aiops run scan --services EC2,Lambda,RDS,S3

# Run anomaly detection
aiops run detect

# View health issues
aiops issues

# Analyze a specific issue
aiops run analyze 1

# Generate daily report
aiops run report --type daily
```

### 5. Start Web Dashboard

```bash
aiops web
# Dashboard at http://localhost:8000
```

### 6. Interactive AI Chat

```bash
aiops chat
# Or with account context:
aiops chat --account production
```

## CLI Reference

### Command Structure

```
aiops <verb> <resource> [options]
```

### Core Commands

| Command | Description |
|---------|-------------|
| `aiops init` | Initialize database |
| `aiops chat [--account NAME]` | Start interactive AI chat |
| `aiops web [--host HOST]` | Launch web dashboard |
| `aiops issues [--severity S] [--status S]` | List health issues |
| `aiops issue <id>` | Get specific health issue |
| `aiops manage <resource_id>` | Mark resource as managed |
| `aiops unmanage <resource_id>` | Unmark managed resource |
| `aiops arch [-o FORMAT]` | Show system architecture (tree/markdown/json) |
| `aiops export <entity> [-o FORMAT]` | Export data (resources, issues, accounts, reports) |
| `aiops test_account <name>` | Test AWS account credentials |
| `aiops version` | Show version |

### Get Resources

| Command | Description |
|---------|-------------|
| `aiops get accounts` | List all AWS accounts |
| `aiops get resources [-t TYPE]` | List resources (filterable by type) |
| `aiops get anomalies [--status STATUS]` | List anomalies (legacy) |
| `aiops get reports` | List generated reports |
| `aiops get schedules` | List scheduled tasks |
| `aiops get channels` | List notification channels |

### Create / Update Resources

| Command | Description |
|---------|-------------|
| `aiops create account <name> -a <id> -r <arn>` | Create AWS account |
| `aiops create schedule <name> <pipeline> <cron>` | Create scheduled task |
| `aiops create channel <name> -t <type> -c <config>` | Create notification channel |
| `aiops update account <name> --enable/--disable` | Activate/deactivate account |
| `aiops update anomaly <id> --acknowledge/--resolve` | Update anomaly status |

### Run Operations

| Command | Description |
|---------|-------------|
| `aiops run scan [--services SVC]` | Scan AWS resources |
| `aiops run detect` | Run anomaly detection |
| `aiops run analyze <issue_id>` | Run RCA on issue |
| `aiops run report [--type TYPE]` | Generate report |
| `aiops run schedule <name>` | Trigger scheduled task |
| `aiops run notify <subject>` | Send notification |

### Output Formatting

```bash
# Output formats
aiops get resources -o table   # Default table view
aiops get resources -o json    # JSON with syntax highlighting
aiops get resources -o wide    # Extended table with more columns

# Architecture views
aiops arch              # Tree view (default)
aiops arch -o markdown  # Markdown tables
aiops arch -o json      # JSON

# Table styles (via env var)
export AIOPS_TABLE_STYLE=simple   # simple | minimal | double | ascii | default
```

## Chat Mode

`aiops chat` provides an interactive REPL with 30+ slash commands, AI-powered natural language queries, animated thinking display, and smart output paging.

### Thinking Display

Real-time progress indicators (Claude Code-style):

```
  ✓ Understanding request (245ms)
  ⚙ Calling scan_resources (EC2, Lambda) (1.2s)
  ✓ Processing results (89ms)
  ⠹ Generating response...
```

Braille spinner animates smoothly. Token usage tracked per request: `↑3.8K ↓216 Σ4.1K | Requests: 1`.

### Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| ↑ / ↓ | Navigate command history |
| Ctrl+R | Reverse search history |
| Tab | Auto-complete slash commands |
| Ctrl+A / Ctrl+E | Move to line start/end |
| Ctrl+W | Delete word |
| Ctrl+U | Clear line |
| Ctrl+C | Cancel input (press twice to exit) |

### Slash Commands

```
# Help & Info
/help                              Show all commands
/status                            System status overview
/arch                              Show system architecture

# Resources
/account list|show|activate|delete Account management
/resource list|show                Resource queries
/issue list|show                   Health issue queries
/report list                       Report queries

# Operations
/scan                              Scan resources
/detect                            Run detection
/analyze <id>                      Run RCA
/ack <id>                          Acknowledge issue
/resolve <id>                      Resolve issue

# Workflows
/workflow full-scan                Full scan pipeline
/workflow daily                    Scan -> detect -> analyze -> report
/workflow incident <id>            RCA + notify workflow
/workflow health                   Health check

# Session & Context
/session save|load|delete|list     Session management
/context account <name>            Switch account context
/output json|table|wide            Set output format
/style <style>                     Set table style

# Display & Paging
/pager on|off|auto|<N>            Smart output truncation
/less                              View full last output (markdown rendered)
/scroll                            Scroll back through history
/clear                             Clear screen

# Token Tracking
/tokens                            Show token usage stats
/verbose                           Toggle verbose mode

# Export
/export resources|anomalies        Export data

/exit                              Exit chat
```

### Example Session

```
You: /account activate production
You: /workflow full-scan
You: /issue list
You: /analyze 1
You: What are the top issues in my infrastructure?
You: Can you generate a fix plan for issue #3?
You: /export resources --json
You: /exit
```

## Web Dashboard

Modern React SPA with 8 pages, served by FastAPI at `http://localhost:8000`.

**Tech stack:** React 18, TypeScript, Tailwind CSS, React Flow (topology visualization), TanStack Query

### Pages

| Page | Description |
|------|-------------|
| **Dashboard** | Overview stats, critical issues, recent activity |
| **Resources** | Managed AWS resource inventory with filtering |
| **Anomalies** | Health issue list with severity/status badges |
| **Anomaly Detail** | Single issue view with RCA results |
| **Accounts** | AWS account management |
| **Network** | Interactive VPC/region topology with graph visualization, dynamic AWS region dropdown |
| **Reports** | Generated report browser |
| **Audit Log** | Complete operation audit trail |

### Network Topology Features

- **Region-level overview**: VPCs, Transit Gateways, peering connections
- **VPC drill-down**: Subnets, route tables, NAT gateways, Internet gateways, endpoints
- **Interactive graph view**: React Flow with clickable nodes (VPC -> subnet -> reachability)
- **Anomaly detection**: Blackhole routes, orphaned resources, missing gateways
- **Security group dependency map**: Visual SG reference chain
- **Dynamic region selector**: Populated from AWS regional-table API (37+ regions)

## API Reference

60+ REST API endpoints served by FastAPI. Full OpenAPI docs at `http://localhost:8000/docs`.

### Endpoints by Category

| Category | Endpoints | Description |
|----------|-----------|-------------|
| **System** | `GET /api/health`, `GET /api/stats`, `GET /api/regions` | Health check, dashboard stats, AWS region list |
| **Accounts** | `GET/POST /api/accounts`, `GET/PUT/DELETE /api/accounts/{id}` | AWS account CRUD |
| **Resources** | `GET /api/resources`, `GET /api/resources/{id}` | Resource inventory |
| **Health Issues** | `GET/POST /api/health-issues`, `GET/PUT/DELETE /api/health-issues/{id}`, `GET .../rca`, `GET .../fix-plans` | Issue lifecycle management |
| **Fix Plans** | `GET/POST /api/fix-plans`, `GET/PUT/DELETE /api/fix-plans/{id}`, `PUT .../approve`, `POST .../execute` | Remediation plan management |
| **Fix Executions** | `GET /api/fix-executions`, `GET /api/fix-executions/{id}` | Execution result history |
| **Reports** | `GET /api/reports`, `GET /api/reports/{id}`, `POST /api/reports/generate` | Report management |
| **Schedules** | `GET/POST /api/schedules`, `GET/PUT/DELETE /api/schedules/{id}`, `POST .../run`, `GET .../executions` | Cron scheduling |
| **Notifications** | `GET/POST /api/notifications/channels`, `PUT/DELETE .../channels/{id}`, `POST .../test`, `GET .../logs` | Notification channels |
| **Auth** | `POST /api/auth/register/login/logout`, `GET /api/users/me`, `PUT /api/users/me/password`, API key CRUD | Authentication |
| **Audit** | `GET /api/audit/logs`, `GET /api/audit/entity/{type}/{id}`, `GET /api/audit/stats` | Audit trail |
| **Network** | `GET /api/network/vpcs`, `GET /api/network/vpc-topology`, `GET /api/network/region-topology` | Live AWS network queries |
| **Graph** | `GET /api/graph/vpc/{id}`, `GET /api/graph/region/{region}`, reachability, anomalies | Topology graph engine |
| **Anomalies** | `GET/PUT /api/anomalies`, `GET .../rca` | Legacy compatibility endpoints |

## Graph Engine

Built on NetworkX, the graph engine models AWS infrastructure as a directed graph for topology analysis and anomaly detection.

**Node types:** VPC, Subnet, Route Table, Internet Gateway, NAT Gateway, Transit Gateway, Security Group, Load Balancer

**Edge types:** contains, routes_to, associated, attached_to, peers_with, hosted_in, references, serves

**Algorithms:**
- Reachability analysis (subnet -> internet path tracing)
- Impact radius computation (blast radius of a change)
- Network path finding (shortest path between resources)
- Anomaly detection (blackhole routes, orphaned resources, missing gateways)

## Knowledge Base

Hybrid search system for SOPs, case studies, and runbook patterns.

- **Vector search**: AWS Titan Text Embeddings V2 (1024-dim) via Bedrock
- **Keyword fallback**: When embeddings are unavailable
- **Reranking**: 60% cosine similarity + 20% efficiency score + 20% base score
- **Verified boost**: Verified case studies get 1.2x ranking boost
- **Case distillation**: Reporter agent automatically distills resolved incidents into KB case studies

## EKS Chaos Lab

Infrastructure-as-code for testing AgenticOps against real EKS failures.

**Location:** `infra/eks-chaos-lab/`

```bash
# Setup cluster + workloads + monitoring
./infra/eks-chaos-lab/setup.sh

# Inject chaos
./infra/eks-chaos-lab/chaos/pod-kill.sh
./infra/eks-chaos-lab/chaos/node-drain.sh
./infra/eks-chaos-lab/chaos/network-chaos.sh
./infra/eks-chaos-lab/chaos/resource-stress.sh
./infra/eks-chaos-lab/chaos/config-break.sh

# Restore
./infra/eks-chaos-lab/chaos/restore-all.sh

# Verify setup
./infra/eks-chaos-lab/verify/verify-agenticops.sh

# Cleanup
./infra/eks-chaos-lab/cleanup.sh
```

Includes IAM role creation, CloudWatch alarm setup, and Kubernetes workload manifests (deployments, HPA, PDB, ConfigMaps).

## Account Management

Only one account can be active at a time.

```bash
# Create and activate (deactivates others)
aiops create account prod \
  --account-id 123456789012 \
  --role-arn arn:aws:iam::123456789012:role/AgenticOpsRole

# Create without activating
aiops create account staging \
  --account-id 987654321098 \
  --role-arn arn:aws:iam::987654321098:role/AgenticOpsRole \
  --no-activate

# Switch active account
aiops update account staging --enable

# In chat mode
/account activate staging
/account active    # Show current
```

## AWS IAM Role Setup

Create an IAM role in each AWS account you want to monitor:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ec2:Describe*",
        "lambda:List*", "lambda:Get*",
        "rds:Describe*",
        "s3:List*", "s3:GetBucket*",
        "ecs:List*", "ecs:Describe*",
        "eks:List*", "eks:Describe*",
        "dynamodb:List*", "dynamodb:Describe*",
        "sqs:List*", "sqs:Get*",
        "sns:List*",
        "elasticloadbalancing:Describe*",
        "cloudwatch:GetMetricData", "cloudwatch:ListMetrics",
        "cloudwatch:DescribeAlarms", "cloudwatch:GetMetricStatistics",
        "logs:DescribeLogGroups", "logs:StartQuery", "logs:GetQueryResults",
        "cloudtrail:LookupEvents"
      ],
      "Resource": "*"
    }
  ]
}
```

Trust policy for cross-account access:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "AWS": "arn:aws:iam::YOUR_MAIN_ACCOUNT:root"
      },
      "Action": "sts:AssumeRole",
      "Condition": {
        "StringEquals": {
          "sts:ExternalId": "your-external-id"
        }
      }
    }
  ]
}
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `AIOPS_DATABASE_URL` | Database URL | `sqlite:///data/agenticops.db` |
| `AIOPS_BEDROCK_REGION` | AWS region for Bedrock LLM calls | `us-east-1` |
| `AIOPS_BEDROCK_MODEL_ID` | Bedrock model ID | `global.anthropic.claude-opus-4-6-v1` |
| `AIOPS_EMBEDDING_MODEL_ID` | Text embedding model | `amazon.titan-embed-text-v2:0` |
| `AIOPS_EMBEDDING_DIMENSION` | Embedding vector dimension | `1024` |
| `AIOPS_EMBEDDING_ENABLED` | Enable vector embeddings | `true` |
| `AIOPS_DEFAULT_METRICS_PERIOD` | CloudWatch metrics period (seconds) | `300` |
| `AIOPS_ANOMALY_DETECTION_WINDOW` | Anomaly detection window (seconds) | `3600` |
| `AIOPS_DEFAULT_LIST_LIMIT` | Default list query limit | `50` |
| `AIOPS_MAX_LIST_LIMIT` | Maximum list query limit | `500` |
| `AIOPS_EXECUTOR_ENABLED` | Enable autonomous fix execution | `false` |
| `AIOPS_EXECUTOR_AUTO_APPROVE_L0_L1` | Auto-approve L0/L1 fix plans | `true` |
| `AIOPS_EXECUTOR_STEP_TIMEOUT` | Per-step execution timeout (seconds) | `300` |
| `AIOPS_EXECUTOR_TOTAL_TIMEOUT` | Total execution timeout (seconds) | `1800` |
| `AIOPS_TABLE_STYLE` | CLI table border style | `default` |
| `AIOPS_DEV_MODE` | Enable CORS dev mode (localhost origins) | `false` |

## Architecture

```
src/agenticops/
├── agents/      # 7 Strands agents (scan, detect, rca, sre, executor, reporter, main)
├── tools/       # 10 tool modules (AWS, network, EKS, CloudWatch, CloudTrail, KB, metadata, reporting, detect, CLI)
├── graph/       # Infrastructure topology engine (NetworkX) + graph algorithms + API router
├── kb/          # Knowledge Base (vector embeddings + keyword search + case studies)
├── cli/         # kubectl-style CLI + interactive chat (30+ slash commands)
├── web/         # FastAPI backend (60+ endpoints) + React SPA frontend
├── models.py    # SQLAlchemy ORM (12+ models)
├── config.py    # Pydantic settings
├── scan/        # AWS resource scanning
├── monitor/     # CloudWatch metrics & logs
├── detect/      # Anomaly detection (Z-score + rules)
├── analyze/     # Root Cause Analysis
├── report/      # Report generation
├── pipeline/    # Multi-step workflow orchestration
├── scheduler/   # Cron-based task scheduling
├── notify/      # Notifications (Slack/Email/SNS/Webhook)
├── auth/        # Authentication (JWT sessions + API keys)
└── audit/       # Complete audit logging
```

### Dependencies

- **Agent/LLM**: `strands-agents` (Strands SDK) + AWS Bedrock (Claude)
- **AWS**: `boto3`
- **Web**: `fastapi`, `uvicorn`, `jinja2`
- **CLI**: `typer`, `rich`, `prompt-toolkit`
- **Database**: `sqlalchemy`, `pydantic`
- **Graph**: `networkx`
- **Data**: `pandas`, `numpy`

**Python**: 3.11+

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest tests/

# Syntax check
python3 -m py_compile src/agenticops/cli/main.py
python3 -m py_compile src/agenticops/web/app.py

# Run API server (dev)
uvicorn agenticops.web.app:app --reload --port 8000

# Run chat
aiops chat
```

## License

MIT
