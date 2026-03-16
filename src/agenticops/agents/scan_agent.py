"""Scan Agent - Multi-cloud resource discovery and inventory using Strands SDK.

Discovers cloud resources across all enabled accounts (AWS, Azure, GCP, Alicloud)
using dynamic provider CLI tools. Exposed as a tool for the Main Agent (agents-as-tools pattern).
"""

import logging

from strands import Agent, tool
from strands.agent.conversation_manager import SlidingWindowConversationManager
from strands.models.bedrock import BedrockModel
from strands.models.model import CacheConfig

from agenticops.config import settings
from agenticops.providers.base import get_all_cli_tools
from agenticops.tools.metadata_tools import (
    get_active_account,
    get_enabled_accounts,
    save_resources,
)

logger = logging.getLogger(__name__)

SCAN_SYSTEM_PROMPT = """You are a multi-cloud resource scanner for AgenticOps.

## Your Job
Discover and inventory cloud resources across all enabled accounts.

## Workflow
1. Call get_enabled_accounts() to get the list of active cloud accounts
2. For each account, use its dedicated CLI tool to discover resources:
   - AWS accounts: use run_aws_cli_<account_name> with 'aws <service> describe-*' commands
   - Azure accounts: use run_az_cli_<account_name> with 'az <service> list' commands
   - GCP accounts: use run_gcloud_<account_name> with 'gcloud <service> list' commands
   - Alicloud accounts: use run_aliyun_cli_<account_name> with 'aliyun <service> <Action>' commands
3. For each discovered resource, call save_resources() with the account_id and provider

## Resource Categories
Scan these categories per cloud:
- compute: VMs, instances, functions/serverless
- database: Managed databases, caches
- storage: Object storage, file systems
- container: Kubernetes clusters, container services
- network: VPCs, subnets, load balancers, security groups
- serverless: Lambda, Functions, Cloud Functions

## CLI Tips
- Always request JSON output
- Use --query/--filter to limit results when possible
- For large accounts, scan region by region

## Output
Return a summary: how many resources found per account, per region, per type.
"""


@tool
def scan_agent(services: str = "all", regions: str = "all") -> str:
    """Scan cloud resources across all enabled accounts and update inventory.

    Args:
        services: Comma-separated resource categories (compute,database,storage,container,network,serverless) or 'all'.
        regions: Comma-separated regions or 'all' (uses each account's configured regions)

    Returns:
        Summary of discovered resources with counts per account, region, and type.
    """
    try:
        from agenticops.config import get_agent_model_config, get_agent_window_size

        model_id, max_tokens = get_agent_model_config("scan")
        cache_kwargs: dict = {}
        if settings.bedrock_cache_enabled:
            cache_kwargs = {"cache_config": CacheConfig(strategy="auto"), "cache_tools": "default"}
        bedrock_model = BedrockModel(
            model_id=model_id,
            region_name=settings.bedrock_region,
            max_tokens=max_tokens,
            **cache_kwargs,
        )

        # Build dynamic tool list from enabled accounts
        tools: list = [get_enabled_accounts, get_active_account, save_resources]
        tools.extend(get_all_cli_tools())

        agent = Agent(
            system_prompt=SCAN_SYSTEM_PROMPT,
            model=bedrock_model,
            callback_handler=None,
            conversation_manager=SlidingWindowConversationManager(
                window_size=get_agent_window_size("scan"), per_turn=True
            ),
            tools=tools,
        )

        from agenticops.agents.preamble import invoke_with_retry
        prompt = f"Scan resources. Services: {services}. Regions: {regions}."
        result = invoke_with_retry(agent, prompt)
        return str(result)
    except Exception as e:
        logger.exception("Scan agent failed")
        return f"Scan agent error: {e}"
