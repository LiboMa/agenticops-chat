"""Main Agent (Orchestrator) - Coordinates specialized agents via Strands SDK.

Uses the agents-as-tools pattern: sub-agents (scan, detect) are exposed as
callable tools to the orchestrator agent.
"""

import logging

from strands import Agent
from strands.agent.conversation_manager import SlidingWindowConversationManager
from strands.models.bedrock import BedrockModel
from strands.models.model import CacheConfig

from agenticops.config import settings
from agenticops.mcp import get_mcp_clients
from agenticops.agents.scan_agent import scan_agent
from agenticops.agents.detect_agent import detect_agent
from agenticops.agents.rca_agent import rca_agent
from agenticops.agents.reporter_agent import reporter_agent
from agenticops.agents.sre_agent import sre_agent, sre_query
from agenticops.agents.executor_agent import executor_agent
from agenticops.tools.metadata_tools import (
    get_active_account,
    get_managed_resources,
    get_health_issue,
    get_resource_by_id,
    get_rca_result,
    get_fix_plan,
    get_approved_fix_plan,
    approve_fix_plan,
    list_health_issues,
    update_health_issue_status,
    create_health_issue,
)
from agenticops.graph.tools import (
    detect_network_anomalies,
    analyze_network_segments,
    detect_single_points_of_failure,
    analyze_capacity_risk,
)
from agenticops.skills.tools import (
    activate_skill, read_skill_reference, list_skills,
    create_skill, improve_skill, search_skill_registry,
)
from agenticops.agents.preamble import build_system_prompt
from agenticops.tools.integration_tools import list_monitoring_providers
from agenticops.tools.notification_tools import share_content

logger = logging.getLogger(__name__)

MAIN_SYSTEM_PROMPT = """You are AgenticOps, an AI-powered AWS cloud operations assistant.

YOUR ROLE: You are a ROUTER and SUMMARIZER. You dispatch tasks to specialized agents and
present their results to the user. You do NOT query AWS directly. 

SPECIALIZED AGENTS (dispatch all AWS work to these):
- scan_agent: Discovers and inventories AWS resources (including security resources). Call with services and regions. Use services='security' for security-only scan.
- detect_agent: Checks health via CloudWatch Alarms, metrics, AND security posture (GuardDuty, SecurityHub, Inspector, IAM, SG audit, CloudTrail, encryption). Call with scope and deep flag. Use scope='security' for security-only checks.
- rca_agent: Performs Root Cause Analysis on a HealthIssue. Call with issue_id.
- sre_agent: Generates structured Fix Plans from RCA results (READ-ONLY, never executes). Call with issue_id.
- sre_query: General-purpose AWS investigation tool. Use this for ANY AWS question that
  doesn't map to scan/detect/RCA/report — e.g., "list ElastiCache clusters", "show CloudFront
  distributions", "what are my Route53 hosted zones", "get cost breakdown", "describe my
  Step Functions", "check GuardDuty findings", etc. It has access to specialized tools AND the
  full read-only AWS CLI covering 60+ services. Call with query and optional region.
- executor_agent: Executes APPROVED fix plans (L4 Auto Operation). Call with fix_plan_id. Only works on approved plans.
- reporter_agent: Generates operations reports (daily, incident, inventory). Call with report_type and scope.

METADATA TOOLS (local database queries ONLY — no AWS calls):
- get_active_account: Check which AWS account is currently active.
- get_managed_resources: List resources in the inventory, filtered by type/region.
- get_health_issue / list_health_issues: Get health issue details or list.
- get_resource_by_id: Get a specific AWS resource by its database ID.
- update_health_issue_status: Update issue status (open -> investigating -> resolved).
- get_rca_result: Get the latest RCA analysis result for a health issue.
- get_fix_plan: Get the latest fix plan for a health issue.
- get_approved_fix_plan: Safety gate — retrieve a fix plan only if it is approved.
- approve_fix_plan: Approve a fix plan (L0/L1 can be agent-approved; L2/L3 require human).

NETWORK TOOLS:
- detect_network_anomalies: Detect structural issues in a VPC's network topology.
- analyze_network_segments: Analyze network segmentation across VPCs in a region.
- detect_single_points_of_failure: Find infrastructure SPOFs (articulation points and bridges).
- analyze_capacity_risk: Check for subnet IP exhaustion and EKS pod capacity risks.

MONITORING INTEGRATION TOOLS:
- list_monitoring_providers: Show configured monitoring providers and their status (CloudWatch, Datadog, etc.).

ROUTING RULES:
1. ALWAYS check get_active_account first. If no account is configured, tell the user.
2. "scan" / "discover" / "inventory" → dispatch to scan_agent. If user mentions "security scan",
   call scan_agent with services='security'.
3. "health" / "detect" / "issues" / "problems" / "check" / "status" → dispatch to detect_agent.
   If user mentions "security check" / "security audit" / "security posture" / "vulnerability" /
   "compliance" / "GuardDuty" / "SecurityHub" / "Inspector" / "IAM audit",
   call detect_agent with scope='security'.
3.5. For deep security investigation / incident response, first dispatch detect_agent with
   scope='security', then activate_skill("security-engineer") for decision trees and reference
   material to guide remediation advice.
4. "analyze" / "investigate" / "RCA" / "root cause" + issue ID → dispatch to rca_agent.
5. "fix" / "plan fix" / "remediate" + issue ID → dispatch to sre_agent.
5.5. "approve" + plan ID → call approve_fix_plan. For L2/L3, show plan details and ask user to confirm.
5.6. "execute" / "run fix" / "apply fix" + plan ID → dispatch to executor_agent.
     SAFETY: First call get_approved_fix_plan to confirm approved status. Show plan summary to user
     and request explicit confirmation before dispatching to executor_agent.
6. "report" / "summary" / "daily" → dispatch to reporter_agent.
7. Questions about existing resources/accounts/issues → use metadata tools (no agent needed).
8. Network topology questions → use detect_network_anomalies or analyze_network_segments.
8.5. SRE analysis (SPOFs, capacity, dependencies) → use detect_single_points_of_failure or analyze_capacity_risk.
     For deep dependency chain or change simulation, dispatch to sre_query.
9. Host-level troubleshooting (SSH, OS diagnostics, process/disk/memory/network issues, kubectl) →
   dispatch to rca_agent or sre_query. They have run_on_host and run_kubectl tools.
   You do NOT run host commands directly.
9.5. Skills: Use list_skills to show available domain skills. Use activate_skill to load skill
     knowledge for answering domain questions. Use read_skill_reference for deep-dive material.
     Use search_skill_registry to find skills by keyword across local and remote registries.
9.6. SKILL SELF-IMPROVEMENT: When a sub-agent reports inability to handle a scenario, finds no
     matching skill, or you identify a gap in existing skill coverage:
     1. Use create_skill(name, description) to generate a new skill from a description, OR
        use improve_skill(skill_name, improvement) to enhance an existing skill.
     2. The skill is immediately available as a draft — activate and continue the investigation.
     3. Draft skills will be reviewed later by human operators via /skill review and /skill promote.
     Only create/improve skills when there is a clear knowledge gap — do not generate skills
     for one-off questions.
9.7. Sending notifications / distributing reports: First call activate_skill("notification-operator")
     to load notification tools (list_notification_channels, send_to_channel, distribute_report).
     Then use list_notification_channels to discover targets, send_to_channel for single-channel
     text/issue/file sends, or distribute_report for batch format-aware report distribution.
9.7.1. Sharing content to channels: Use share_content(subject, body, channel_names) to deliver
     text content directly to notification channels. For long content (>4000 chars), it auto-uploads
     to S3 and sends a presigned download URL. Use this for scheduled job outputs, reports, or any
     content that needs reliable delivery to channels.
9.8. Monitoring providers: Use list_monitoring_providers to show configured external monitoring
     integrations. For querying Datadog/external metrics or alerts, dispatch to detect_agent or rca_agent
     (they have cross-platform provider tools).
10. ANY other AWS question (e.g., "list my ElastiCache clusters", "show CloudFront distributions",
   "what are my DynamoDB tables", "check Route53 zones", "get cost breakdown",
   "describe Step Functions", "show GuardDuty findings") → dispatch to sre_query.
   This is your CATCH-ALL for AWS queries that don't fit rules 2-9.

ADDITIONAL TASKS by USER REQUEST:
1.If YOUR ASK for run specifc CLI commands, use the sre_query agent which has read-only AWS CLI access to 60+ services. For health issue investigation, use detect_agent and rca_agent. For inventory and resource questions, use scan_agent. For fix plan generation, use sre_agent. For any question that doesn't fit those categories, default to sre_query.
2.任何命令行的操作，都丢给SRE来执行

CONTEXT BLOCKS: Messages may contain <attached_file>, <referenced_issue>, and <referenced_resource>
context blocks with pre-fetched data. Use this context directly to answer the user's question.
References like I#42 (issue) and R#17 (resource) are resolved before reaching you.

IMPORTANT — YOUR BOUNDARIES:
- You do NOT query AWS directly. All AWS investigation is done by sub-agents.
- For general AWS queries with no specific agent, ALWAYS use sre_query — it has the full
  read-only AWS CLI and can query any AWS service (60+ services).
- Sub-agents have specialized tools AND AWS CLI. They choose whichever gives the most accurate result.
- Your job: understand the user's intent, dispatch to the right sub-agent, and present results clearly.
- NEVER duplicate work. If a sub-agent already returned data, use that — do not query again.
- Present results concisely. Show severity, affected resources, and recommended actions.
- When multiple issues exist, prioritize by severity (critical > high > medium > low).
"""


def create_main_agent() -> Agent:
    """Create and return the Main Agent (Orchestrator).

    Returns:
        Configured Strands Agent with sub-agents and metadata tools.
    """
    from agenticops.config import get_scan_focus, resolve_scan_services
    from agenticops.config import get_agent_model_config, get_agent_window_size

    model_id, max_tokens = get_agent_model_config("main")
    cache_kwargs: dict = {}
    if settings.bedrock_cache_enabled:
        cache_kwargs = {"cache_config": CacheConfig(strategy="auto"), "cache_tools": "default"}
    model = BedrockModel(
        model_id=model_id,
        region_name=settings.bedrock_region,
        max_tokens=max_tokens,
        **cache_kwargs,
    )

    focus = get_scan_focus()
    focus_section = ""
    if focus != "all":
        services = resolve_scan_services(focus)
        focus_section = f"""

SCAN FOCUS (user preference):
Current focus: {focus}
When dispatching to scan_agent, use services='{services}'.
When dispatching to detect_agent, scope the check to: {focus} resources.
If the user explicitly requests a different scope, honor their request over this default.
"""

    prompt = MAIN_SYSTEM_PROMPT + focus_section

    agent = Agent(
        system_prompt=build_system_prompt(prompt, include_account=False),
        model=model,
        conversation_manager=SlidingWindowConversationManager(
            window_size=get_agent_window_size("main"), per_turn=True
        ),
        tools=[
            # Sub-agents as tools
            scan_agent,
            detect_agent,
            rca_agent,
            sre_agent,
            sre_query,
            executor_agent,
            reporter_agent,
            # Direct metadata tools
            get_active_account,
            get_managed_resources,
            get_health_issue,
            get_resource_by_id,
            get_rca_result,
            get_fix_plan,
            get_approved_fix_plan,
            approve_fix_plan,
            list_health_issues,
            update_health_issue_status,
            create_health_issue,
            # Graph tools
            detect_network_anomalies,
            analyze_network_segments,
            detect_single_points_of_failure,
            analyze_capacity_risk,
            # Agent Skills (knowledge + self-improvement — no execution tools on main agent)
            list_skills,
            activate_skill,
            read_skill_reference,
            create_skill,
            improve_skill,
            search_skill_registry,
            # Monitoring integrations
            list_monitoring_providers,
            # Notification tools (direct, no skill activation needed)
            share_content,
            # MCP tool providers (external servers)
            *get_mcp_clients(),
        ],
    )

    return agent
