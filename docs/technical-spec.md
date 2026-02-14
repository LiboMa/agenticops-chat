# AgenticOps v2 — Technical Specification

> Spec-Driven Development Document
> Version: 0.1.0 | Date: 2026-02-08
> Framework: Strands Agents SDK + Amazon Bedrock
> Runtime: Local Dev → Amazon Bedrock AgentCore (Production)

---

## 1. System Overview

### 1.1 Vision

An Agent-First Cloud Observability Platform for AWS. Multi-Agent architecture where specialized agents collaborate through a shared Metadata layer, orchestrated by a primary agent. Human-in-the-loop at L3-L4 automation level: the system proactively detects, analyzes, and recommends — humans decide and approve.

### 1.2 Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                        CLI / Chat                           │
│                   (prompt_toolkit based)                     │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                    Main Agent (Orchestrator)                 │
│              Strands Agent + Agents-as-Tools                │
│                                                             │
│  Tools: scan_agent, detect_agent, rca_agent,                │
│         reporter_agent, read_metadata, update_metadata,     │
│         cli_tools                                           │
└────┬──────────┬──────────┬──────────┬───────────────────────┘
     │          │          │          │
     ▼          ▼          ▼          ▼
┌─────────┐┌─────────┐┌─────────┐┌──────────┐
│  Scan   ││ Detect  ││  RCA    ││ Reporter │
│  Agent  ││  Agent  ││  Agent  ││  Agent   │
└────┬────┘└────┬────┘└────┬────┘└────┬─────┘
     │          │          │          │
     ▼          ▼          ▼          ▼
┌─────────────────────────────────────────────────────────────┐
│                    Shared Infrastructure                     │
│                                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │   Metadata   │  │  Knowledge   │  │   Session Mgmt   │  │
│  │   (SQLite)   │  │  Base (MD)   │  │  (Strands File)  │  │
│  └──────────────┘  └──────────────┘  └──────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

### 1.3 Technology Stack

| Component | Technology | Rationale |
|-----------|-----------|-----------|
| Agent Framework | Strands Agents SDK | Native AgentCore deploy, built-in MCP, agent-as-tool |
| LLM | Amazon Bedrock (Claude 3.5 Sonnet) | Local credentials, no API key management |
| Storage | SQLite (via SQLAlchemy) | Zero-config, concurrent read, transaction support |
| Knowledge Base | Markdown files (local) | Human-readable, git-trackable, future → S3 + vector |
| Session | Strands FileSessionManager | Built-in persistence, AgentCore compatible |
| CLI | Click + prompt_toolkit | Rich terminal UX, history, autocomplete |
| Observability | Strands built-in OTEL | Traces, metrics, token tracking |
| AWS Access | boto3 + STS AssumeRole | Cross-account, least privilege |

---

## 2. Project Structure

```
agenticops/
├── pyproject.toml
├── README.md
├── docs/
│   ├── architecture-discussion.md
│   └── technical-spec.md              # This file
├── data/
│   ├── agenticops.db                  # SQLite metadata
│   ├── knowledge_base/
│   │   ├── sops/                      # Standard Operating Procedures
│   │   │   ├── ec2-cpu-high.md
│   │   │   ├── rds-connection-exhausted.md
│   │   │   └── lambda-timeout.md
│   │   ├── patterns/                  # Abstracted failure patterns
│   │   └── cases/                     # Structured case studies (Reporter output)
│   ├── reports/
│   └── sessions/                      # Strands session files
├── src/agenticops/
│   ├── __init__.py
│   ├── config.py                      # Settings (Pydantic)
│   ├── models.py                      # SQLAlchemy models (Metadata)
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── main_agent.py             # Orchestrator
│   │   ├── scan_agent.py             # Resource scanning
│   │   ├── detect_agent.py           # Health detection
│   │   ├── rca_agent.py              # Root cause analysis
│   │   └── reporter_agent.py         # Report & case study generation
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── aws_tools.py              # boto3 wrappers (scan, describe, etc.)
│   │   ├── cloudwatch_tools.py       # Alarms, Metrics, Logs
│   │   ├── cloudtrail_tools.py       # Change event lookup
│   │   ├── metadata_tools.py         # Read/write metadata DB
│   │   └── kb_tools.py              # Knowledge Base read/write/search
│   ├── cli/
│   │   ├── __init__.py
│   │   ├── main.py                   # Click CLI entry point
│   │   └── chat.py                   # Interactive chat (prompt_toolkit)
│   └── web/                          # (Phase 3+, deferred)
└── tests/
```

---

## 3. Metadata Schema (SQLAlchemy Models)

### 3.1 Core Tables

```python
# models.py — Key tables only, full implementation in code

class CloudAccount(Base):
    """AWS account configuration."""
    __tablename__ = "cloud_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    provider: Mapped[str] = mapped_column(String(20), default="aws")  # Future: azure, gcp
    account_id: Mapped[str] = mapped_column(String(20), unique=True)
    role_arn: Mapped[str] = mapped_column(String(200))
    external_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    regions: Mapped[list] = mapped_column(JSON, default=list)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_scanned_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class Resource(Base):
    """Scanned cloud resource inventory."""
    __tablename__ = "resources"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("cloud_accounts.id"))
    resource_id: Mapped[str] = mapped_column(String(200))       # e.g., i-xxx, arn:...
    resource_type: Mapped[str] = mapped_column(String(50))       # EC2, RDS, Lambda, etc.
    resource_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    region: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(30), default="unknown")
    managed: Mapped[bool] = mapped_column(default=False)         # User opted-in for monitoring
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    tags: Mapped[dict] = mapped_column(JSON, default=dict)
    discovered_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow,
                                                  onupdate=datetime.utcnow)


class HealthIssue(Base):
    """Detected health issues."""
    __tablename__ = "health_issues"

    id: Mapped[int] = mapped_column(primary_key=True)
    resource_id: Mapped[int] = mapped_column(ForeignKey("resources.id"))
    severity: Mapped[str] = mapped_column(String(20))            # critical, high, medium, low
    source: Mapped[str] = mapped_column(String(50))              # cloudwatch_alarm, metric_anomaly, log_pattern
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text)
    alarm_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    metric_data: Mapped[dict] = mapped_column(JSON, default=dict)
    related_changes: Mapped[list] = mapped_column(JSON, default=list)  # CloudTrail events
    status: Mapped[str] = mapped_column(String(30), default="open")
    # Lifecycle: open → investigating → root_cause_identified → fix_planned
    #            → fix_approved → fix_executed → resolved
    detected_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    detected_by: Mapped[str] = mapped_column(String(50), default="detect_agent")
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class RCAResult(Base):
    """Root cause analysis results."""
    __tablename__ = "rca_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    health_issue_id: Mapped[int] = mapped_column(ForeignKey("health_issues.id"))
    root_cause: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(default=0.0)
    contributing_factors: Mapped[list] = mapped_column(JSON, default=list)
    recommendations: Mapped[list] = mapped_column(JSON, default=list)
    fix_plan: Mapped[dict] = mapped_column(JSON, default=dict)   # Structured remediation steps
    fix_risk_level: Mapped[str] = mapped_column(String(20), default="unknown")  # L0-L3
    sop_used: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)  # KB SOP path
    similar_cases: Mapped[list] = mapped_column(JSON, default=list)  # Historical case refs
    model_id: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    user_feedback: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # 👍/👎


class AgentLog(Base):
    """Agent execution audit trail."""
    __tablename__ = "agent_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    agent_name: Mapped[str] = mapped_column(String(50))
    action: Mapped[str] = mapped_column(String(100))
    input_summary: Mapped[str] = mapped_column(Text)
    output_summary: Mapped[str] = mapped_column(Text)
    tool_calls: Mapped[int] = mapped_column(default=0)
    input_tokens: Mapped[int] = mapped_column(default=0)
    output_tokens: Mapped[int] = mapped_column(default=0)
    duration_ms: Mapped[int] = mapped_column(default=0)
    status: Mapped[str] = mapped_column(String(20), default="success")
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
```

---

## 4. Agent Specifications

### 4.1 Main Agent (Orchestrator)

```python
# agents/main_agent.py

from strands import Agent
from strands.models.bedrock import BedrockModel

SYSTEM_PROMPT = """You are AgenticOps, an AI-powered AWS cloud operations assistant.

You coordinate specialized agents to help users manage their AWS infrastructure:
- scan_agent: Discovers and inventories AWS resources
- detect_agent: Checks health via CloudWatch Alarms and metrics
- rca_agent: Performs root cause analysis on detected issues
- reporter_agent: Generates reports and case studies

RULES:
1. Always check metadata (active account, resource inventory) before dispatching tasks.
2. For destructive or write operations, ALWAYS present the plan and wait for user approval.
3. Summarize agent results clearly. Show severity, affected resources, and recommended actions.
4. When multiple issues exist, prioritize by severity (critical > high > medium > low).
5. Track and report token usage when asked.

You also have direct tools for metadata queries and CLI operations.
"""

model = BedrockModel(
    model_id="anthropic.claude-3-5-sonnet-20241022-v2:0",
    region_name="us-east-1",
)

main_agent = Agent(
    system_prompt=SYSTEM_PROMPT,
    model=model,
    tools=[
        scan_agent,          # Agent-as-tool
        detect_agent,        # Agent-as-tool
        rca_agent,           # Agent-as-tool
        reporter_agent,      # Agent-as-tool
        read_metadata,       # Direct tool
        update_metadata,     # Direct tool
        get_active_account,  # Direct tool
    ],
)
```

### 4.2 Scan Agent

```python
# agents/scan_agent.py

from strands import Agent, tool
from strands.models.bedrock import BedrockModel

SCAN_SYSTEM_PROMPT = """You are the Scan Agent for AgenticOps.
Your job is to discover and inventory AWS resources in the active account.

WORKFLOW:
1. Get the active account from metadata.
2. Use STS AssumeRole to get credentials for the target account.
3. Scan requested services across configured regions.
4. Save discovered resources to metadata (resources table).
5. Return a summary: count by service, count by region, new vs updated.

RULES:
- Only READ operations. Never create, modify, or delete AWS resources.
- If a service/region fails, log the error and continue with others.
- Mark resources as managed=False by default (user opts in later).
"""

@tool
def scan_agent(services: str = "all", regions: str = "all") -> str:
    """Scan AWS resources in the active account and update inventory.

    Args:
        services: Comma-separated service names (EC2,RDS,Lambda,S3,ECS,EKS,DynamoDB,SQS,SNS) or 'all'
        regions: Comma-separated AWS regions or 'all' (uses account configured regions)

    Returns:
        Summary of discovered resources with counts by service and region.
    """
    agent = Agent(
        system_prompt=SCAN_SYSTEM_PROMPT,
        model=BedrockModel(model_id="anthropic.claude-3-5-sonnet-20241022-v2:0"),
        callback_handler=None,  # Suppress intermediate output
        tools=[
            assume_role,           # STS AssumeRole
            describe_ec2,          # EC2 describe instances
            list_lambda_functions, # Lambda list/get
            describe_rds,          # RDS describe instances
            list_s3_buckets,       # S3 list buckets
            describe_ecs,          # ECS clusters/services/tasks
            describe_eks,          # EKS clusters
            list_dynamodb,         # DynamoDB tables
            list_sqs,              # SQS queues
            list_sns,              # SNS topics
            save_resources,        # Write to metadata DB
            get_active_account,    # Read active account config
        ],
    )
    result = agent(f"Scan services={services} regions={regions}")
    return str(result)
```

### 4.3 Detect Agent

```python
# agents/detect_agent.py

DETECT_SYSTEM_PROMPT = """You are the Detect Agent for AgenticOps.
Your job is to check the health of managed resources.

STRATEGY: Passive-first, active-second.
1. FIRST: Check CloudWatch Alarms for all managed resources.
   - If alarm state = ALARM → this is a confirmed issue, pull detailed metrics.
   - If alarm state = OK → skip (or low-priority spot check if requested).
   - If NO alarm exists for a managed resource → flag as "monitoring gap".
2. ONLY when alarm is triggered OR main agent requests deep investigation:
   - Pull CloudWatch Metrics (last 1-6 hours).
   - Pull recent CloudWatch Logs (error patterns).
   - Pull CloudTrail events (recent changes to this resource).
3. Create HealthIssue records in metadata for confirmed problems.

SEVERITY CLASSIFICATION:
- critical: Service down, data loss risk, security breach
- high: Significant degradation, approaching limits
- medium: Performance anomaly, non-critical errors
- low: Informational, minor deviations

RULES:
- Only READ operations on AWS.
- Always include related_changes (CloudTrail) in HealthIssue records.
- Do NOT call LLM for simple alarm state checks — use tools directly.
"""

@tool
def detect_agent(scope: str = "all", deep: bool = False) -> str:
    """Check health of managed resources via CloudWatch Alarms and metrics.

    Args:
        scope: Resource type filter (e.g., 'EC2', 'RDS') or 'all' managed resources
        deep: If True, pull detailed metrics/logs even for OK resources

    Returns:
        Health check summary with issues found, severity breakdown, and monitoring gaps.
    """
    agent = Agent(
        system_prompt=DETECT_SYSTEM_PROMPT,
        model=BedrockModel(model_id="anthropic.claude-3-5-sonnet-20241022-v2:0"),
        callback_handler=None,
        tools=[
            assume_role,
            list_alarms,              # CloudWatch DescribeAlarms
            get_alarm_history,        # CloudWatch alarm state history
            get_metrics,              # CloudWatch GetMetricData
            query_logs,               # CloudWatch Logs Insights
            lookup_cloudtrail_events, # CloudTrail LookupEvents
            get_managed_resources,    # Read managed resources from metadata
            create_health_issue,      # Write HealthIssue to metadata
        ],
    )
    result = agent(f"Check health scope={scope} deep={deep}")
    return str(result)
```

### 4.4 RCA Agent

```python
# agents/rca_agent.py

RCA_SYSTEM_PROMPT = """You are the RCA Agent for AgenticOps.
Your job is to perform Root Cause Analysis on detected health issues.

METHODOLOGY:
1. Read the HealthIssue details from metadata.
2. Search Knowledge Base for matching SOPs (by resource_type + issue pattern).
3. Search Knowledge Base for similar historical cases.
4. Gather additional context:
   - Resource configuration and tags
   - Related CloudTrail changes (CRITICAL: 80% of issues are caused by changes)
   - Metrics trends (not just current values)
   - Dependency information (if available)
5. Synthesize root cause analysis using SOP steps + evidence + LLM reasoning.
6. Generate fix_plan with risk level classification.

FIX RISK LEVELS:
- L0: Read-only diagnostic commands (always safe)
- L1: Low-risk (restart task, clear cache) — single confirmation
- L2: Medium-risk (modify config, update parameters) — double confirmation
- L3: High-risk (delete, failover, IAM changes) — confirmation code + rollback plan

OUTPUT FORMAT (structured):
- root_cause: Clear statement of the root cause
- confidence: 0.0-1.0
- contributing_factors: List of contributing factors
- recommendations: Ordered list of actions
- fix_plan: Step-by-step remediation with risk level per step
- sop_used: Which SOP was referenced (if any)

RULES:
- Always check CloudTrail changes FIRST before other analysis.
- If confidence < 0.5, explicitly state uncertainty and suggest manual investigation.
- Never fabricate evidence. If data is missing, say so.
"""

@tool
def rca_agent(issue_id: int) -> str:
    """Perform Root Cause Analysis on a specific health issue.

    Args:
        issue_id: The HealthIssue ID from metadata to analyze.

    Returns:
        Structured RCA report with root cause, confidence, factors, and fix plan.
    """
    agent = Agent(
        system_prompt=RCA_SYSTEM_PROMPT,
        model=BedrockModel(model_id="anthropic.claude-3-5-sonnet-20241022-v2:0"),
        callback_handler=None,
        tools=[
            get_health_issue,          # Read specific issue from metadata
            get_resource_details,      # Read resource config from metadata
            search_sops,               # Search KB SOPs by resource_type + pattern
            search_similar_cases,      # Search KB cases by similarity
            lookup_cloudtrail_events,  # CloudTrail for change correlation
            get_metrics,               # Additional metric context
            save_rca_result,           # Write RCA result to metadata
        ],
    )
    result = agent(f"Analyze health issue ID={issue_id}")
    return str(result)
```

### 4.5 Reporter Agent

```python
# agents/reporter_agent.py

REPORTER_SYSTEM_PROMPT = """You are the Reporter Agent for AgenticOps.
Your job is to generate reports and distill operational knowledge.

TWO MODES:

MODE 1 — Daily/On-demand Report:
- Summarize current state: accounts, resources, open issues, recent RCAs.
- Highlight critical items requiring attention.
- Include trends (new issues vs resolved).

MODE 2 — Case Study Generation (post-incident):
- Act as a "senior post-mortem expert".
- Take raw incident data (HealthIssue + RCA + fix actions) and produce a structured case study.
- DENOISE: Replace specific instance IDs with abstract types (i-12345 → EC2_Instance).
- EXTRACT PATTERN: Identify the reusable failure pattern.
- Generate SOP if one doesn't exist for this pattern.
- Save case study and any new SOP to Knowledge Base.

CASE STUDY FORMAT:
```markdown
# [Pattern Name]: [Brief Description]
## Trigger
## Symptoms
## Root Cause
## Resolution Steps
## Prevention
## Related Patterns
```

RULES:
- Reports should be actionable, not just informational.
- Case studies must be generic enough to apply to future similar incidents.
- Always save outputs to Knowledge Base (cases/ or sops/ directory).
"""

@tool
def reporter_agent(mode: str = "daily", issue_id: int = 0) -> str:
    """Generate operational reports or post-incident case studies.

    Args:
        mode: 'daily' for status report, 'case_study' for post-incident analysis
        issue_id: Required for case_study mode — the resolved HealthIssue ID

    Returns:
        Generated report content (markdown).
    """
    agent = Agent(
        system_prompt=REPORTER_SYSTEM_PROMPT,
        model=BedrockModel(model_id="anthropic.claude-3-5-sonnet-20241022-v2:0"),
        callback_handler=None,
        tools=[
            read_all_issues,       # Summary of all health issues
            get_rca_results,       # RCA results for case study
            read_kb_sops,          # Existing SOPs
            write_kb_case,         # Save case study to KB
            write_kb_sop,          # Save new SOP to KB
            get_resource_summary,  # Resource inventory summary
        ],
    )
    result = agent(f"Generate mode={mode} issue_id={issue_id}")
    return str(result)
```

---

## 5. Tool Specifications

### 5.1 AWS Tools (`tools/aws_tools.py`)

All AWS tools use STS AssumeRole for cross-account access. Read-only by default.

```python
from strands import tool

@tool
def assume_role(account_id: str, role_arn: str, region: str, external_id: str = "") -> str:
    """Assume an IAM role in a target AWS account and cache the session.

    Args:
        account_id: AWS account ID
        role_arn: IAM role ARN to assume
        region: AWS region for the session
        external_id: Optional external ID for the trust policy
    """
    # Returns session credentials, cached per account+region

@tool
def describe_ec2(region: str) -> str:
    """Describe all EC2 instances in a region.

    Args:
        region: AWS region
    """

@tool
def list_lambda_functions(region: str) -> str:
    """List all Lambda functions in a region.

    Args:
        region: AWS region
    """

# Similar tools for: describe_rds, list_s3_buckets, describe_ecs,
# describe_eks, list_dynamodb, list_sqs, list_sns
```

### 5.2 CloudWatch Tools (`tools/cloudwatch_tools.py`)

```python
@tool
def list_alarms(region: str, resource_type: str = "", state: str = "") -> str:
    """List CloudWatch Alarms, optionally filtered by resource type or state.

    Args:
        region: AWS region
        resource_type: Filter by resource type prefix (e.g., 'AWS/EC2')
        state: Filter by alarm state ('ALARM', 'OK', 'INSUFFICIENT_DATA')
    """

@tool
def get_metrics(resource_id: str, resource_type: str, region: str,
                metric_names: str = "", hours: int = 1) -> str:
    """Get CloudWatch metrics for a specific resource.

    Args:
        resource_id: AWS resource identifier
        resource_type: Service type (EC2, RDS, Lambda, etc.)
        region: AWS region
        metric_names: Comma-separated metric names, or empty for defaults
        hours: Hours of data to retrieve (1-72)
    """

@tool
def query_logs(log_group: str, region: str, query: str = "",
               hours: int = 1) -> str:
    """Run a CloudWatch Logs Insights query.

    Args:
        log_group: Log group name or pattern
        region: AWS region
        query: Logs Insights query string (default: error/exception filter)
        hours: Hours of logs to search
    """
```

### 5.3 CloudTrail Tools (`tools/cloudtrail_tools.py`)

```python
@tool
def lookup_cloudtrail_events(resource_id: str, region: str,
                              hours: int = 2) -> str:
    """Look up recent CloudTrail events for a resource.

    This is CRITICAL for RCA — 80% of production issues are caused by changes.

    Args:
        resource_id: AWS resource name or ID
        region: AWS region
        hours: Hours of history to search (1-24)

    Returns:
        List of recent change events with: event_name, time, user, source_ip
    """
```

### 5.4 Metadata Tools (`tools/metadata_tools.py`)

```python
@tool
def get_active_account() -> str:
    """Get the currently active AWS account configuration."""

@tool
def get_managed_resources(resource_type: str = "", region: str = "") -> str:
    """List resources that are opted-in for monitoring (managed=True).

    Args:
        resource_type: Filter by type (EC2, RDS, etc.) or empty for all
        region: Filter by region or empty for all
    """

@tool
def save_resources(resources_json: str) -> str:
    """Save or update discovered resources in metadata.

    Args:
        resources_json: JSON array of resource objects to upsert
    """

@tool
def create_health_issue(resource_id: int, severity: str, source: str,
                         title: str, description: str,
                         related_changes: str = "[]") -> str:
    """Create a new health issue record.

    Args:
        resource_id: Internal resource ID from metadata
        severity: critical|high|medium|low
        source: cloudwatch_alarm|metric_anomaly|log_pattern|manual
        title: Brief issue title
        description: Detailed description
        related_changes: JSON array of CloudTrail events
    """

@tool
def save_rca_result(health_issue_id: int, root_cause: str, confidence: float,
                     contributing_factors: str, recommendations: str,
                     fix_plan: str, fix_risk_level: str,
                     sop_used: str = "") -> str:
    """Save RCA analysis result to metadata.

    Args:
        health_issue_id: The HealthIssue ID
        root_cause: Root cause description
        confidence: Confidence score 0.0-1.0
        contributing_factors: JSON array of factors
        recommendations: JSON array of recommendations
        fix_plan: JSON object with step-by-step remediation
        fix_risk_level: L0|L1|L2|L3
        sop_used: Path to SOP used (if any)
    """
```

### 5.5 Knowledge Base Tools (`tools/kb_tools.py`)

```python
@tool
def search_sops(resource_type: str, issue_pattern: str) -> str:
    """Search Knowledge Base for matching SOPs.

    Args:
        resource_type: AWS resource type (EC2, RDS, Lambda, etc.)
        issue_pattern: Issue pattern keywords (e.g., 'cpu high', 'connection timeout')

    Returns:
        Matching SOP content or 'No SOP found' message.
    """

@tool
def search_similar_cases(resource_type: str, issue_pattern: str,
                          limit: int = 3) -> str:
    """Search Knowledge Base for similar historical cases.

    Args:
        resource_type: AWS resource type
        issue_pattern: Issue pattern keywords
        limit: Max cases to return

    Returns:
        Matching case studies with root causes and resolutions.
    """

@tool
def write_kb_case(filename: str, content: str) -> str:
    """Write a case study to the Knowledge Base.

    Args:
        filename: Case filename (e.g., '2026-02-08-rds-cpu-spike.md')
        content: Markdown content of the case study
    """

@tool
def write_kb_sop(filename: str, content: str) -> str:
    """Write or update an SOP in the Knowledge Base.

    Args:
        filename: SOP filename (e.g., 'rds-connection-exhausted.md')
        content: Markdown content of the SOP
    """
```

---

## 6. IAM Permissions

### 6.1 ReadOnly Role (Scan, Detect, RCA Agents)

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ResourceDiscovery",
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
        "sns:List*", "sns:Get*"
      ],
      "Resource": "*"
    },
    {
      "Sid": "Monitoring",
      "Effect": "Allow",
      "Action": [
        "cloudwatch:DescribeAlarms",
        "cloudwatch:DescribeAlarmHistory",
        "cloudwatch:GetMetricData",
        "cloudwatch:ListMetrics",
        "logs:DescribeLogGroups",
        "logs:StartQuery",
        "logs:GetQueryResults"
      ],
      "Resource": "*"
    },
    {
      "Sid": "ChangeTracking",
      "Effect": "Allow",
      "Action": [
        "cloudtrail:LookupEvents"
      ],
      "Resource": "*"
    }
  ]
}
```

### 6.2 Operator Role (SRE Agent — Phase 3)

Deferred. Will be scoped per-action with explicit resource constraints.

---

## 7. CLI Interface

### 7.1 Command Structure

```bash
# Account management
aiops account add <name> --account-id <id> --role-arn <arn> --regions <r1,r2>
aiops account list
aiops account activate <name>

# Resource management
aiops resource list [--type TYPE] [--region REGION] [--managed]
aiops resource manage <resource_id>      # Opt-in for monitoring
aiops resource unmanage <resource_id>    # Opt-out

# Operations (dispatch to agents)
aiops scan [--services SVC] [--regions REGIONS]
aiops detect [--scope TYPE] [--deep]
aiops analyze <issue_id>
aiops report [--type daily|case_study] [--issue-id ID]

# Queries
aiops issues [--severity SEV] [--status STATUS]
aiops issue <id>                         # Show issue + RCA details

# Interactive
aiops chat                               # Full interactive mode

# System
aiops init                               # Initialize DB + KB structure
aiops status                             # System overview
aiops version
```

### 7.2 Chat Mode

```
You: /status
You: /scan --services EC2,RDS
You: /detect
You: /issues
You: /analyze 3
You: What's causing the RDS CPU spike?
You: /report
You: /exit
```

---

## 8. Implementation Phases

### Phase 1: Core Skeleton (Week 1-2)

**Goal**: Main Agent + Scan Agent working end-to-end via CLI.

Deliverables:
- [ ] `pyproject.toml` with strands-agents, boto3, sqlalchemy, click, prompt_toolkit
- [ ] `config.py` — Settings with Bedrock model config
- [ ] `models.py` — CloudAccount, Resource tables + init_db
- [ ] `tools/aws_tools.py` — assume_role + describe_ec2 (start with one service)
- [ ] `tools/metadata_tools.py` — get_active_account, save_resources, get_managed_resources
- [ ] `agents/scan_agent.py` — Working scan for EC2
- [ ] `agents/main_agent.py` — Orchestrator with scan_agent as tool
- [ ] `cli/main.py` — `aiops init`, `aiops account add/list/activate`, `aiops scan`
- [ ] `cli/chat.py` — Basic interactive chat

**Verification**: `aiops scan --services EC2` discovers EC2 instances and saves to SQLite.

### Phase 2: Detection & Analysis (Week 3-4)

**Goal**: Detect Agent + RCA Agent with CloudTrail integration.

Deliverables:
- [ ] `models.py` — Add HealthIssue, RCAResult tables
- [ ] `tools/cloudwatch_tools.py` — list_alarms, get_metrics, query_logs
- [ ] `tools/cloudtrail_tools.py` — lookup_cloudtrail_events
- [ ] `tools/kb_tools.py` — search_sops, search_similar_cases
- [ ] `agents/detect_agent.py` — Alarm-first detection
- [ ] `agents/rca_agent.py` — RCA with CloudTrail + KB integration
- [ ] `data/knowledge_base/sops/` — 10 initial SOPs (EC2, RDS, Lambda, ECS, S3)
- [ ] CLI: `aiops detect`, `aiops analyze <id>`, `aiops issues`

**Verification**: Detect finds CloudWatch Alarm in ALARM state → creates HealthIssue → RCA produces root cause with CloudTrail change correlation.

### Phase 3: Knowledge Flywheel + Cross-Account (Week 5-6)

**Goal**: Reporter Agent + case study generation + feedback loop + Landing Zone support.

Deliverables:
- [ ] `agents/reporter_agent.py` — Daily reports + case study generation
- [ ] `tools/kb_tools.py` — write_kb_case, write_kb_sop
- [ ] `models.py` — Add AgentLog table + AccountTopology table
- [ ] `tools/metadata_tools.py` — Add RuntimeContext for multi-account scope resolution
- [ ] `tools/fault_domain_tools.py` — collect_fault_domain (cross-account signal aggregation)
- [ ] Multi-account support in Tool layer (resolve_accounts loop, Agent unchanged)
- [ ] Cross-Region parallel execution in scan/detect tools (ThreadPoolExecutor)
- [ ] User feedback mechanism (👍/👎 on RCA results)
- [ ] CLI: `aiops report`, `aiops feedback <rca_id> <up|down>`
- [ ] CLI: `aiops topology add/list/remove`
- [ ] CLI: `--account`, `--all`, `--group` scope parameters on scan/detect/issues
- [ ] Expand scan to all services (RDS, Lambda, S3, ECS, EKS, DynamoDB, SQS, SNS)

**Verification**: 
- After resolving an issue, Reporter generates case study, extracts pattern, saves SOP. Next similar issue → RCA finds and uses the SOP.
- Multi-account scan works with `aiops scan --all`, Agent prompt/tools unchanged from Phase 1.
- RCA on Workload account issue automatically collects Network Account signals via topology.

### Phase 4: Production Readiness (Week 7-8)

**Goal**: Polish, security, AgentCore preparation.

Deliverables:
- [ ] Session management (Strands FileSessionManager)
- [ ] Token usage tracking and cost reporting
- [ ] Comprehensive error handling and retry strategies
- [ ] SRE Agent (report-only mode — generates fix plans, no execution)
- [ ] Intelligent topology discovery (auto-detect TGW attachments, VPC Peering, RAM shares)
- [ ] AgentCore deployment configuration
- [ ] MCP tool integration (AWS Official MCP servers)

---

## 9. Verification Criteria

Each phase must pass these checks before proceeding:

| Check | Description |
|-------|-------------|
| **Functional** | Agent completes its primary task end-to-end |
| **Data Integrity** | Metadata correctly updated after each operation |
| **Error Handling** | Graceful failure on AWS API errors, invalid input |
| **Token Efficiency** | Agent doesn't make unnecessary LLM calls |
| **Security** | No credentials logged, no write operations without approval |
| **CLI UX** | Clear output, proper formatting, helpful error messages |

---

## 10. Dependencies

```toml
[project]
name = "agenticops"
version = "0.2.0"
requires-python = ">=3.11"
dependencies = [
    "strands-agents[bedrock]",
    "boto3>=1.35.0",
    "sqlalchemy>=2.0",
    "click>=8.0",
    "prompt-toolkit>=3.0",
    "pydantic>=2.0",
    "pydantic-settings>=2.0",
    "rich>=13.0",
]
```

---

## 11. Key Design Decisions Log

| # | Decision | Rationale | Date |
|---|----------|-----------|------|
| 1 | Strands SDK over LangChain | Native AgentCore deploy, built-in MCP, simpler API | 2026-02-08 |
| 2 | Agents-as-Tools pattern | Strands native, clean separation, focused context windows | 2026-02-08 |
| 3 | SQLite over JSON for metadata | Concurrent read, transactions, query efficiency | 2026-02-08 |
| 4 | Passive-first detection | Avoid costly full-scan polling, leverage existing Alarms | 2026-02-08 |
| 5 | CloudTrail as first-class signal | 80% of issues are change-induced, critical for RCA accuracy | 2026-02-08 |
| 6 | Markdown KB over vector DB (Phase 1) | Simple, human-readable, git-trackable, sufficient for rule-based search | 2026-02-08 |
| 7 | L3-L4 automation ceiling | Human-in-the-loop for all write operations, trust boundary | 2026-02-08 |
| 8 | Bedrock Claude 3.5 Sonnet | Best reasoning for ops tasks, local credential access | 2026-02-08 |
| 9 | Multi-account transparent to Agent | Tool layer absorbs account routing via RuntimeContext; zero token overhead | 2026-02-08 |
| 10 | Account serial, Region parallel | STS session safety (serial accounts), performance (parallel regions) | 2026-02-08 |
| 11 | Account Topology + Fault Domain | Landing Zone cross-account RCA via static topology config + dynamic signal collection | 2026-02-08 |

---

*Last updated: 2026-02-09*
*Next review: After Phase 1 completion*
