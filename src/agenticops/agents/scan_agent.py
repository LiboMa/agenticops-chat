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

## Preferred Approach
For standard full scans, call scan_resources() — it runs predefined CLI commands across all accounts
in parallel. For parallel health checking across multiple accounts, call check_health() — it spawns
one detect agent per account for concurrent LLM-powered analysis. Only use individual account CLI
tools (run_aws_cli_*, etc.) for ad-hoc investigation or when you need to run specific commands not
covered by the standard scan.

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
def scan_resources(account_ids: str = "", focus: str = "all", regions: str = "") -> str:
    """Programmatic parallel scan of cloud resources across all enabled accounts.

    Uses predefined CLI commands per provider — much faster than manual scanning.
    Prefer this for standard full scans. Use per-account CLI tools only for ad-hoc investigation.

    Args:
        account_ids: Comma-separated account IDs to scan, or empty for all enabled.
        focus: Scan focus: computing,networking,databases,storage,security,all.
        regions: Comma-separated regions to scan, or empty for each account's configured regions.

    Returns:
        Summary of scan results per account.
    """
    import asyncio
    from agenticops.scanner import scan_accounts_parallel

    ids = [int(x.strip()) for x in account_ids.split(",") if x.strip()] or None
    rgns = [r.strip() for r in regions.split(",") if r.strip()] or None

    try:
        result = asyncio.run(scan_accounts_parallel(account_ids=ids, focus=focus, regions=rgns))
    except RuntimeError:
        loop = asyncio.get_event_loop()
        result = loop.run_until_complete(scan_accounts_parallel(account_ids=ids, focus=focus, regions=rgns))

    lines = [f"Scan complete in {result.duration_s}s — {result.total_found} resources found."]
    for a in result.accounts:
        lines.append(f"  {a.account_name} ({a.provider}): {a.resources_found} found, {a.resources_updated} updated, regions={a.regions_scanned}")
        for err in a.errors[:3]:
            lines.append(f"    ⚠ {err}")
    return "\n".join(lines)


@tool
def check_health(account_ids: str = "", scope: str = "all", deep: str = "false") -> str:
    """Run parallel health checks across all enabled accounts.

    Spawns one detect agent per account for concurrent LLM-powered health checking.
    Each agent uses the account's cloud CLI tool and reasons about what to check.
    Much faster than sequential single-agent detection.

    Args:
        account_ids: Comma-separated account IDs, or empty for all enabled.
        scope: Resource scope: 'all', 'EC2', 'RDS', 'security', etc.
        deep: 'true' for deep investigation even on healthy resources.

    Returns:
        Summary of health check results per account.
    """
    import asyncio
    from agenticops.checker import check_accounts_parallel

    ids = [int(x.strip()) for x in account_ids.split(",") if x.strip()] or None
    is_deep = deep.lower() == "true"

    try:
        result = asyncio.run(check_accounts_parallel(account_ids=ids, scope=scope, deep=is_deep))
    except RuntimeError:
        loop = asyncio.get_event_loop()
        result = loop.run_until_complete(check_accounts_parallel(account_ids=ids, scope=scope, deep=is_deep))

    lines = [f"Health check complete in {result.duration_s}s — {result.total_issues} issues found."]
    for a in result.accounts:
        lines.append(f"  {a.account_name} ({a.provider}): {a.issues_created} issues, {a.duration_s}s")
        for err in a.errors[:3]:
            lines.append(f"    ERROR: {err}")
    return "\n".join(lines)


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
        tools: list = [get_enabled_accounts, get_active_account, save_resources, scan_resources, check_health]
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
