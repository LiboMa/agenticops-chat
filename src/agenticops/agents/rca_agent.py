"""RCA Agent - Root Cause Analysis using Strands SDK.

Receives a HealthIssue ID, investigates using AWS tools + Knowledge Base,
and persists structured RCA results. Exposed as a tool for the Main Agent
(agents-as-tools pattern).
"""

import logging

from strands import Agent, tool
from strands.models.bedrock import BedrockModel

from agenticops.config import settings
from agenticops.tools.aws_tools import assume_role
from agenticops.tools.cloudwatch_tools import get_metrics, query_logs
from agenticops.tools.cloudtrail_tools import lookup_cloudtrail_events
from agenticops.tools.kb_tools import search_sops, search_similar_cases
from agenticops.tools.metadata_tools import (
    get_active_account,
    get_managed_resources,
    get_health_issue,
    update_health_issue_status,
    save_rca_result,
)

logger = logging.getLogger(__name__)

RCA_SYSTEM_PROMPT = """You are the RCA Agent for AgenticOps.
Your job is to perform Root Cause Analysis on a specific HealthIssue.

INVESTIGATION PROTOCOL — follow this order strictly:

1. SETUP: Call get_active_account and assume_role to get AWS credentials.
2. READ ISSUE: Call get_health_issue with the given issue_id to understand the problem.
3. SET STATUS: Call update_health_issue_status to set status to 'investigating'.
4. SEARCH KNOWLEDGE BASE:
   a. Call search_sops with the resource type and issue keywords to find relevant SOPs.
   b. Call search_similar_cases with resource type and issue keywords for historical context.
5. INVESTIGATE CHANGES (80% of issues are caused by recent changes):
   a. Call lookup_cloudtrail_events for the affected resource (last 24 hours).
   b. Look for deployment, config change, security group, IAM, or scaling events.
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
        )

        agent = Agent(
            system_prompt=RCA_SYSTEM_PROMPT,
            model=model,
            callback_handler=None,
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
            ],
        )

        result = agent(f"Analyze HealthIssue #{issue_id}. Follow the investigation protocol.")
        return str(result)
    except Exception as e:
        logger.exception("RCA agent failed")
        return f"RCA agent error: {e}"
