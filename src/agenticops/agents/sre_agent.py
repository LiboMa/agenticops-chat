"""SRE Agent - Read-only Fix Plan generation using Strands SDK.

Generates structured fix plans from RCA results with risk-level classification
(L0-L3) and an approval gate model. This agent NEVER executes fixes — it only
produces plans. Exposed as a tool for the Main Agent (agents-as-tools pattern).
"""

import logging

from strands import Agent, tool
from strands.models.bedrock import BedrockModel

from agenticops.config import settings
from agenticops.tools.aws_tools import (
    assume_role,
    describe_ec2,
    describe_rds,
    list_lambda_functions,
)
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
    get_rca_result,
    save_fix_plan,
)
from agenticops.tools.kb_tools import search_sops, search_similar_cases
from agenticops.graph.tools import (
    query_reachability,
    query_impact_radius,
    find_network_path,
    detect_network_anomalies,
)

logger = logging.getLogger(__name__)

SRE_SYSTEM_PROMPT = """You are the SRE Agent for AgenticOps.
Your job is to generate structured Fix Plans from RCA results.
You are READ-ONLY — you NEVER execute fixes or modify AWS resources.

FIX PLAN PROTOCOL:
1. SETUP: Call get_active_account and assume_role to get AWS credentials.
2. READ: Call get_health_issue and get_rca_result for the given issue.
3. SEARCH KB: Call search_sops for relevant procedures.
   Call search_similar_cases with a detailed description for past resolutions.
4. ASSESS RISK: Classify the fix as:
   - L0: Read-only verification (e.g., confirm metric recovered)
   - L1: Low-risk config change (e.g., adjust alarm threshold, update tag)
   - L2: Service-affecting change (e.g., resize instance, modify SG rules)
   - L3: High-risk change (e.g., restart service, failover, data migration)
5. INVESTIGATE: Gather current state of affected resource:
   - Call describe_region_topology for a region-level view of all VPCs, Transit Gateways,
     and peering connections — understand cross-VPC blast radius first.
   - Call analyze_vpc_topology for VPC-level blast radius analysis (subnet classification,
     blackhole routes, SG dependency map, peering/endpoint connectivity).
   - Call relevant describe tools (EC2, RDS, network tools, etc.)
   - For EKS issues: use describe_eks_clusters, describe_eks_nodegroups,
     check_eks_pod_ip_capacity, and map_eks_to_vpc_topology.
   - Call query_reachability to verify subnet internet connectivity with exact path trace.
   - Call find_network_path for point-to-point traffic path analysis.
   - Call detect_network_anomalies to find structural issues (routing loops, orphan nodes, blackholes).
   - Call query_impact_radius to assess blast radius of proposed changes.
   - Check if the issue has already self-resolved
6. GENERATE PLAN: Create a structured fix plan with:
   - Ordered steps with specific AWS CLI/API calls
   - Pre-checks (what to verify before starting)
   - Post-checks (what to verify after completion)
   - Rollback plan (how to undo if fix fails)
   - Estimated impact (downtime, performance impact)
7. SAVE: Call save_fix_plan with all details.

RULES:
- NEVER execute fixes. Only generate plans.
- Only READ operations on AWS.
- Always include rollback plans for L2+ fixes.
- Reference SOP steps when available.
- Be specific: use actual resource IDs, exact CLI commands, specific parameter values.
"""


@tool
def sre_agent(issue_id: int) -> str:
    """Generate a Fix Plan for a HealthIssue based on RCA results.

    READ-ONLY: does not execute any fixes, only produces a plan with
    risk classification, ordered steps, rollback plan, and pre/post checks.

    Args:
        issue_id: The HealthIssue ID to create a fix plan for.

    Returns:
        Fix plan summary with risk level, steps, and rollback plan.
    """
    try:
        model = BedrockModel(
            model_id=settings.bedrock_model_id,
            region_name=settings.bedrock_region,
        )

        agent = Agent(
            system_prompt=SRE_SYSTEM_PROMPT,
            model=model,
            callback_handler=None,
            tools=[
                assume_role,
                get_active_account,
                get_managed_resources,
                get_health_issue,
                get_rca_result,
                search_sops,
                search_similar_cases,
                save_fix_plan,
                # AWS describe tools (read-only)
                describe_ec2,
                describe_rds,
                list_lambda_functions,
                # Network tools (read-only)
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
            ],
        )

        result = agent(
            f"Generate a Fix Plan for HealthIssue #{issue_id}. "
            f"Follow the fix plan protocol. Be specific with resource IDs and CLI commands."
        )
        return str(result)
    except Exception as e:
        logger.exception("SRE agent failed")
        return f"SRE agent error: {e}"
