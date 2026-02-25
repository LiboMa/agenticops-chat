"""Scan Agent - Resource discovery and inventory using Strands SDK.

Discovers AWS resources via STS AssumeRole and saves them to metadata.
Exposed as a tool for the Main Agent (agents-as-tools pattern).
"""

import logging

from strands import Agent, tool
from strands.models.bedrock import BedrockModel

from agenticops.config import settings
from agenticops.tools.aws_tools import (
    assume_role,
    describe_ec2,
    list_lambda_functions,
    describe_rds,
    list_s3_buckets,
    describe_ecs,
    describe_eks,
    list_dynamodb,
    list_sqs,
    list_sns,
)
from agenticops.tools.eks_tools import describe_eks_clusters
from agenticops.tools.network_tools import (
    describe_vpcs,
    describe_subnets,
    describe_security_groups,
    describe_route_tables,
    describe_nat_gateways,
    describe_transit_gateways,
    describe_load_balancers,
    describe_region_topology,
)
from agenticops.tools.metadata_tools import (
    get_active_account,
    save_resources,
)
from agenticops.tools.aws_cli_tool import run_aws_cli_readonly

logger = logging.getLogger(__name__)

SCAN_SYSTEM_PROMPT = """You are the Scan Agent for AgenticOps.
Your job is to discover and inventory AWS resources in the active account.

WORKFLOW:
1. Call get_active_account to get the active account configuration (account_id, role_arn, regions).
2. Call assume_role with the account's role_arn and external_id for each region to scan.
3. For each requested service, call the appropriate describe/list tool in each region.
4. Collect all discovered resources and call save_resources with the combined JSON array.
5. Return a summary: count by service, count by region, new vs updated.

RULES:
- Only READ operations. Never create, modify, or delete AWS resources.
- If a service/region fails, log the error and continue with others.
- When services='all', scan: EC2, Lambda, RDS, S3, ECS, EKS, DynamoDB, SQS, SNS, VPC, Subnet, SecurityGroup, NATGateway, TransitGateway, ELB, RouteTable.
- When regions='all', use the regions from the account configuration.
- Always call save_resources at the end to persist discovered resources.
TOOL SELECTION — accuracy first:
- Use specialized tools (describe_ec2, describe_rds, etc.) when they cover the service.
- Use run_aws_cli_readonly when: (a) the service has no specialized tool (e.g., ElastiCache,
  Redshift, Step Functions), OR (b) the CLI gives more precise/complete data for the specific query.
- Choose whichever tool produces the most accurate result for the task at hand.
- When using run_aws_cli_readonly, always use --query to filter output fields.
  Example: `aws elasticache describe-cache-clusters --query 'CacheClusters[].{Id:CacheClusterId,Status:CacheClusterStatus,Engine:Engine}'`
"""


@tool
def scan_agent(services: str = "all", regions: str = "all") -> str:
    """Scan AWS resources in the active account and update inventory.

    Args:
        services: Comma-separated service names (EC2,RDS,Lambda,S3,ECS,EKS,DynamoDB,SQS,SNS,VPC,Subnet,SecurityGroup,NATGateway,TransitGateway,ELB,RouteTable) or 'all'
        regions: Comma-separated AWS regions or 'all' (uses account configured regions)

    Returns:
        Summary of discovered resources with counts by service and region.
    """
    try:
        model = BedrockModel(
            model_id=settings.bedrock_model_id,
            region_name=settings.bedrock_region,
        )

        agent = Agent(
            system_prompt=SCAN_SYSTEM_PROMPT,
            model=model,
            callback_handler=None,
            tools=[
                assume_role,
                describe_ec2,
                list_lambda_functions,
                describe_rds,
                list_s3_buckets,
                describe_ecs,
                describe_eks,
                describe_eks_clusters,
                list_dynamodb,
                list_sqs,
                list_sns,
                # Network tools
                describe_vpcs,
                describe_subnets,
                describe_security_groups,
                describe_route_tables,
                describe_nat_gateways,
                describe_transit_gateways,
                describe_load_balancers,
                describe_region_topology,
                # Metadata
                save_resources,
                get_active_account,
                # AWS CLI (read-only, for uncovered services or precision queries)
                run_aws_cli_readonly,
            ],
        )

        result = agent(f"Scan services={services} regions={regions}")
        return str(result)
    except Exception as e:
        logger.exception("Scan agent failed")
        return f"Scan agent error: {e}"
