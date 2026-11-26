"""Reporter Agent - Report generation using Strands SDK.

Gathers health issues, RCA results, and resource inventory to produce
structured reports. Exposed as a tool for the Main Agent
(agents-as-tools pattern).
"""

import logging
import re

from strands import Agent, tool
from strands.hooks import AfterToolCallEvent, HookProvider, HookRegistry
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
from agenticops.skills.tools import activate_skill, read_skill_reference
from agenticops.tools.memory_tools import search_agent_memory
from agenticops.llm.errors import safe_error_text

logger = logging.getLogger(__name__)


class CoverageRecorder(HookProvider):
    """Counts, on the run's coverage record, the tool results that failed or that the context offloader moved out of
    the context (services/report_coverage; the cut ones are counted by the tools themselves). It runs AFTER the
    offloader (order 70), which rewrites the result into a preview that begins «[Offloaded:»."""

    ORDER = 90

    def __init__(self, coverage):
        self.coverage = coverage

    def register_hooks(self, registry: HookRegistry, **kwargs) -> None:
        registry.add_callback(AfterToolCallEvent, self._ended, order=self.ORDER)

    def _ended(self, event) -> None:
        try:
            result = getattr(event, "result", None) or {}
            text = "\n".join(block["text"] for block in (result.get("content") or [])
                             if isinstance(block, dict) and isinstance(block.get("text"), str))
            with self.coverage._lock:
                if text.lstrip().startswith("[Offloaded:"):
                    self.coverage.offloaded += 1
                elif (getattr(event, "exception", None) is not None or result.get("status") == "error"
                      or _SAYS_FAILED.match(text) is not None):
                    self.coverage.failed += 1
        except Exception:
            logger.debug("coverage recorder: a result could not be read", exc_info=True)


# A tool that answers with an error: «Error: …», «Access error (…)», or the metadata tools' {"error": …}
_SAYS_FAILED = re.compile(r'^\s*(?:(?:[A-Za-z]+ )?[Ee]rror(?::| \()|\{\s*"error"\s*:)')

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
   - **security-review**: Latest SecuritySnapshot scores, CIS results, exposure paths, open recommendations — use the generate_report tool with report_type="security-review".
   - **conversation**: Use the above tools as needed to answer user queries about health issues, RCA, or inventory.
   
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

LOCAL FILE OUTPUT:
- When the user asks to save/export results to a local file, call
  activate_skill("local-os-operator") first to load the write_local_file tool,
  then use write_local_file to save the content.

WEB RESEARCH:
- If a report needs external context (upstream incident reports, CVE details,
  vendor changelogs), call activate_skill("web-research") to load web_search +
  web_fetch, then cite fetched sources by URL.

REPORT DISTRIBUTION:
- After saving a report, if the user requests distribution (or if you are instructed
  to distribute), call activate_skill("notification-operator") to load notification tools.
- Use list_notification_channels to discover available channels and their format preferences.
- Use distribute_report with the report ID to batch-distribute to multiple channels.
  Each channel receives the report in its preferred format (HTML, PDF, markdown).
- Use send_to_channel for single-channel text/issue sends.

RULES:
- Only READ from AWS metadata. The only writes are save_report, write_kb_case,
  and write_local_file (when user explicitly requests file export).
- Always check list_reports first to avoid generating duplicate reports.
- Return the report summary and file path at the end.
"""


@tool
def reporter_agent(report_type: str = "daily", scope: str = "all") -> str:
    """Generate an operations report from health issues, RCA results, and inventory.

    USE FOR: "report", "summary", "daily report", "incident report",
    "inventory report". Gathers metadata, formats structured markdown,
    saves to DB + reports directory.
    NOT FOR: live health checks (detect_agent) or ad-hoc queries (sre_query).

    Args:
        report_type: Type of report: daily, incident, inventory, or security-review
        scope: Resource type filter (e.g., 'EC2', 'RDS') or 'all' for all resources

    Returns:
        Report summary with ID and file path.
    """
    try:
        from agenticops.config import get_agent_model_config, get_agent_conversation_manager, get_agent_context_plugins

        model_id, max_tokens = get_agent_model_config("reporter")
        from agenticops.llm.factory import build_model    # Bedrock or another provider (MVP-2.9.0 N35)
        # carries the stream read timeout on Bedrock (model connection settings, ≥ the 300 s it had)
        model = build_model(model_id, max_tokens=max_tokens, bedrock_cls=BedrockModel)

        # What this run reads is recorded by the code (services/report_coverage): the record rides on the run's
        # context, the tools and the hook below write into it, save_report stores it on the report.
        from agenticops.run_context import run_context
        from agenticops.services import report_coverage
        coverage = report_coverage.begin()

        from agenticops.agents.preamble import build_system_prompt
        agent = Agent(
            system_prompt=build_system_prompt(REPORTER_SYSTEM_PROMPT, include_account=False, agent_name="reporter"),
            model=model,
            callback_handler=None,
            conversation_manager=get_agent_conversation_manager("reporter"),
            plugins=get_agent_context_plugins("reporter"),
            hooks=[CoverageRecorder(coverage)],
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
                activate_skill,
                read_skill_reference,
                # Agent Memory (cross-agent search)
                search_agent_memory,
            ],
        )

        from agenticops.agents.preamble import invoke_with_retry, infer_parent_agent
        from agenticops.services.agent_log_service import track_agent
        with run_context(coverage=coverage), \
                track_agent("reporter", "generate_report", f"type={report_type} scope={scope}", parent_agent=infer_parent_agent()) as tracker:
            result = invoke_with_retry(agent,
                f"Generate a {report_type} report. Scope: {scope}. "
                f"Follow the report generation protocol.",
                max_retries=3, backoff=5.0,
            )
            tracker.set_result(result)
        return str(result)
    except Exception as e:
        logger.exception("Reporter agent failed")
        return f"Reporter agent error: {safe_error_text(e)}"
