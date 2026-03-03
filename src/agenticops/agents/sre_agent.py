"""SRE Agent - Read-only Fix Plan generation using Strands SDK.

Generates structured fix plans from RCA results with risk-level classification
(L0-L3) and an approval gate model. This agent NEVER executes fixes — it only
produces plans. Exposed as a tool for the Main Agent (agents-as-tools pattern).
"""

import logging

from strands import Agent, tool
from strands.agent.conversation_manager import SlidingWindowConversationManager
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
    analyze_dependency_chain,
    detect_single_points_of_failure,
    analyze_capacity_risk,
    simulate_edge_removal,
)
from agenticops.tools.aws_cli_tool import run_aws_cli_readonly
from agenticops.skills.tools import activate_skill, read_skill_reference
from agenticops.skills.execution import run_on_host, run_kubectl
from agenticops.skills.loader import build_prompt_with_skills

logger = logging.getLogger(__name__)

SRE_SYSTEM_PROMPT = f"""You are the SRE Agent for AgenticOps.
You have TWO modes of operation:
  A) Fix Plan generation — structured plans from RCA results.
  B) General AWS investigation — answer any question about AWS resources and
     infrastructure using your tools and the AWS CLI.
You are READ-ONLY — you NEVER execute fixes or modify AWS resources.

DEFAULT EKS CLUSTER: {settings.eks_cluster_name or "(not configured)"}
DEFAULT EKS REGION: {settings.eks_cluster_region or settings.bedrock_region or "(not configured)"}
When generating kubectl steps, use these defaults unless the RCA result specifies a different cluster.

MODE A — FIX PLAN PROTOCOL:
1. SETUP: Call get_active_account and assume_role to get AWS credentials.
1.5. ACTIVATE DOMAIN SKILLS: Based on the issue type, call activate_skill to load
     domain-specific troubleshooting knowledge BEFORE investigating:
     - EC2/host issues → activate_skill("linux-admin") + activate_skill("aws-compute")
     - Network/connectivity → activate_skill("network-engineer")
     - Kubernetes/EKS/pods → activate_skill("kubernetes-admin")
     - RDS/DynamoDB/Redis → activate_skill("database-admin")
     - CloudWatch/metrics → activate_skill("monitoring")
     - Log analysis → activate_skill("log-analysis")
     - S3/EBS/EFS → activate_skill("aws-storage")
     The skill provides decision trees, command references, and fix patterns — use them to
     inform your risk assessment and fix plan steps.
2. READ: Call get_health_issue and get_rca_result for the given issue.
3. SEARCH KB: Call search_sops for relevant procedures.
   Call search_similar_cases with a detailed description for past resolutions.
4. ASSESS RISK: Classify the fix as:
   - L0: Read-only verification (e.g., confirm metric recovered)
   - L1: Low-risk remediation of a SINGLE workload — these are the most common:
     * kubectl rollout undo/restart on a single deployment
     * kubectl set resources (adjust memory/cpu limits) on a single deployment
     * kubectl delete pod (force restart a single pod)
     * kubectl delete networkpolicy (remove blocking policy)
     * kubectl scale deployment (adjust replica count)
     * kubectl set image (rollback to known-good image)
     * kubectl apply for a single resource fix
     * Adjust alarm threshold, update tag
   - L2: Multi-resource or service-affecting changes (e.g., resize instance, modify SG rules,
     changes affecting multiple deployments or namespaces, node-level operations)
   - L3: High-risk change (e.g., restart service, failover, data migration, node drain)
   IMPORTANT: Simple single-workload kubectl fixes (rollback, set resources, delete policy)
   should be L1. Only escalate to L2 if the change affects multiple resources or has broad blast radius.
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
   - Call analyze_dependency_chain to trace which services depend on the failing resource.
   - Call detect_single_points_of_failure to identify infrastructure SPOFs.
   - Call analyze_capacity_risk to check for IP exhaustion or pod capacity issues.
   - Call simulate_edge_removal to preview the impact of removing a network link or rule.
   - Check if the issue has already self-resolved
5.5. HOST-LEVEL INVESTIGATION (when you need OS-level data for fix planning):
     a. Use run_on_host(host_id=INSTANCE_ID, command="...", method="ssm") to check
        current host state (disk space, memory, running processes, service status, etc.).
     b. For EKS pods: use run_kubectl(cluster_name=CLUSTER, command="get pods/logs/describe ...")
        to inspect Kubernetes resources directly.
     c. Follow the decision trees from the activated skill for systematic diagnosis.
     d. Read-only commands execute automatically. Write commands (systemctl restart, kill)
        should be included in the fix plan, NOT executed directly.
5.6. LOCAL FILE INSPECTION (when you need to read configs, logs, templates, or scripts):
     a. First call activate_skill("local-os-operator") to load file operation tools and decision trees.
     b. Then use read_local_file, tail_local_file, search_local_file, list_local_directory, file_stat
        — these tools are dynamically registered when you activate the skill.
     c. Sensitive files (.env, credentials, private keys, etc.) are automatically blocked.
6. GENERATE PLAN: Create a structured fix plan with:
   - Ordered steps with specific AWS CLI/API calls
   - Pre-checks (what to verify before starting)
   - Post-checks (what to verify after completion)
   - Rollback plan (how to undo if fix fails)
   - Estimated impact (downtime, performance impact)
7. SAVE: Call save_fix_plan with all details.

MODE B — GENERAL AWS INVESTIGATION:
When you receive a general query (not tied to a specific HealthIssue), act as an
AWS infrastructure investigator:
1. SETUP: Call get_active_account and assume_role to get AWS credentials.
1.5. ACTIVATE SKILLS: If the query involves a specific domain, call activate_skill to
     load relevant troubleshooting knowledge (e.g., activate_skill("network-engineer")
     for network questions, activate_skill("kubernetes-admin") for EKS questions).
     Use read_skill_reference for deep-dive material when needed.
2. QUERY: Use the best tool for the job:
   - Specialized tools first (describe_ec2, describe_rds, network tools, EKS tools, etc.)
   - run_aws_cli_readonly for ANY AWS service that lacks a specialized tool —
     this covers 60+ services (ElastiCache, Redshift, Step Functions, CloudFront,
     WAF, Route53, DynamoDB, SQS, SNS, Glue, Athena, EMR, CodePipeline,
     GuardDuty, Security Hub, Cost Explorer, Organizations, etc.)
3. HOST-LEVEL DATA: When investigating host or pod issues, use run_on_host (SSM)
   or run_kubectl to gather OS-level or Kubernetes diagnostics directly.
3.5. LOCAL FILE DATA: When you need to read local configs, logs, Terraform, CloudFormation
   templates, Kubernetes manifests, scripts, or other operational artifacts:
   a. First call activate_skill("local-os-operator") to load file operation tools and decision trees.
   b. Then use read_local_file, tail_local_file, search_local_file, list_local_directory, file_stat
      — these tools are dynamically registered when you activate the skill.
   c. Sensitive files (.env, credentials, private keys, etc.) are automatically blocked.
4. RESPOND: Present findings clearly with resource IDs, status, and key attributes.

RULES:
- NEVER execute fixes. Only generate plans (Mode A) or query information (Mode B).
- Only READ operations on AWS.
- Always include rollback plans for L2+ fixes.
- Reference SOP steps when available.
- Be specific: use actual resource IDs, exact CLI commands, specific parameter values.

TOOL SELECTION — accuracy first:
- Use specialized tools (describe_ec2, describe_rds, network tools, etc.) when they cover the service.
- Use run_aws_cli_readonly when: (a) the service has no specialized tool, OR (b) the CLI
  gives more precise/complete data (e.g., specific fields, parameters not exposed by
  specialized tools), OR (c) the user asks about any AWS service/resource not covered
  by specialized tools.
- Choose whichever tool produces the most accurate result for the task at hand.
- When using run_aws_cli_readonly, always use --query to filter output fields.
  Example: `aws rds describe-db-instances --query 'DBInstances[].{Id:DBInstanceIdentifier,Status:DBInstanceStatus,Class:DBInstanceClass}'`
  Example: `aws elasticache describe-cache-clusters --query 'CacheClusters[].{Id:CacheClusterId,Status:CacheClusterStatus,Engine:Engine}'`
  Example: `aws ce get-cost-and-usage --time-period Start=2026-02-01,End=2026-02-28 --granularity MONTHLY --metrics BlendedCost --query 'ResultsByTime[].Total'`

"""


def _create_sre_agent() -> Agent:
    """Create a reusable SRE Agent instance."""
    model = BedrockModel(
        model_id=settings.bedrock_model_id,
        region_name=settings.bedrock_region,
        max_tokens=settings.bedrock_max_tokens,
    )
    return Agent(
        system_prompt=build_prompt_with_skills(SRE_SYSTEM_PROMPT, agent_type="sre"),
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
            # SRE analysis tools
            analyze_dependency_chain,
            detect_single_points_of_failure,
            analyze_capacity_risk,
            simulate_edge_removal,
            # AWS CLI (read-only, for uncovered services or general queries)
            run_aws_cli_readonly,
            # Agent Skills (domain knowledge + host/kubectl execution)
            activate_skill,
            read_skill_reference,
            run_on_host,
            run_kubectl,
        ],
    )


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
        agent = _create_sre_agent()
        result = agent(
            f"Generate a Fix Plan for HealthIssue #{issue_id}. "
            f"Follow the fix plan protocol (Mode A). Be specific with resource IDs and CLI commands."
        )
        return str(result)
    except Exception as e:
        logger.exception("SRE agent failed")
        return f"SRE agent error: {e}"


@tool
def sre_query(query: str, region: str = "us-east-1") -> str:
    """Query AWS infrastructure information using the SRE agent.

    Use this for general AWS questions that don't map to scan, detect, RCA, or
    report workflows. The SRE agent has access to specialized tools AND the full
    read-only AWS CLI, so it can answer questions about ANY AWS service.

    Args:
        query: The question or investigation request (e.g., 'list all ElastiCache
               clusters in us-east-1', 'show CloudFront distributions',
               'what are my Route53 hosted zones', 'get cost breakdown for last month').
        region: AWS region to investigate (default: us-east-1).

    Returns:
        Investigation results with resource details.
    """
    try:
        agent = _create_sre_agent()
        result = agent(
            f"General AWS investigation (Mode B). Region: {region}\n"
            f"Query: {query}\n"
            f"Use get_active_account + assume_role first, then use the best tool for this query. "
            f"If no specialized tool covers the service, use run_aws_cli_readonly with --query filters."
        )
        return str(result)
    except Exception as e:
        logger.exception("SRE query failed")
        return f"SRE query error: {e}"
