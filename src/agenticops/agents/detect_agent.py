"""Detect Agent - Health monitoring via CloudWatch using Strands SDK.

Passive-first strategy: check alarms first, then deep investigate on ALARM state.
Exposed as a tool for the Main Agent (agents-as-tools pattern).
"""

import logging

from strands import Agent, tool
from strands.models.bedrock import BedrockModel
from strands.models.model import CacheConfig

from agenticops.config import settings
from agenticops.tools.aws_tools import assume_role
from agenticops.tools.network_tools import (
    describe_nat_gateways,
    describe_load_balancers,
    describe_region_topology,
    analyze_vpc_topology,
)
from agenticops.tools.eks_tools import map_eks_to_vpc_topology
from agenticops.tools.cloudwatch_tools import (
    list_alarms,
    get_alarm_history,
    get_metrics,
    query_logs,
)
from agenticops.tools.cloudtrail_tools import lookup_cloudtrail_events
from agenticops.tools.metadata_tools import (
    get_active_account,
    get_managed_resources,
    create_health_issue,
)
from agenticops.tools.detect_tools import (
    run_zscore_detection,
    run_rule_evaluation,
)
from agenticops.tools.aws_cli_tool import run_aws_cli_readonly  # fallback
from agenticops.providers.base import get_all_cli_tools
from agenticops.tools.integration_tools import (
    list_provider_alerts,
    query_provider_metrics,
)
from agenticops.skills.tools import activate_skill, read_skill_reference
from agenticops.tools.memory_tools import search_agent_memory

logger = logging.getLogger(__name__)

_DOWNGRADE_NOTE = "[degraded: account load failed, ran in single-agent mode]"

DETECT_SYSTEM_PROMPT = """You are the Detect Agent for AgenticOps.
Your job is to check the health of resources in the active account.

STRATEGY: Passive-first, active-second, with statistical fallback.
1. FIRST: Call get_active_account to see enabled accounts. Pass account='<name>' to tools
   when more than one is enabled; single-account deployments resolve automatically.
2. Call get_managed_resources to get the resource inventory to check (only managed=True resources).
3. Call list_alarms to check CloudWatch Alarms for the region.
   - If alarm state = ALARM -> this is a confirmed issue, pull detailed metrics and logs.
   - If alarm state = OK -> report as healthy (or spot check if deep=True).
   - If NO alarm exists for a resource -> note as "no alarm configured".
4. ONLY when alarm is triggered OR deep=True:
   - Call get_metrics for the affected resource (last 1-6 hours).
   - Call query_logs for recent error patterns.
   - Call lookup_cloudtrail_events for recent changes to this resource.
5. NETWORK HEALTH CHECKS:
   - Call analyze_vpc_topology for each VPC to detect blackhole routes, isolated subnets,
     and SG dependency issues. Check reachability_summary.issues for problems.
   - Call describe_nat_gateways to check NAT Gateway state and CloudWatch metrics
     (ErrorPortAllocation, PacketsDropCount are key failure signals).
   - Call describe_load_balancers to check target health — UnHealthyHostCount > 0
     is a top-3 root cause signal. Create HealthIssue for unhealthy targets.
   - For EKS workloads: call map_eks_to_vpc_topology to detect topology issues
     (e.g., private subnets without NAT gateway coverage).
6. STATISTICAL DETECTION (use when deep=True or when alarms are missing):
   - After getting metrics via get_metrics, pass the values to run_zscore_detection
     to identify statistical anomalies that CloudWatch alarms might not catch.
   - Use run_rule_evaluation to check metric values against built-in threshold rules
     (e.g., CPUUtilization > 90% = critical, DatabaseConnections > 100 = medium).
6.5. EXTERNAL PROVIDER ALERTS:
   - Call list_provider_alerts to pull active alerts from external monitoring systems
     (Datadog, Grafana, etc.) that are configured.
   - Call query_provider_metrics to get cross-platform metrics for a resource.
   - Cross-reference external alerts with CloudWatch findings for corroboration.
7. SECURITY HEALTH CHECKS (always run when scope='all' or scope='security'):
   Use the cloud CLI tool for all security checks:
   a) **GuardDuty Threats**:
      - `aws guardduty list-detectors` → get detector ID
      - `aws guardduty list-findings --detector-id DID --finding-criteria '{"Criterion":{"severity":{"Gte":4}}}'`
      - `aws guardduty get-findings --detector-id DID --finding-ids [IDs]` for details
      - Create HealthIssue for severity >= 7: source="guardduty", severity=low (governance) UNLESS active exploitation on reachable service → critical
   b) **Security Hub Critical Findings**:
      - `aws securityhub get-findings --filters '{"RecordState":[{"Value":"ACTIVE","Comparison":"EQUALS"}],"SeverityLabel":[{"Value":"CRITICAL","Comparison":"EQUALS"}]}'`
      - Create HealthIssue for CRITICAL findings: source="security_hub"
   c) **Inspector Vulnerabilities**:
      - `aws inspector2 list-findings --filter-criteria '{"severity":[{"comparison":"EQUALS","value":"CRITICAL"}],"findingStatus":[{"comparison":"EQUALS","value":"ACTIVE"}]}'`
      - Create HealthIssue for CRITICAL CVEs: source="inspector", severity=low (governance) UNLESS network-reachable + actively exploitable → escalate to high
   d) **Open Security Groups** (0.0.0.0/0 on sensitive ports):
      - `aws ec2 describe-security-groups` and filter for IpRanges containing 0.0.0.0/0
      - Flag ports 22, 3389, 3306, 5432, 6379, 27017, 9200 open to world
      - Create HealthIssue: source="security_audit", severity=low (long-term governance)
   e) **IAM Credential Hygiene** (global, run once):
      - `aws iam generate-credential-report` then `aws iam get-credential-report`
      - Flag: root access keys, users without MFA, stale credentials (>90 days)
      - Create HealthIssue for root access keys or root without MFA: source="iam_audit", severity=low (governance)
   f) **CloudTrail Integrity**:
      - `aws cloudtrail describe-trails` → check multi-region trail exists
      - `aws cloudtrail get-trail-status --name TRAIL` → check IsLogging
      - Create HealthIssue if no trail or logging disabled: source="cloudtrail_audit", severity=low (governance)
   g) **Encryption Gaps**:
      - `aws ec2 describe-volumes --query 'Volumes[?!Encrypted]'` → unencrypted EBS
      - `aws rds describe-db-instances --query 'DBInstances[?!StorageEncrypted]'` → unencrypted RDS
      - Create HealthIssue if critical data resources are unencrypted: source="encryption_audit", severity=low (governance)

8. For confirmed problems, call create_health_issue with:
   - severity, source, title, description, alarm_name, metric_data, related_changes.

SEVERITY CLASSIFICATION (SRE priority — reachability first):

Priority 1 — CRITICAL (immediate operational impact, resolve NOW):
- ANY reachability failure: instance unreachable, endpoint down, connection refused/timeout,
  health check failing, DNS resolution failure, port unreachable
- Compute: EC2 StatusCheckFailed, ECS task crash-looping, Lambda invocation errors > 50%
- Networking: NAT Gateway ErrorPortAllocation/PacketsDropCount > 0, VPC blackhole routes,
  ELB UnHealthyHostCount > 0, target group with 0 healthy targets, NLB connection errors
- Database: RDS/Aurora connection failures, replica lag causing read timeouts, cluster failover,
  ElastiCache unreachable, DynamoDB throttling causing request failures
- Storage: S3 5xx errors, EFS mount failures, EBS volume detached/impaired
- Service down, data loss risk imminent

Priority 2 — HIGH (performance degradation, short-term danger signals):
# - CPU/Memory sustained > 90% causing latency spikes
- Memory sustained > 90% causing latency spikes
- Response time P99 > SLA threshold, elevated error rates (>5%)
- Database connection pool exhaustion approaching, replication lag growing
- Network packet loss > 1%, intermittent connectivity, jitter spikes
- Disk IOPS throttling, queue backlog growing rapidly

Priority 3 — MEDIUM (capacity & resource planning):
- Capacity approaching limits: disk > 80%, connections > 70%, IOPS nearing provisioned max
- Performance anomaly (Z-score deviation) without user-facing impact yet
- Missing CloudWatch alarms for critical resources
- Resource utilization trending toward limits (days/weeks horizon)

Priority 4 — LOW (long-term governance, security hardening):
- Security misconfigurations: open SGs, unencrypted volumes, stale credentials (>90 days)
- Compliance gaps: missing CloudTrail, no encryption at rest
- GuardDuty/SecurityHub findings (unless CRITICAL CVE on network-reachable resource → escalate to HIGH)
- IAM hygiene: root access keys, users without MFA
- Informational deviations, minor non-critical findings

ESCALATION RULE: Any security finding that directly enables unauthorized access to a reachable
service (e.g., CRITICAL CVE on internet-facing instance, active exploitation detected by GuardDuty
severity >= 8) should be escalated to CRITICAL.

RULES:
- Only READ operations on AWS. The only write is create_health_issue in our metadata DB.
- Always include related_changes (CloudTrail) in HealthIssue records when available.
- Do NOT call LLM for simple alarm state checks - use tools directly.
- Return a structured summary: total resources checked, alarms found, issues created,
  AND security findings summary (threats, vulnerabilities, misconfigurations, compliance gaps).
TOOL SELECTION — accuracy first:
- Use specialized tools (list_alarms, get_metrics, etc.) when they cover the service.
- Use the cloud CLI tool when: (a) the service has no specialized tool (e.g., security services),
  OR (b) the CLI gives more precise/complete data for the specific query (e.g., specific --query
  filters, fields not exposed by specialized tools).
- Choose whichever tool produces the most accurate result for the task at hand.
- When using the cloud CLI tool, always use --query to filter output fields.
  Example: `aws iam list-roles --query 'Roles[].{Name:RoleName,Arn:Arn}'`
8.5. WEB RESEARCH: When investigating potential service-wide issues, call
     activate_skill("web-research") to load web_fetch, then check cloud provider
     status pages (e.g., AWS Health Dashboard) to confirm whether symptoms are
     caused by an upstream provider outage.

AGENT MEMORY SUPPRESSION:
Before creating a HealthIssue, call search_agent_memory with a keyword summary of the finding.
If a matching memory exists with confidence >= 3, SKIP creating the issue (it was previously
marked as a false positive or known-benign pattern). Log it as "suppressed by memory: {filename}".
If confidence is 1-2, still create the issue but lower severity by one level.
"""


def _build_detect_agent_for_account(
    acct_name: str,
    acct_id: int,
    cli_tool,
    session,
) -> Agent:
    """Build a detect agent scoped to a single account.

    Args:
        acct_name: Human-readable account name
        acct_id: Database account ID
        cli_tool: The CLI tool callable for this specific account
        session: Database session (reserved for future use)

    Returns:
        Agent instance pre-configured for the given account
    """
    from agenticops.config import get_agent_model_config, get_agent_conversation_manager, get_bedrock_boto_session

    model_id, max_tokens = get_agent_model_config("detect")
    cache_kwargs: dict = {}
    if settings.bedrock_cache_enabled:
        cache_kwargs = {"cache_config": CacheConfig(strategy="auto"), "cache_tools": "default"}
    model = BedrockModel(
        model_id=model_id,
        boto_session=get_bedrock_boto_session(),
        max_tokens=max_tokens,
        **cache_kwargs,
    )

    # Account-scoped system prompt preamble
    account_context = (
        f"You are checking account '{acct_name}' (id={acct_id}). "
        f"Use the CLI tool provided to query this account's resources. "
        f"Do NOT call get_active_account or assume_role — you already know which account you're checking."
    )

    from agenticops.agents.preamble import build_system_prompt
    base_prompt = f"{account_context}\n\n{DETECT_SYSTEM_PROMPT}"

    agent = Agent(
        system_prompt=build_system_prompt(base_prompt, include_account=False, agent_name="detect"),
        model=model,
        callback_handler=None,
        conversation_manager=get_agent_conversation_manager("detect"),
        tools=[
            cli_tool,
            get_managed_resources,
            list_alarms,
            get_alarm_history,
            get_metrics,
            query_logs,
            lookup_cloudtrail_events,
            run_zscore_detection,
            run_rule_evaluation,
            describe_nat_gateways,
            describe_load_balancers,
            describe_region_topology,
            analyze_vpc_topology,
            map_eks_to_vpc_topology,
            list_provider_alerts,
            query_provider_metrics,
            create_health_issue,
            # Agent Skills (dynamic tool registration)
            activate_skill,
            read_skill_reference,
            # Agent Memory (cross-agent search)
            search_agent_memory,
        ],
    )
    return agent


@tool
def detect_agent(scope: str = "all", deep: bool = False) -> str:
    """Check resource health via CloudWatch alarms, metrics, and security posture.

    USE FOR: "health", "detect", "issues", "problems", "check", "status", and
    security checks — "security audit", "security posture", "vulnerability",
    "compliance", "GuardDuty", "SecurityHub", "Inspector", "IAM audit"
    (use scope='security' for security-only). Creates HealthIssues for findings.
    NOT FOR: resource inventory (scan_agent) or root-cause analysis (rca_agent).

    Args:
        scope: Resource type filter (e.g., 'EC2', 'RDS', 'security') or 'all'.
        deep: If True, pull detailed metrics/logs even for OK resources.

    Returns:
        Health summary: issues found, severity breakdown, security findings.
    """
    try:
        from agenticops.config import get_agent_model_config, get_agent_conversation_manager, get_bedrock_boto_session
        from agenticops.services.notification_service import batch_mode
        with batch_mode():
            # Check account count to decide parallel vs single-agent mode.
            # Fallback to single-agent if DB is unavailable.
            _downgraded = False
            try:
                from agenticops.scanner.engine import _load_accounts
                accounts = _load_accounts()
            except Exception:
                logger.error(
                    "Failed to load accounts — DEGRADING to single-agent health check",
                    exc_info=True,
                )
                accounts = []
                _downgraded = True

            if len(accounts) > 1:
                # ACCOUNT-SCOPED BY DESIGN: parallel checkers each get a pre-resolved,
                # account-locked cli_tool and account context in their prompt — they
                # intentionally do NOT receive assume_role/get_active_account. The
                # single-agent path below is the multi-account variant. Do not
                # "align" these tool sets; the divergence is deliberate.
                # Multiple accounts: use parallel agentic checker
                import asyncio
                import concurrent.futures
                from agenticops.checker import check_accounts_parallel

                acct_ids = [a.id for a in accounts]
                coro = check_accounts_parallel(account_ids=acct_ids, scope=scope, deep=deep)
                try:
                    asyncio.get_running_loop()
                    # Already inside an async event loop (e.g. scheduler) — run in a thread
                    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                        result = pool.submit(asyncio.run, coro).result()
                except RuntimeError:
                    # No running loop — safe to use asyncio.run()
                    result = asyncio.run(coro)

                lines = [f"Parallel health check: {result.total_issues} issues in {result.duration_s}s"]
                for a in result.accounts:
                    lines.append(f"  {a.account_name}: {a.issues_created} issues")
                    if a.agent_output:
                        lines.append(f"    {a.agent_output[:500]}")
                return "\n".join(lines)
            else:
                # Single account: use original single-agent approach
                cli_tools = get_all_cli_tools() or [run_aws_cli_readonly]

                model_id, max_tokens = get_agent_model_config("detect")
                cache_kwargs: dict = {}
                if settings.bedrock_cache_enabled:
                    cache_kwargs = {"cache_config": CacheConfig(strategy="auto"), "cache_tools": "default"}
                model = BedrockModel(
                    model_id=model_id,
                    boto_session=get_bedrock_boto_session(),
                    max_tokens=max_tokens,
                    **cache_kwargs,
                )

                from agenticops.agents.preamble import build_system_prompt as _bsp
                agent = Agent(
                    system_prompt=_bsp(DETECT_SYSTEM_PROMPT, include_account=False, agent_name="detect"),
                    model=model,
                    callback_handler=None,
                    conversation_manager=get_agent_conversation_manager("detect"),
                    tools=[
                        # Multi-account variant: these two enable account switching,
                        # absent from the account-locked parallel path (see above).
                        assume_role,
                        get_active_account,
                        get_managed_resources,
                        list_alarms,
                        get_alarm_history,
                        get_metrics,
                        query_logs,
                        lookup_cloudtrail_events,
                        create_health_issue,
                        run_zscore_detection,
                        run_rule_evaluation,
                        describe_nat_gateways,
                        describe_load_balancers,
                        describe_region_topology,
                        analyze_vpc_topology,
                        map_eks_to_vpc_topology,
                        *cli_tools,
                        list_provider_alerts,
                        query_provider_metrics,
                        # Agent Skills (dynamic tool registration)
                        activate_skill,
                        read_skill_reference,
                        # Agent Memory (cross-agent search)
                        search_agent_memory,
                    ],
                )

                from agenticops.agents.preamble import invoke_with_retry
                from agenticops.services.agent_log_service import track_agent
                with track_agent("detect", "check_health", f"scope={scope} deep={deep}", parent_agent="main") as tracker:
                    result = invoke_with_retry(agent, f"Check health scope={scope} deep={deep}")
                    tracker.set_result(result)
                return (str(result) + "\n\n" + _DOWNGRADE_NOTE) if _downgraded else str(result)
    except Exception as e:
        logger.exception("Detect agent failed")
        return f"Detect agent error: {e}"
