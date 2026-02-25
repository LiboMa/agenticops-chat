"""Detect Agent - Health monitoring via CloudWatch using Strands SDK.

Passive-first strategy: check alarms first, then deep investigate on ALARM state.
Exposed as a tool for the Main Agent (agents-as-tools pattern).
"""

import logging

from strands import Agent, tool
from strands.models.bedrock import BedrockModel

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
from agenticops.tools.aws_cli_tool import run_aws_cli_readonly

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
7. For confirmed problems, call create_health_issue with:
   - severity, source, title, description, alarm_name, metric_data, related_changes.

SEVERITY CLASSIFICATION:
- critical: Service down, data loss risk, security breach
- high: Significant degradation, approaching limits
- medium: Performance anomaly, non-critical errors
- low: Informational, minor deviations

RULES:
- Only READ operations on AWS. The only write is create_health_issue in our metadata DB.
- Always include related_changes (CloudTrail) in HealthIssue records when available.
- Do NOT call LLM for simple alarm state checks - use tools directly.
- Return a structured summary: total resources checked, alarms found, issues created.
TOOL SELECTION — accuracy first:
- Use specialized tools (list_alarms, get_metrics, etc.) when they cover the service.
- Use run_aws_cli_readonly when: (a) the service has no specialized tool, OR (b) the CLI
  gives more precise/complete data for the specific query (e.g., specific --query filters,
  fields not exposed by specialized tools).
- Choose whichever tool produces the most accurate result for the task at hand.
- When using run_aws_cli_readonly, always use --query to filter output fields.
  Example: `aws iam list-roles --query 'Roles[].{Name:RoleName,Arn:Arn}'`
"""


@tool
def detect_agent(scope: str = "all", deep: bool = False) -> str:
    """Check health of resources via CloudWatch Alarms and metrics.

    Args:
        scope: Resource type filter (e.g., 'EC2', 'RDS') or 'all' for all resources
        deep: If True, pull detailed metrics/logs even for OK resources

    Returns:
        Health check summary with issues found, severity breakdown, and monitoring gaps.
    """
    try:
        model = BedrockModel(
            model_id=settings.bedrock_model_id,
            region_name=settings.bedrock_region,
        )

        agent = Agent(
            system_prompt=DETECT_SYSTEM_PROMPT,
            model=model,
            callback_handler=None,
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
                # AWS CLI (read-only, for uncovered services or precision queries)
                run_aws_cli_readonly,
            ],
        )

        result = agent(f"Check health scope={scope} deep={deep}")
        return str(result)
    except Exception as e:
        logger.exception("Detect agent failed")
        return f"Detect agent error: {e}"
