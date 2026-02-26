"""RCA Agent - Root Cause Analysis using Strands SDK.

Receives a HealthIssue ID, investigates using AWS tools + Knowledge Base,
and persists structured RCA results. Exposed as a tool for the Main Agent
(agents-as-tools pattern).
"""

import logging

from strands import Agent, tool
from strands.agent.conversation_manager import SlidingWindowConversationManager
from strands.models.bedrock import BedrockModel

from agenticops.config import settings
from agenticops.tools.aws_tools import assume_role
from agenticops.tools.cloudwatch_tools import get_metrics, query_logs
from agenticops.tools.cloudtrail_tools import lookup_cloudtrail_events
from agenticops.tools.kb_tools import search_sops, search_similar_cases
from agenticops.tools.network_tools import (
    describe_vpcs,
    describe_subnets,
    describe_security_groups,
    describe_route_tables,
    describe_nat_gateways,
    describe_transit_gateways,
    describe_load_balancers,
    describe_region_topology,
    analyze_vpc_topology,
)
from agenticops.tools.eks_tools import (
    describe_eks_clusters,
    describe_eks_nodegroups,
    check_eks_pod_ip_capacity,
    map_eks_to_vpc_topology,
)
from agenticops.tools.metadata_tools import (
    get_active_account,
    get_managed_resources,
    get_health_issue,
    update_health_issue_status,
    save_rca_result,
)
from agenticops.graph.tools import (
    query_reachability,
    query_impact_radius,
    find_network_path,
    detect_network_anomalies,
)
from agenticops.tools.aws_cli_tool import run_aws_cli_readonly

logger = logging.getLogger(__name__)

RCA_SYSTEM_PROMPT = """You are the RCA Agent for AgenticOps.
Your job is to perform Root Cause Analysis on a specific HealthIssue.

INVESTIGATION PROTOCOL — follow this order strictly:

1. SETUP: Call get_active_account and assume_role to get AWS credentials.
2. READ ISSUE: Call get_health_issue with the given issue_id to understand the problem.
3. SET STATUS: Call update_health_issue_status to set status to 'investigating'.
4. SEARCH KNOWLEDGE BASE:
   a. Call search_sops with the resource type and issue keywords to find relevant SOPs.
   b. Call search_similar_cases with resource type and a full symptom description
      (not just keywords) for better vector-based semantic matching.
5. INVESTIGATE CHANGES (80% of issues are caused by recent changes):
   a. Call lookup_cloudtrail_events for the affected resource (last 24 hours).
   b. Look for deployment, config change, security group, IAM, or scaling events.
5.5. INVESTIGATE NETWORK PATH (when resource has connectivity issues):
   a. Call describe_region_topology to understand cross-VPC connectivity (Transit Gateways,
      peering connections) and identify which VPCs can communicate.
   b. Call analyze_vpc_topology with the affected resource's VPC ID for a holistic view
      of subnets (public/private), routing, gateways, peering, endpoints, SG dependencies,
      and blackhole routes. Check the reachability_summary for issues.
   b. For individual deep-dives, use describe_security_groups, describe_route_tables, etc.
   c. If behind a load balancer, call describe_load_balancers to check target health.
   d. For EKS workloads: call describe_eks_clusters and map_eks_to_vpc_topology to understand
      cluster networking. Use check_eks_pod_ip_capacity if pod scheduling failures are suspected.
      Call describe_eks_nodegroups for node-level health issues.
   e. Call query_reachability to verify subnet internet connectivity with exact path trace.
   f. Call find_network_path for point-to-point traffic path analysis.
   g. Call detect_network_anomalies to find structural issues (routing loops, orphan nodes, blackholes).
   h. Call query_impact_radius to assess blast radius of suspected failed component.
6. INVESTIGATE METRICS:
   a. Call get_metrics for the affected resource (relevant metrics based on resource type).
   b. Call query_logs if log patterns are relevant to the issue.
7. SYNTHESIZE: Combine all evidence into a root cause analysis:
   - Identify the most likely root cause with confidence score (0.0-1.0).
   - List contributing factors.
   - Provide actionable recommendations ordered by impact.
   - Create a fix plan with step-by-step remediation.
   - Assess fix risk level: low, medium, high, or critical.
8. SAVE: Call save_rca_result with all findings.
8.5. EXTENDED INVESTIGATION: Use run_aws_cli_readonly for services not covered
     by specialized tools (ElastiCache, Redshift, Step Functions, API Gateway, etc.).

CONFIDENCE SCORING:
- 0.9-1.0: Clear evidence from CloudTrail + metrics confirming root cause
- 0.7-0.8: Strong correlation but some ambiguity
- 0.5-0.6: Probable cause based on patterns and KB matches
- 0.3-0.4: Multiple possible causes, needs further investigation
- 0.0-0.2: Insufficient data, speculative

FIX RISK LEVELS:
- low: Read-only or config-only changes, no service impact
- medium: May cause brief disruption, easily reversible
- high: Service restart or significant change required
- critical: Data migration, downtime required, or irreversible

RULES:
- Only READ operations on AWS. The only writes are to our metadata DB.
- Always search SOPs and similar cases BEFORE forming conclusions.
- Include CloudTrail evidence when available — cite specific event names and timestamps.
- If you cannot determine root cause with confidence > 0.3, say so explicitly.
- Return a structured summary at the end.
TOOL SELECTION — accuracy first:
- Use specialized tools (get_metrics, query_logs, describe_* tools, etc.) when they cover the service.
- Use run_aws_cli_readonly when: (a) the service has no specialized tool (e.g., ElastiCache,
  Redshift, Step Functions, API Gateway), OR (b) the CLI gives more precise/complete data
  for investigation (e.g., specific fields, parameters not exposed by specialized tools).
- Choose whichever tool produces the most accurate result for the task at hand.
- When using run_aws_cli_readonly, always use --query to filter output fields.
  Example: `aws elasticache describe-cache-clusters --query 'CacheClusters[].{Id:CacheClusterId,Status:CacheClusterStatus,Engine:Engine}'`
"""


@tool
def rca_agent(issue_id: int) -> str:
    """Perform Root Cause Analysis on a HealthIssue.

    Investigates the issue using CloudTrail, CloudWatch metrics/logs,
    and the Knowledge Base (SOPs + similar cases). Saves structured
    RCA results to metadata.

    Args:
        issue_id: The HealthIssue ID to analyze.

    Returns:
        RCA summary with root cause, confidence, recommendations, and fix plan.
    """
    try:
        model = BedrockModel(
            model_id=settings.bedrock_model_id,
            region_name=settings.bedrock_region,
            max_tokens=settings.bedrock_max_tokens,
        )

        agent = Agent(
            system_prompt=RCA_SYSTEM_PROMPT,
            model=model,
            callback_handler=None,
            conversation_manager=SlidingWindowConversationManager(
                window_size=settings.bedrock_window_size, per_turn=True
            ),
            tools=[
                assume_role,
                get_active_account,
                get_managed_resources,
                get_health_issue,
                update_health_issue_status,
                lookup_cloudtrail_events,
                get_metrics,
                query_logs,
                search_sops,
                search_similar_cases,
                save_rca_result,
                # Network investigation tools
                describe_vpcs,
                describe_subnets,
                describe_security_groups,
                describe_route_tables,
                describe_nat_gateways,
                describe_transit_gateways,
                describe_load_balancers,
                describe_region_topology,
                analyze_vpc_topology,
                # EKS networking tools
                describe_eks_clusters,
                describe_eks_nodegroups,
                check_eks_pod_ip_capacity,
                map_eks_to_vpc_topology,
                # Graph-based analysis tools
                query_reachability,
                query_impact_radius,
                find_network_path,
                detect_network_anomalies,
                # AWS CLI (read-only, for uncovered services or precision queries)
                run_aws_cli_readonly,
            ],
        )

        result = agent(f"Analyze HealthIssue #{issue_id}. Follow the investigation protocol.")
        return str(result)
    except Exception as e:
        logger.exception("RCA agent failed")
        return f"RCA agent error: {e}"
