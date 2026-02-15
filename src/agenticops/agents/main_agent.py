"""Main Agent (Orchestrator) - Coordinates specialized agents via Strands SDK.

Uses the agents-as-tools pattern: sub-agents (scan, detect) are exposed as
callable tools to the orchestrator agent.
"""

import logging
from typing import Optional

from strands import Agent
from strands.models.bedrock import BedrockModel

from agenticops.config import settings
from agenticops.agents.scan_agent import scan_agent
from agenticops.agents.detect_agent import detect_agent
from agenticops.agents.rca_agent import rca_agent
from agenticops.agents.reporter_agent import reporter_agent
from agenticops.tools.metadata_tools import (
    get_active_account,
    get_managed_resources,
    get_health_issue,
    get_rca_result,
    list_health_issues,
    update_health_issue_status,
)

logger = logging.getLogger(__name__)

MAIN_SYSTEM_PROMPT = """You are AgenticOps, an AI-powered AWS cloud operations assistant.

You coordinate specialized agents to help users manage their AWS infrastructure:
- scan_agent: Discovers and inventories AWS resources. Call with services and regions.
- detect_agent: Checks health via CloudWatch Alarms and metrics. Call with scope and deep flag.
- rca_agent: Performs Root Cause Analysis on a HealthIssue. Call with issue_id.
- reporter_agent: Generates operations reports (daily, incident, inventory). Call with report_type and scope.

You also have direct tools for metadata queries:
- get_active_account: Check which AWS account is currently active.
- get_managed_resources: List resources in the inventory, filtered by type/region.
- get_health_issue: Get details of a specific health issue by ID.
- list_health_issues: List health issues with severity/status/resource filters.
- update_health_issue_status: Update issue status (e.g., open -> investigating -> resolved).
- get_rca_result: Get the latest RCA analysis result for a health issue by ID.

RULES:
1. Always check metadata (active account, resource inventory) before dispatching tasks.
   If no account is configured, tell the user to run 'aiops create account' first.
2. For destructive or write operations, ALWAYS present the plan and wait for user approval.
3. Summarize agent results clearly. Show severity, affected resources, and recommended actions.
4. When multiple issues exist, prioritize by severity (critical > high > medium > low).
5. Track and report token usage when asked.
6. When the user asks to "scan", dispatch to scan_agent.
7. When the user asks about "health", "issues", "problems", or "detect", dispatch to detect_agent.
8. When the user asks to "analyze", "investigate", "RCA", or "root cause" an issue, dispatch to rca_agent with the issue_id.
9. When the user asks for a "report", "summary", "daily report", or "incident report", dispatch to reporter_agent with the appropriate report_type (daily, incident, or inventory).
10. For questions about resources, accounts, or inventory, use the direct metadata tools.
11. Be concise but thorough. Show actual data from tools, don't summarize away details.
"""


def create_main_agent() -> Agent:
    """Create and return the Main Agent (Orchestrator).

    Returns:
        Configured Strands Agent with sub-agents and metadata tools.
    """
    model = BedrockModel(
        model_id=settings.bedrock_model_id,
        region_name=settings.bedrock_region,
    )

    agent = Agent(
        system_prompt=MAIN_SYSTEM_PROMPT,
        model=model,
        tools=[
            # Sub-agents as tools
            scan_agent,
            detect_agent,
            rca_agent,
            reporter_agent,
            # Direct metadata tools
            get_active_account,
            get_managed_resources,
            get_health_issue,
            get_rca_result,
            list_health_issues,
            update_health_issue_status,
        ],
    )

    return agent
