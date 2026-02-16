"""Reporter Agent - Report generation using Strands SDK.

Gathers health issues, RCA results, and resource inventory to produce
structured reports. Exposed as a tool for the Main Agent
(agents-as-tools pattern).
"""

import logging

from strands import Agent, tool
from strands.models.bedrock import BedrockModel

from agenticops.config import settings
from agenticops.tools.metadata_tools import (
    get_active_account,
    get_managed_resources,
    get_health_issue,
    get_rca_result,
    list_health_issues,
)
from agenticops.tools.report_tools import save_report, list_reports
from agenticops.tools.kb_tools import search_similar_cases, write_kb_case, distill_case_study

logger = logging.getLogger(__name__)

REPORTER_SYSTEM_PROMPT = """You are the Reporter Agent for AgenticOps.
Your job is to generate structured operations reports from health issues,
RCA results, and resource inventory data.

REPORT GENERATION PROTOCOL:

1. SETUP: Call get_active_account to identify the AWS account context.
2. GATHER DATA based on report_type:
   - **daily**: Call list_health_issues (all statuses) to get recent issues.
     For each issue with status 'root_cause_identified' or later, call get_rca_result.
     Call get_managed_resources for resource inventory summary.
   - **incident**: Call list_health_issues filtered by severity (critical, high).
     For each issue, call get_health_issue for full details, then get_rca_result.
     Call search_similar_cases if patterns repeat.
   - **inventory**: Call get_managed_resources (scope filter if provided).
     Call list_health_issues to cross-reference issues against resources.
3. FORMAT: Generate a well-structured markdown report with these sections:
   - **Header**: Report type, date, account info.
   - **Executive Summary**: Key metrics (total issues, by severity, resolved vs open).
   - **Issues Detail**: For each issue, include severity, resource, title, RCA summary
     (if available), status, and recommendations.
   - **Resource Inventory** (for daily/inventory): Total resources by type and region.
   - **Recommendations**: Aggregated action items prioritized by severity.
4. SAVE: Call save_report with the full markdown content.
5. KNOWLEDGE BASE (optional): For resolved issues with high-confidence RCA,
   call write_kb_case to persist the case study for future reference.
6. DISTILLATION: After generating the report, check for resolved issues with
   RCA confidence >= 0.7. For each qualifying issue, call distill_case_study
   with the health_issue_id. This distills the incident into a structured
   Case Study with abstracted patterns, embeds it for semantic search, and
   indexes it in the vector store for future RCA lookups.

SEVERITY FORMATTING:
- 🔴 critical -> immediate action required
- 🟠 high -> action required within 24h
- 🟡 medium -> schedule remediation
- 🟢 low -> informational, track

REPORT QUALITY:
- Include actual data, metrics, and timestamps — never fabricate information.
- Use markdown tables for structured data (resource lists, issue summaries).
- Keep executive summary concise (3-5 bullet points).
- Recommendations should be specific and actionable, not generic advice.
- If no issues are found, report that explicitly as a positive finding.

RULES:
- Only READ from AWS metadata. The only writes are save_report and write_kb_case.
- Always check list_reports first to avoid generating duplicate reports.
- Return the report summary and file path at the end.
"""


@tool
def reporter_agent(report_type: str = "daily", scope: str = "all") -> str:
    """Generate an operations report from health issues, RCA results, and inventory.

    Gathers data from metadata, formats a structured markdown report,
    and saves it to the database and reports directory.

    Args:
        report_type: Type of report: daily, incident, or inventory
        scope: Resource type filter (e.g., 'EC2', 'RDS') or 'all' for all resources

    Returns:
        Report summary with ID and file path.
    """
    try:
        model = BedrockModel(
            model_id=settings.bedrock_model_id,
            region_name=settings.bedrock_region,
        )

        agent = Agent(
            system_prompt=REPORTER_SYSTEM_PROMPT,
            model=model,
            callback_handler=None,
            tools=[
                get_active_account,
                get_managed_resources,
                get_health_issue,
                get_rca_result,
                list_health_issues,
                save_report,
                list_reports,
                search_similar_cases,
                write_kb_case,
                distill_case_study,
            ],
        )

        result = agent(
            f"Generate a {report_type} report. Scope: {scope}. "
            f"Follow the report generation protocol."
        )
        return str(result)
    except Exception as e:
        logger.exception("Reporter agent failed")
        return f"Reporter agent error: {e}"
