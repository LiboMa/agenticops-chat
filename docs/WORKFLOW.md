# AgenticOps — Business Workflow & Quick Start Guide

## How It Works (30-Second Overview)

AgenticOps is an AI operations assistant that **scans** your AWS infrastructure, **detects** health issues, performs **root cause analysis**, generates **fix plans**, and optionally **executes** them — all through natural language chat.

```
You: "check health of my prod services"
 └──► Main Agent (router) ──► Detect Agent ──► CloudWatch + metrics + logs
                                                      │
                                            HealthIssue created
                                                      │
You: "analyze I#42"                                   ▼
 └──► Main Agent ──► RCA Agent ──► Skills + CloudTrail + metrics + KB
                                          │
                              Root cause identified (confidence: 0.85)
                                          │
You: "fix I#42"                           ▼
 └──► Main Agent ──► SRE Agent ──► Fix plan generated (L2: resize instance)
                                          │
You: "approve fix plan 7"                 ▼
 └──► Approval gate ──► Plan status: approved
                                          │
You: "execute plan 7"                     ▼
 └──► Main Agent ──► Executor Agent ──► Pre-check → Execute → Post-check
                                          │
                                    Issue resolved ──► KB case study saved
```

---

## Architecture Overview

```mermaid
graph TB
    subgraph "User Interfaces"
        CLI["CLI<br/><code>aiops chat</code>"]
        WEB["Web Dashboard<br/>React + SSE"]
    end

    subgraph "Preprocessing"
        PP["Message Preprocessor<br/>I#/R# refs, @file, uploads<br/>Multimodal content blocks"]
    end

    subgraph "Agent Layer"
        MAIN["Main Agent<br/>(Pure Router)"]
        SCAN["Scan Agent<br/>Resource Discovery"]
        DETECT["Detect Agent<br/>Health Monitoring"]
        RCA["RCA Agent<br/>Root Cause Analysis"]
        SRE["SRE Agent<br/>Fix Planning + Investigation"]
        EXEC["Executor Agent<br/>Fix Execution (L0-L4)"]
        RPT["Reporter Agent<br/>Report Generation"]
    end

    subgraph "Knowledge & Skills"
        KB["Knowledge Base<br/>SOPs + Past Cases"]
        SKILLS["Agent Skills (9)<br/>Domain expertise packages"]
        RAG["RAG Pipeline<br/>Vector search + reranking"]
    end

    subgraph "AWS Infrastructure"
        CW["CloudWatch<br/>Alarms + Metrics"]
        CT["CloudTrail<br/>Change History"]
        STS["STS<br/>AssumeRole"]
        SERVICES["60+ AWS Services<br/>EC2, RDS, EKS, Lambda, ..."]
    end

    subgraph "Data Layer"
        DB["SQLite DB<br/>Issues, Plans, Resources"]
        GRAPH["Graph Engine<br/>NetworkX topology"]
    end

    CLI --> PP
    WEB --> PP
    PP --> MAIN
    MAIN --> SCAN
    MAIN --> DETECT
    MAIN --> RCA
    MAIN --> SRE
    MAIN --> EXEC
    MAIN --> RPT

    RCA --> SKILLS
    SRE --> SKILLS
    RCA --> KB
    SRE --> KB
    RPT --> KB

    SCAN --> STS --> SERVICES
    DETECT --> CW
    RCA --> CT
    EXEC --> SERVICES

    DETECT --> DB
    RCA --> DB
    SRE --> DB
    EXEC --> DB
    SCAN --> DB
    DETECT --> GRAPH
    RCA --> GRAPH
    SRE --> GRAPH

    KB --> RAG
```

---

## Core Workflow: Issue Lifecycle

```mermaid
stateDiagram-v2
    [*] --> Detected : Detect Agent finds anomaly
    Detected --> Acknowledged : User acknowledges (optional)
    Detected --> Investigating : RCA Agent starts analysis
    Acknowledged --> Investigating : RCA Agent starts analysis

    Investigating --> RootCauseIdentified : RCA complete (confidence score)
    RootCauseIdentified --> FixPlanning : SRE Agent generates fix plan

    FixPlanning --> FixReady : Fix plan created (L0-L3)

    FixReady --> FixApproved : User approves plan
    FixApproved --> Executing : Executor Agent runs plan

    Executing --> Resolved : Execution succeeded
    Executing --> FixFailed : Execution failed
    FixFailed --> FixPlanning : Retry with new plan

    Resolved --> [*] : KB case study saved

    note right of Investigating
        Skills activated based on issue type
        CloudTrail + metrics + logs analyzed
        Similar past cases searched
    end note

    note right of FixReady
        L0: Read-only verification
        L1: Low-risk config change
        L2: Service-affecting change
        L3: High-risk (restart, failover)
    end note

    note right of Executing
        Pre-check → Execute → Post-check
        Auto-rollback on failure
        Full audit trail
    end note
```

---

## Agent Routing Logic

```mermaid
flowchart TD
    INPUT["User Message"] --> MAIN["Main Agent<br/>(Router)"]

    MAIN -->|"scan / discover / inventory"| SCAN["Scan Agent"]
    MAIN -->|"health / detect / check / status"| DETECT["Detect Agent"]
    MAIN -->|"analyze / investigate / RCA + I#N"| RCA["RCA Agent"]
    MAIN -->|"fix / plan fix / remediate + I#N"| SRE_A["SRE Agent<br/>(Mode A: Fix Plan)"]
    MAIN -->|"approve + plan ID"| APPROVE["Approval Gate"]
    MAIN -->|"execute + plan ID"| EXEC["Executor Agent"]
    MAIN -->|"report / summary / daily"| RPT["Reporter Agent"]
    MAIN -->|"general AWS question"| SRE_B["SRE Agent<br/>(Mode B: Investigation)"]
    MAIN -->|"network / topology / SPOF"| GRAPH["Graph Engine"]
    MAIN -->|"list skills / activate skill"| SKILLS["Skills System"]

    SCAN --> RESULT["Response to User"]
    DETECT --> RESULT
    RCA --> RESULT
    SRE_A --> RESULT
    SRE_B --> RESULT
    APPROVE --> RESULT
    EXEC --> RESULT
    RPT --> RESULT
    GRAPH --> RESULT
    SKILLS --> RESULT
```

---

## Detection & Analysis Flow (Detail)

```mermaid
flowchart TD
    START["Detect Agent triggered"] --> ACCOUNT["get_active_account<br/>+ assume_role"]
    ACCOUNT --> RESOURCES["get_managed_resources<br/>(only opted-in resources)"]

    RESOURCES --> ALARMS["Check CloudWatch Alarms"]
    ALARMS -->|"ALARM state"| DEEP["Deep Investigation"]
    ALARMS -->|"OK state"| HEALTHY["Mark healthy"]
    ALARMS -->|"No alarm configured"| GAP["Report monitoring gap"]

    DEEP --> METRICS["get_metrics<br/>(1-6 hours)"]
    DEEP --> LOGS["query_logs<br/>(error patterns)"]
    DEEP --> TRAIL["lookup_cloudtrail_events<br/>(recent changes)"]

    METRICS --> STATS["Statistical Detection"]
    STATS --> ZSCORE["Z-score anomaly<br/>detection"]
    STATS --> RULES["Rule evaluation<br/>(CPU > 90% = critical)"]

    DEEP --> NETWORK["Network Health"]
    NETWORK --> VPC["analyze_vpc_topology<br/>(blackhole routes, isolated subnets)"]
    NETWORK --> NAT["NAT Gateway<br/>(ErrorPortAllocation)"]
    NETWORK --> ELB["Load Balancers<br/>(UnHealthyHostCount)"]

    ZSCORE --> ISSUE["create_health_issue<br/>(severity: critical/high/medium/low)"]
    RULES --> ISSUE
    VPC --> ISSUE
    NAT --> ISSUE
    ELB --> ISSUE
```

---

## Fix Execution Pipeline (Detail)

```mermaid
flowchart TD
    START["Executor Agent receives plan_id"] --> VERIFY["1. VERIFY<br/>get_approved_fix_plan"]
    VERIFY -->|"REJECTED"| STOP["STOP immediately"]
    VERIFY -->|"Approved"| GATE["2. GATE<br/>Check executor_enabled"]
    GATE -->|"Disabled"| STOP2["STOP + report"]
    GATE -->|"Enabled"| PRE["3. PRE-CHECK<br/>Execute plan.pre_checks"]

    PRE -->|"Any check fails"| ABORT["ABORT<br/>save_execution_result(aborted)"]
    PRE -->|"All pass"| EXEC["4. EXECUTE<br/>Run plan.steps in order"]

    EXEC -->|"Step fails"| ROLLBACK["6. ROLLBACK<br/>Reverse order"]
    EXEC -->|"All succeed"| POST["5. POST-CHECK<br/>Execute plan.post_checks"]

    ROLLBACK -->|"Rollback OK"| FINAL_RB["FINALIZE<br/>status: rolled_back"]
    ROLLBACK -->|"Rollback fails"| FINAL_FAIL["FINALIZE<br/>status: failed<br/>(rollback also failed)"]

    POST --> FINAL_OK["7. FINALIZE<br/>status: succeeded"]
    FINAL_OK --> RESOLVE["Auto-resolve issue<br/>+ save KB case study"]

    style STOP fill:#f66
    style STOP2 fill:#f66
    style ABORT fill:#f96
    style FINAL_FAIL fill:#f66
    style FINAL_RB fill:#f96
    style FINAL_OK fill:#6f6
    style RESOLVE fill:#6f6
```

---

## Skills & Knowledge Base Flow

```mermaid
flowchart LR
    subgraph "Progressive Disclosure"
        PROMPT["System Prompt<br/>~100 tokens/skill<br/>(always loaded)"]
        ACTIVATE["activate_skill<br/>~3-5K tokens<br/>(on demand)"]
        REF["read_skill_reference<br/>~2-8K tokens<br/>(deep dive)"]
    end

    subgraph "9 Domain Skills"
        S1["linux-admin"]
        S2["network-engineer"]
        S3["kubernetes-admin"]
        S4["database-admin"]
        S5["elasticsearch"]
        S6["monitoring"]
        S7["log-analysis"]
        S8["aws-compute"]
        S9["aws-storage"]
    end

    subgraph "Execution Tools"
        HOST["run_on_host<br/>(SSM / SSH)"]
        KUBE["run_kubectl<br/>(EKS clusters)"]
    end

    subgraph "Knowledge Base"
        SOP["SOPs<br/>(Standard Procedures)"]
        CASES["Past Cases<br/>(Resolved issues)"]
        VEC["Vector Store<br/>(Semantic search)"]
    end

    PROMPT --> ACTIVATE --> REF
    S1 --> ACTIVATE
    S2 --> ACTIVATE
    S3 --> ACTIVATE
    S4 --> ACTIVATE
    S5 --> ACTIVATE
    S6 --> ACTIVATE
    S7 --> ACTIVATE
    S8 --> ACTIVATE
    S9 --> ACTIVATE
    ACTIVATE --> HOST
    ACTIVATE --> KUBE

    RCA["RCA / SRE Agents"] --> SOP
    RCA --> CASES
    SOP --> VEC
    CASES --> VEC
```

---

## Chat Preprocessing Pipeline

```mermaid
flowchart LR
    INPUT["User Message<br/>'analyze @/tmp/error.log I#42'"]

    INPUT --> FILE["@file extraction<br/>CLI: read from disk<br/>Web: multipart upload"]
    INPUT --> REFS["I#/R# resolution<br/>Query DB for context"]

    FILE -->|"Image (.png/.jpeg)"| IMG["Image ContentBlock<br/>(native Strands SDK)"]
    FILE -->|"Document (.pdf/.docx)"| DOC["Document ContentBlock<br/>(native Strands SDK)"]
    FILE -->|"Text (.json/.yaml/.py)"| TXT["<attached_file> XML"]

    REFS --> CTX["<referenced_issue><br/><referenced_resource>"]

    TXT --> ASSEMBLY["Assemble enriched input"]
    CTX --> ASSEMBLY
    IMG --> ASSEMBLY
    DOC --> ASSEMBLY

    ASSEMBLY -->|"Text only"| STR["str<br/>(backward compatible)"]
    ASSEMBLY -->|"Has media"| BLOCKS["list[ContentBlock]<br/>(text + image + document)"]

    STR --> AGENT["Agent.__call__()"]
    BLOCKS --> AGENT
```

---

## Quick Tutorials

### Tutorial 1: First Scan — Discover Your AWS Resources

```bash
# 1. Start interactive chat
aiops chat

# 2. Set your AWS account (if not already configured)
/account set prod

# 3. Scan all resources in all regions
scan all resources in all regions

# 4. Or scan specific services/regions
scan EC2 and RDS in us-east-1 and us-west-2

# 5. View results
/resource list
```

**What happens behind the scenes:**

Main Agent → routes to **Scan Agent** → calls `assume_role` → loops through services (`describe_ec2`, `describe_rds`, ...) → saves to SQLite → returns summary.

---

### Tutorial 2: Health Check — Detect Issues

```bash
# Quick health check (alarm-based, fast)
check health of all services

# Deep health check (adds z-score anomaly detection, slower)
run a deep health check on all services in us-east-1

# Check specific resource type
check health of EC2 instances
```

**What happens:**

Main Agent → **Detect Agent** → checks CloudWatch alarms → pulls metrics/logs for alarming resources → runs statistical detection → creates `HealthIssue` records.

**Output:** A severity-sorted table of issues found, with IDs you can reference as `I#N`.

---

### Tutorial 3: Root Cause Analysis

```bash
# Analyze a specific issue (use the I# from detect results)
analyze I#42

# Or describe the problem naturally
investigate the high CPU on i-0abc123def in us-east-1
```

**What happens:**

Main Agent → **RCA Agent** → activates domain skills (e.g., `linux-admin` for EC2) → searches KB for similar cases → checks CloudTrail for recent changes → gathers metrics/logs → synthesizes root cause with confidence score → generates fix recommendations.

**Output:** Root cause summary, confidence score (0.0–1.0), contributing factors, recommended fix.

---

### Tutorial 4: Generate & Execute a Fix Plan

```bash
# Generate a fix plan
generate a fix plan for I#42

# Review it
/fix 7

# Approve the plan (required before execution)
approve fix plan 7

# Execute
execute plan 7
```

**Risk levels determine approval requirements:**

| Level | Risk | Example | Approval |
|-------|------|---------|----------|
| L0 | Read-only | Verify metric recovered | Auto |
| L1 | Low | Adjust alarm threshold | Auto |
| L2 | Medium | Resize EC2 instance | **Manual** |
| L3 | High | Restart service, failover | **Manual** |

**Execution flow:** Pre-checks → Execute steps → Post-checks → Auto-rollback on failure.

---

### Tutorial 5: Using the Web Dashboard

```bash
# Start the web server
aiops web
# or
uvicorn agenticops.web.app:app --reload --port 8000
```

Open `http://localhost:8000/app/dashboard` and explore:

| Page | What You Can Do |
|------|----------------|
| **Dashboard** | Overview stats, recent issues |
| **Chat** | Same as CLI but with SSE streaming, file upload button, session history |
| **Resources** | Browse all scanned AWS resources with filters |
| **Anomalies** | View health issues, click through to RCA and fix plans |
| **Fix Plans** | Review plans, approve, trigger execution |
| **Network** | Interactive topology graph with SRE analysis (SPOF detection, capacity risk) |
| **Reports** | Generate and view daily/incident/inventory reports |
| **Schedules** | Set up cron-based automated scans/detections |
| **Notifications** | Configure alerting channels (email, Slack, PagerDuty) |

**Web chat supports file uploads** — click the paperclip icon to attach screenshots (PNG/JPEG) for visual analysis or PDFs/docs for document analysis.

---

### Tutorial 6: Headless Mode (Scripting & Automation)

```bash
# Single-shot query (prints response and exits)
aiops chat "check health of prod"

# Pipe mode (machine-readable output)
echo "list all critical issues" | aiops chat

# With file attachment
aiops chat "analyze this error log @/tmp/error.log"

# With image analysis
aiops chat "what's wrong in this screenshot @/tmp/dashboard.png"

# Control output detail level (-d / --detail)
aiops chat -d concise "quick status of prod"     # ~500 tokens, bullets only
aiops chat -d medium "check health of EC2"        # ~1500 tokens (default)
aiops chat --detail detailed "deep dive on I#42"  # ~4000 tokens, full narrative

# Chain commands in CI/CD
aiops chat "scan EC2 in us-east-1" && \
aiops chat "check health of EC2" && \
aiops chat "generate daily report"
```

**TTY detection:** Rich formatting when running in terminal, plain text when piped.

**Detail levels:** Use `/detail` in interactive mode or `--detail` in headless mode to control how much detail agents return. `concise` gives root cause + bullets only; `medium` (default) adds evidence + recommendations; `detailed` provides full narrative with complete evidence chain.

---

### Tutorial 7: Network Topology & SRE Analysis

```bash
# View VPC topology
show me the network topology for vpc-0abc123

# Find single points of failure
detect single points of failure in vpc-0abc123

# Check capacity risks
analyze capacity risk in vpc-0abc123

# Simulate removing a network link
what happens if I remove the connection between subnet-aaa and nat-gw-bbb?

# Dependency chain (blast radius)
what depends on i-0abc123def?
```

**Web alternative:** Go to the **Network** page, select a VPC, toggle "Enriched" to see compute resources, and use the SRE Analysis panel for SPOF/capacity/dependency analysis.

---

### Tutorial 8: Using Agent Skills

```bash
# List available skills
list available skills

# Skills are auto-activated during RCA/SRE — but you can also ask directly
activate the kubernetes-admin skill and help me debug pod CrashLoopBackOff

# The agent will:
# 1. activate_skill("kubernetes-admin") — loads decision trees
# 2. Follow the decision tree for CrashLoopBackOff
# 3. Use run_kubectl to inspect the pod
# 4. Read references for deep-dive material if needed
```

**Adding your own skill:** See `skills/ADDING_SKILLS.md` — just create a directory with a `SKILL.md` file, no code changes needed.

---

### Tutorial 9: Reference Shortcuts in Chat

```bash
# Reference a health issue by ID
what is the status of I#42?

# Reference an AWS resource by ID
show me details of R#17

# Combine references
compare I#42 with the config of R#17

# Attach a file for context
analyze this error log @/var/log/app/error.log alongside I#42
```

The preprocessor resolves `I#N` and `R#N` references by querying the database and injecting context blocks into the message before the agent sees it.

---

### Tutorial 10: Reports & Scheduled Operations

```bash
# Generate reports
generate a daily report
generate an incident report for critical issues
generate an inventory report for EC2

# View reports
/report list
/report 3

# Set up scheduled automation
/schedule create

# Example schedules (via web dashboard):
# - Daily health check at 8:00 AM
# - Weekly inventory scan on Mondays
# - Hourly critical-issue detection
```

---

## CLI Slash Command Quick Reference

| Command | Purpose |
|---------|---------|
| `/help` | Show all commands |
| `/account list` | List AWS accounts |
| `/account set <name>` | Switch active account |
| `/scan [region\|all]` | Trigger resource scan |
| `/detect [region\|all]` | Trigger health detection |
| `/issues` | List all health issues |
| `/issue <ID>` | Show issue details |
| `/analyze <ID>` | Trigger RCA |
| `/fix list` | List fix plans |
| `/approve <ID>` | Approve fix plan |
| `/execute <ID>` | Execute fix plan |
| `/report list` | List reports |
| `/context set <key> <val>` | Set chat context |
| `/detail [concise\|medium\|detailed]` | Set agent output detail level |
| `/output json` | Switch to JSON output |
| `/pager auto` | Auto-paginate long output |
| `/exit` | Exit chat |

---

## API Quick Reference (curl)

```bash
BASE=http://localhost:8000/api

# Health check
curl $BASE/health

# Dashboard stats
curl $BASE/stats

# List resources
curl "$BASE/resources?type=ec2&region=us-east-1&limit=20"

# List issues
curl "$BASE/health-issues?severity=critical&status=detected&limit=10"

# Create chat session
curl -X POST $BASE/chat/sessions -H 'Content-Type: application/json' \
  -d '{"title": "My Session"}'

# Send message (SSE stream)
curl -N -X POST $BASE/chat/sessions/{id}/messages \
  -H 'Content-Type: application/json' \
  -d '{"content": "check health of EC2"}'

# Send message with detail level
curl -N -X POST $BASE/chat/sessions/{id}/messages \
  -H 'Content-Type: application/json' \
  -d '{"content": "deep dive on EC2", "detail_level": "detailed"}'

# Upload image for analysis
curl -X POST $BASE/chat/sessions/{id}/messages \
  -F "content=analyze this screenshot" \
  -F "file=@/tmp/dashboard.png"

# Approve fix plan
curl -X PUT $BASE/fix-plans/{id}/approve

# Get network topology
curl "$BASE/graph/vpc/{vpc_id}/enriched?region=us-east-1"

# Detect single points of failure
curl "$BASE/graph/vpc/{vpc_id}/spof?region=us-east-1"
```

---

## Configuration Quick Reference

All settings use env vars with `AIOPS_` prefix. Set via `.env` file or shell:

```bash
# Core
export AIOPS_BEDROCK_MODEL_ID="us.anthropic.claude-sonnet-4-20250514"  # or claude-opus-4-6
export AIOPS_BEDROCK_REGION="us-east-1"
export AIOPS_BEDROCK_MAX_TOKENS=8192

# Features
export AIOPS_EXECUTOR_ENABLED=true     # Enable fix execution (default: false)
export AIOPS_SKILLS_ENABLED=true       # Enable agent skills (default: true)
export AIOPS_EMBEDDING_ENABLED=true    # Enable vector embeddings (default: true)
export AIOPS_AGENT_OUTPUT_DETAIL=medium  # Agent output detail: concise, medium, detailed

# Web
export AIOPS_CORS_ORIGINS="http://localhost:3000,https://myapp.example.com"
export AIOPS_DATABASE_URL="sqlite:///path/to/agenticops.db"
```
