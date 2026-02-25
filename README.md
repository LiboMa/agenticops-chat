# AgenticAIOps

Agent-First Cloud Observability Platform for AWS.

## Features

- **SCAN**: Full cloud resource scanning for configured AWS accounts
- **MONITOR**: CloudWatch Metrics and Logs monitoring
- **DETECT**: Anomaly detection with pattern matching and statistical analysis
- **ANALYZE**: Root Cause Analysis (RCA) powered by AWS Bedrock (Claude)
- **REPORT**: Proactive reporting (daily, on-demand)
- **PIPELINE**: Multi-step workflow orchestration
- **SCHEDULER**: Cron-based task scheduling
- **NOTIFY**: Multi-channel notifications (Slack/Email/SNS/Webhook)
- **AUTH**: User authentication and API keys
- **AUDIT**: Complete audit logging

## New in v0.2.0 (2026-02-22)

- **Multi-Agent Architecture** -- Migrated from LangChain to Strands Agents SDK with 6 specialized agents
- **HealthIssue Lifecycle** -- Full issue lifecycle: open -> investigating -> root_cause_identified -> fix_planned -> fix_approved -> fix_executed -> resolved
- **FixPlan Engine** -- Structured remediation plans with L0-L3 risk levels and approval workflow
- **Knowledge Base** -- Vector embeddings (Titan V2) + keyword search for SOPs and case studies
- **Network Topology** -- VPC topology analysis, blackhole route detection, SG dependency mapping, region dropdown with dynamic AWS region list
- **React SPA Dashboard** -- Modern React + Tailwind + React Flow frontend
- **60+ REST API Endpoints** -- Full CRUD for all models including health-issues, fix-plans, schedules, notifications, dynamic region listing
- **Token Tracking** -- Real-time token usage display in chat (input/output/total)
- **Animated Spinner** -- ThinkingDisplay with smooth braille animation and live elapsed time

## Quick Start

### 1. Install

```bash
cd /Users/malibo/MyDev/AgenticOps
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

> **Note**: Only ONE account can be active at a time. Creating a new account automatically activates it and deactivates others.

### 4. Basic Operations

```bash
# Scan resources
aiops run scan --services EC2,Lambda,RDS,S3

# Run detection
aiops run detect

# View anomalies
aiops get anomalies

# Analyze an anomaly
aiops run analyze 1

# Generate report
aiops run report --type daily
```

### 5. Start Web Dashboard

```bash
aiops web
```

### 6. Interactive Chat with AI Agent

```bash
aiops chat
```

## CLI Commands (kubectl-style)

### Command Structure

```
aiops <verb> <resource> [options]
```

### Get Resources

| Command | Description |
|---------|-------------|
| `aiops get accounts` | List all AWS accounts |
| `aiops get resources [-t TYPE]` | List resources |
| `aiops get anomalies [--status STATUS]` | List anomalies |
| `aiops get reports` | List reports |
| `aiops get schedules` | List scheduled tasks |
| `aiops get channels` | List notification channels |

### Describe Resources

| Command | Description |
|---------|-------------|
| `aiops describe account <name>` | Show account details |
| `aiops describe resource <id>` | Show resource details |
| `aiops describe anomaly <id>` | Show anomaly with RCA |
| `aiops describe report <id>` | Show report content |

### Create Resources

| Command | Description |
|---------|-------------|
| `aiops create account <name> -a <id> -r <arn>` | Create account |
| `aiops create schedule <name> <pipeline> <cron>` | Create schedule |
| `aiops create channel <name> -t <type> -c <config>` | Create notification channel |

### Update Resources

| Command | Description |
|---------|-------------|
| `aiops update account <name> --enable` | Activate account (deactivates others) |
| `aiops update account <name> --disable` | Deactivate account |
| `aiops update anomaly <id> --acknowledge` | Acknowledge anomaly |
| `aiops update anomaly <id> --resolve` | Resolve anomaly |
| `aiops update schedule <name> --enable/--disable` | Enable/disable schedule |

### Run Operations

| Command | Description |
|---------|-------------|
| `aiops run scan [--services SVC]` | Scan AWS resources |
| `aiops run detect` | Run anomaly detection |
| `aiops run analyze <anomaly_id>` | Run RCA on anomaly |
| `aiops run report [--type TYPE]` | Generate report |
| `aiops run schedule <name>` | Trigger scheduled task |
| `aiops run notify <subject>` | Send notification |

### View Logs

| Command | Description |
|---------|-------------|
| `aiops logs audit [-e TYPE]` | View audit logs |
| `aiops logs entity <type> <id>` | View entity history |

### Other Commands

| Command | Description |
|---------|-------------|
| `aiops init` | Initialize database |
| `aiops chat` | Start AI chat (with readline support) |
| `aiops web` | Start web dashboard |
| `aiops arch` | Show system architecture (tree/markdown/json) |
| `aiops export <entity>` | Export data |
| `aiops version` | Show version |

## Chat Slash Commands

In `aiops chat` interactive mode, use slash commands:

### Thinking Display (Claude Code Style)

The CLI shows real-time thinking progress like Claude Code:

```
  ✓ Understanding request (245ms)
  ✓ Calling scan_resources (EC2, Lambda) (1.2s)
  ✓ Processing results (89ms)
  ◐ Generating response...
```

**Status indicators:**
- `◐` Thinking/Processing (animated spinner)
- `⚙` Tool call in progress
- `✓` Step completed
- `✗` Error occurred

### Keyboard Shortcuts

The chat uses `prompt_toolkit` for enhanced terminal support:

| Shortcut | Action |
|----------|--------|
| ↑ / ↓ | Navigate command history |
| Ctrl+R | Reverse search history |
| Tab | Auto-complete slash commands |
| Ctrl+A / Ctrl+E | Move to line start/end |
| Ctrl+W | Delete word |
| Ctrl+U | Clear line |
| Ctrl+C | Cancel input (press twice to exit) |

### Quick Reference

```
/help                         Show all commands
/status                       System status overview
/arch                         Show system architecture

# Resources
/account list|show|activate|delete    Account management
/resource list|show           Resource queries
/anomaly list|show            Anomaly queries
/report list                  Report queries

# Operations
/scan                         Scan resources
/detect                       Run detection
/analyze <id>                 Run RCA
/ack <id>                     Acknowledge anomaly
/resolve <id>                 Resolve anomaly

# Workflows
/workflow full-scan           Full scan pipeline
/workflow daily               Daily operations
/workflow incident <id>       Incident response
/workflow health              Health check

# Session & Context
/session save|load|list       Session management
/context account <name>       Switch account context
/output json|table|wide       Set output format

# Export
/export resources|anomalies   Export data

/exit                         Exit chat
```

### Example Session

```
You: /status
You: /account list
You: /account activate production
You: /workflow full-scan
You: /anomaly list
You: /analyze 1
You: /ack 1
You: What are the top issues in my infrastructure?
You: /export anomalies --json
You: /exit
```

## Account Management

**Important**: Only ONE account can be active at a time.

```bash
# Create and activate account (deactivates others)
aiops create account prod --account-id 123456789012 --role-arn arn:aws:iam::123456789012:role/Role

# Create without activating
aiops create account staging --account-id 987654321098 --role-arn arn:... --no-activate

# Switch active account
aiops update account staging --enable
# Output: "All other accounts deactivated."

# In chat mode
/account activate staging
/account active    # Show current active account
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
        "lambda:List*",
        "lambda:Get*",
        "rds:Describe*",
        "s3:List*",
        "s3:GetBucket*",
        "ecs:List*",
        "ecs:Describe*",
        "eks:List*",
        "eks:Describe*",
        "dynamodb:List*",
        "dynamodb:Describe*",
        "sqs:List*",
        "sqs:Get*",
        "sns:List*",
        "cloudwatch:GetMetricData",
        "cloudwatch:ListMetrics",
        "logs:DescribeLogGroups",
        "logs:StartQuery",
        "logs:GetQueryResults"
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

## Output Formatting

The CLI supports multiple output formats for better terminal experience:

### Architecture View

```bash
# Tree view (default) - hierarchical structure
aiops arch

# Markdown - tables rendered in terminal
aiops arch -o markdown

# JSON - syntax highlighted
aiops arch -o json
```

### Table Styles

Set `AIOPS_TABLE_STYLE` environment variable:

| Style | Description |
|-------|-------------|
| `default` | Rounded borders (default) |
| `simple` | Simple lines |
| `minimal` | Minimal borders |
| `double` | Double-line borders |
| `ascii` | ASCII-only (for limited terminals) |

```bash
export AIOPS_TABLE_STYLE=simple
aiops get resources
```

### Output Formats

Most `get` commands support `-o/--output` flag:

```bash
aiops get resources -o table   # Default table view
aiops get resources -o json    # JSON with syntax highlighting
aiops get resources -o wide    # Extended table with more columns
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `AIOPS_DATABASE_URL` | SQLite database URL | `sqlite:///data/agenticops.db` |
| `AIOPS_BEDROCK_REGION` | AWS region for Bedrock | `us-east-1` |
| `AIOPS_BEDROCK_MODEL_ID` | Bedrock model ID | `global.anthropic.claude-opus-4-6-v1` |
| `AIOPS_TABLE_STYLE` | Table border style | `default` |
| `AIOPS_DEV_MODE` | Enable CORS dev mode (allows localhost origins) | `false` |
| `FORCE_COLOR` | Force color output | - |

## Architecture

```
src/agenticops/
├── agents/    # 6 Strands agents (scan, detect, rca, sre, reporter, main)
├── tools/     # 40+ agent tools (AWS, network, EKS, CloudWatch, KB, metadata)
├── graph/     # Network topology graph engine + algorithms
├── kb/        # Knowledge base (vector embeddings + keyword search)
├── data/      # Data utilities
├── scan/      # AWS resource scanning
├── monitor/   # CloudWatch metrics & logs
├── detect/    # Anomaly detection
├── analyze/   # RCA with LLM
├── report/    # Report generation
├── agent/     # Base agent framework
├── pipeline/  # Workflow orchestration
├── scheduler/ # Cron scheduling
├── notify/    # Notifications (Slack/Email/SNS/Webhook)
├── auth/      # Authentication (JWT sessions + API keys)
├── audit/     # Audit logging
├── cli/       # kubectl-style CLI + chat (28 slash commands)
└── web/       # FastAPI (60+ endpoints) + React SPA
```

## License

MIT
