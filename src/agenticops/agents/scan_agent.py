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
from agenticops.tools.metadata_tools import (
    get_active_account,
    save_resources,
)

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
- When services='all', scan: EC2, Lambda, RDS, S3, ECS, EKS, DynamoDB, SQS, SNS.
- When regions='all', use the regions from the account configuration.
- Always call save_resources at the end to persist discovered resources.
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
                list_dynamodb,
                list_sqs,
                list_sns,
                save_resources,
                get_active_account,
            ],
        )

        result = agent(f"Scan services={services} regions={regions}")
        return str(result)
    except Exception as e:
        logger.exception("Scan agent failed")
        return f"Scan agent error: {e}"
