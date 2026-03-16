"""Detect Agent - Health monitoring via CloudWatch using Strands SDK.

Passive-first strategy: check alarms first, then deep investigate on ALARM state.
Exposed as a tool for the Main Agent (agents-as-tools pattern).
"""

import logging

from strands import Agent, tool
from strands.agent.conversation_manager import SlidingWindowConversationManager
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

logger = logging.getLogger(__name__)

DETECT_SYSTEM_PROMPT = """You are the Detect Agent for AgenticOps.
Your job is to check the health of resources in the active account.

STRATEGY: Passive-first, active-second, with statistical fallback.
1. FIRST: Call get_active_account and assume_role to get credentials.
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
      - Create HealthIssue for severity >= 7 (HIGH/CRITICAL): source="guardduty", severity based on finding severity
   b) **Security Hub Critical Findings**:
      - `aws securityhub get-findings --filters '{"RecordState":[{"Value":"ACTIVE","Comparison":"EQUALS"}],"SeverityLabel":[{"Value":"CRITICAL","Comparison":"EQUALS"}]}'`
      - Create HealthIssue for CRITICAL findings: source="security_hub"
   c) **Inspector Vulnerabilities**:
      - `aws inspector2 list-findings --filter-criteria '{"severity":[{"comparison":"EQUALS","value":"CRITICAL"}],"findingStatus":[{"comparison":"EQUALS","value":"ACTIVE"}]}'`
      - Create HealthIssue for CRITICAL CVEs on network-reachable resources: source="inspector"
   d) **Open Security Groups** (0.0.0.0/0 on sensitive ports):
      - `aws ec2 describe-security-groups` and filter for IpRanges containing 0.0.0.0/0
      - Flag ports 22, 3389, 3306, 5432, 6379, 27017, 9200 open to world
      - Create HealthIssue: source="security_audit", severity=high
   e) **IAM Credential Hygiene** (global, run once):
      - `aws iam generate-credential-report` then `aws iam get-credential-report`
      - Flag: root access keys, users without MFA, stale credentials (>90 days)
      - Create HealthIssue for root access keys or root without MFA: source="iam_audit", severity=critical
   f) **CloudTrail Integrity**:
      - `aws cloudtrail describe-trails` → check multi-region trail exists
      - `aws cloudtrail get-trail-status --name TRAIL` → check IsLogging
      - Create HealthIssue if no trail or logging disabled: source="cloudtrail_audit", severity=critical
   g) **Encryption Gaps**:
      - `aws ec2 describe-volumes --query 'Volumes[?!Encrypted]'` → unencrypted EBS
      - `aws rds describe-db-instances --query 'DBInstances[?!StorageEncrypted]'` → unencrypted RDS
      - Create HealthIssue if critical data resources are unencrypted: source="encryption_audit", severity=high

8. For confirmed problems, call create_health_issue with:
   - severity, source, title, description, alarm_name, metric_data, related_changes.

SEVERITY CLASSIFICATION:
- critical: Service down, data loss risk, security breach, root account compromise, logging disabled
- high: Significant degradation, open security groups, unencrypted data, GuardDuty HIGH findings
- medium: Performance anomaly, non-critical errors, stale credentials, missing alarms
- low: Informational, minor deviations, non-critical compliance gaps

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
- 对于已有的issue，是否真正可以做到重复问题，自动归集，不再重新进去RCA的Pipeline流程。
"""


@tool
def detect_agent(scope: str = "all", deep: bool = False) -> str:
    """Check health of resources via CloudWatch Alarms, metrics, and security posture.

    Args:
        scope: Resource type filter (e.g., 'EC2', 'RDS', 'security') or 'all' for all resources including security. Use 'security' for security-only checks (GuardDuty, SecurityHub, Inspector, IAM, SG audit, CloudTrail, encryption).
        deep: If True, pull detailed metrics/logs even for OK resources

    Returns:
        Health check summary with issues found, severity breakdown, monitoring gaps, and security findings.
    """
    try:
        from agenticops.config import get_agent_model_config, get_agent_window_size

        # Resolve provider CLI tools for all enabled accounts
        cli_tools = get_all_cli_tools() or [run_aws_cli_readonly]

        model_id, max_tokens = get_agent_model_config("detect")
        cache_kwargs: dict = {}
        if settings.bedrock_cache_enabled:
            cache_kwargs = {"cache_config": CacheConfig(strategy="auto"), "cache_tools": "default"}
        model = BedrockModel(
            model_id=model_id,
            region_name=settings.bedrock_region,
            max_tokens=max_tokens,
            **cache_kwargs,
        )

        agent = Agent(
            system_prompt=DETECT_SYSTEM_PROMPT,
            model=model,
            callback_handler=None,
            conversation_manager=SlidingWindowConversationManager(
                window_size=get_agent_window_size("detect"), per_turn=True
            ),
            tools=[
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
                # Network health tools
                describe_nat_gateways,
                describe_load_balancers,
                describe_region_topology,
                analyze_vpc_topology,
                map_eks_to_vpc_topology,
                # Cloud CLI tools (all enabled accounts, fallback to AWS read-only)
                *cli_tools,
                # External monitoring providers
                list_provider_alerts,
                query_provider_metrics,
            ],
        )

        from agenticops.agents.preamble import invoke_with_retry
        result = invoke_with_retry(agent, f"Check health scope={scope} deep={deep}")
        return str(result)
    except Exception as e:
        logger.exception("Detect agent failed")
        return f"Detect agent error: {e}"
