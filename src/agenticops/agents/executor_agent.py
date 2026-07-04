"""Executor Agent - L4 Auto Operation: execute approved fix plans.

Reads an approved FixPlan, executes each step via the appropriate backend
(AWS CLI, SSM/SSH host commands, or kubectl), verifies results with
post-checks, and records the full execution trail. Follows a strict
7-step protocol with safety gates at every stage.

Exposed as a tool for the Main Agent (agents-as-tools pattern).
"""

import logging

from strands import Agent, tool
from strands.models.bedrock import BedrockModel
from strands.models.model import CacheConfig

from agenticops.config import settings
from agenticops.tools.aws_tools import (
    assume_role,
    describe_ec2,
    describe_rds,
)
from agenticops.tools.network_tools import (
    describe_vpcs,
    describe_security_groups,
    describe_load_balancers,
)
from agenticops.tools.eks_tools import (
    describe_eks_clusters,
)
from agenticops.tools.metadata_tools import (
    get_active_account,
    get_health_issue,
    get_approved_fix_plan,
    save_execution_result,
    mark_fix_executed,
    mark_fix_failed,
)
from agenticops.graph.tools import (
    query_reachability,
    find_network_path,
    detect_network_anomalies,
)
from agenticops.tools.aws_cli_tool import run_aws_cli, run_aws_cli_readonly  # fallback
from agenticops.providers.base import get_cli_tool_for_issue
from agenticops.skills.tools import activate_skill, read_skill_reference
from agenticops.skills.execution import run_on_host, run_kubectl
from agenticops.agents.preamble import build_system_prompt
from agenticops.tools.memory_tools import search_agent_memory

logger = logging.getLogger(__name__)

def _build_executor_prompt() -> str:
    """Build the executor system prompt at agent-construction time.

    A function (not a module-level f-string) so runtime settings changes
    (executor_enabled, timeouts) are reflected without a process restart.
    """
    return f"""You are the Executor Agent for AgenticOps (L4 Auto Operation).
Your job is to execute APPROVED fix plans — and ONLY approved plans.

EXECUTION PROTOCOL (7 steps — follow in exact order):

1. VERIFY
   Call get_approved_fix_plan(fix_plan_id) to retrieve the plan.
   If the response starts with "REJECTED:", STOP immediately and report the rejection.
   Never proceed with a non-approved plan.

2. GATE
   The executor is {"ENABLED" if settings.executor_enabled else "DISABLED"}.
   If disabled, STOP and report: "Executor is disabled. Set AIOPS_EXECUTOR_ENABLED=true to enable."

3. PRE-CHECK
   For each item in the plan's pre_checks list:
   - Execute the check using the appropriate read-only tool (see TOOL SELECTION).
   - Record the result (pass/fail + output).
   - If ANY pre-check fails, ABORT:
     Call save_execution_result(status="aborted", ...) and mark_fix_failed.
     Report which pre-check failed and why.

4. EXECUTE
   Steps run against the plan's target account: pass account='<name>' to
   run_on_host/run_kubectl/CLI tools when the plan specifies one; otherwise
   single-account / inventory auto-resolution applies. Credentials come ONLY
   from registered accounts (never a local profile).
   For each step in the plan's steps list (in order):
   - Determine the correct execution tool based on the step type (see TOOL SELECTION).
   - Execute the command and record: step_index, command, status (succeeded/failed), output, duration.
   - If a step FAILS, STOP execution of remaining steps and go to step 6 (ROLLBACK).
   - Never modify, skip, or improvise steps — execute EXACTLY what the approved plan specifies.

5. POST-CHECK
   For each item in the plan's post_checks list:
   - Execute the verification using the appropriate read-only tool.
   - Record the result.
   - Post-check failures do NOT trigger rollback, but must be reported.

6. ROLLBACK (only if step 4 failed)
   Execute the plan's rollback_plan steps in reverse order using the same tool type as
   the original step. Record each rollback step result.
   If rollback also fails, report it clearly.

7. FINALIZE
   Call save_execution_result with all collected results:
   - status: "succeeded" (all steps + post-checks passed)
            "failed" (step failed, rollback attempted)
            "rolled_back" (step failed, rollback succeeded)
            "aborted" (pre-check failed)
   Then call mark_fix_executed (if succeeded) or mark_fix_failed (if failed/rolled_back/aborted).

SAFETY RULES (NEVER violate):
- NEVER execute a plan that is not approved (get_approved_fix_plan enforces this).
- NEVER skip pre-checks.
- NEVER modify, add, or improvise steps beyond what the plan specifies.
- NEVER skip rollback on failure — always attempt it.
- Record EVERY action for audit trail.
- Per-step timeout: {settings.executor_step_timeout} seconds.
- Total timeout: {settings.executor_total_timeout} seconds.

TOOL SELECTION (route each step to the correct backend):
- AWS/Cloud API operations (e.g., modify-instance-attribute, update-function-code, modify-db-instance):
  Use the provided cloud CLI tool (supports both read and write operations with security filtering).
- Host-level commands (e.g., systemctl restart, kill, disk cleanup, log inspection):
  Use run_on_host (method="auto" climbs the SSM→SSH ladder; or force method="ssm"/"ssh").
  Set require_confirmation=True for write commands — the plan approval serves as the confirmation.
- Kubernetes operations (e.g., rollout restart, scale deployment, apply manifest):
  Use run_kubectl with the cluster_name and namespace. Set require_confirmation=True for write commands.
- Resource verification: Use describe tools (describe_ec2, describe_rds, etc.) for targeted checks.

SKILL ACTIVATION:
Before executing steps that involve host-level or Kubernetes operations, call activate_skill
to load relevant domain knowledge (e.g., activate_skill("linux-admin") for host commands,
activate_skill("kubernetes-admin") for kubectl operations). This helps you understand the
commands and verify they are correct before execution. If a step fails with an unfamiliar
error, activate_skill("web-research") loads web_search + web_fetch for upstream research.

LOCAL FILE ACCESS:
When you need to read local configs, logs, templates, or verify file-based pre/post-checks:
a. First call activate_skill("local-os-operator") to load file operation tools and decision trees.
b. Then use read_local_file, tail_local_file, search_local_file, list_local_directory, file_stat
   — these tools are dynamically registered when you activate the skill.
c. Sensitive files (credentials, .env, private keys) are automatically blocked.

STEP TYPE IDENTIFICATION:
When the plan's steps include a field like "action" or "runner_type", use it to route:
  - "aws_cli" → the cloud CLI tool
  - "host_command" / "ssm" / "ssh" → run_on_host
  - "kubectl" → run_kubectl
  - "file_read" / "verify_file" → activate_skill("local-os-operator") first, then read_local_file / search_local_file
  - "verify" → appropriate read-only tool
When the step has no explicit type, infer from the command:
  - Starts with "aws " or cloud CLI command → the cloud CLI tool
  - Starts with "kubectl " → run_kubectl
  - OS-level commands (systemctl, kill, df, ps, etc.) → run_on_host
  - File paths or "cat", "less", "grep" references → activate_skill("local-os-operator") first, then use file tools
"""


# Module-level constant kept for tests/tooling that measure the prompt;
# agent construction calls _build_executor_prompt() for fresh settings.
EXECUTOR_SYSTEM_PROMPT = _build_executor_prompt()


@tool
def executor_agent(fix_plan_id: int) -> str:
    """Execute an APPROVED FixPlan following the 7-step execution protocol.

    USE FOR: "execute", "run fix", "apply fix" + a plan ID. SAFETY: only
    approved plans run — verify with get_approved_fix_plan and confirm with
    the user BEFORE dispatching. Runs pre-checks, executes steps exactly as
    written, post-checks, rolls back on failure, records the audit trail.
    NOT FOR: creating plans (sre_agent) or approving them (approve_fix_plan).

    Args:
        fix_plan_id: The FixPlan ID to execute (must be in 'approved' status).

    Returns:
        Execution summary with status, step results, and any errors.
    """
    if not settings.executor_enabled:
        return (
            "Executor is DISABLED. Cannot execute fix plans. "
            "Set AIOPS_EXECUTOR_ENABLED=true to enable execution."
        )

    try:
        from agenticops.config import get_agent_model_config, get_agent_conversation_manager, get_agent_context_manager, get_executor_interventions, get_bedrock_boto_session
        from agenticops.models import get_db_session, FixPlan, HealthIssue

        # Resolve provider CLI tool from fix plan's issue account
        cli_tool = None
        try:
            with get_db_session() as db:
                plan_for_acct = db.query(FixPlan).filter_by(id=fix_plan_id).first()
                if plan_for_acct:
                    issue = db.query(HealthIssue).filter_by(id=plan_for_acct.health_issue_id).first()
                    if issue and issue.account_id:
                        cli_tool = get_cli_tool_for_issue(issue.account_id)
        except Exception:
            pass

        # Query risk level BEFORE agent creation for smart model selection
        model_id, max_tokens = get_agent_model_config("executor")
        if settings.executor_smart_model:
            try:
                with get_db_session() as db:
                    plan = db.query(FixPlan).filter(FixPlan.id == fix_plan_id).first()
                    risk_level = (plan.risk_level or "L3") if plan else "L3"
                    if risk_level in ("L0", "L1"):
                        model_id = settings.executor_simple_model_id
                        logger.info(
                            "Executor smart model: using %s for %s fix plan #%d",
                            model_id, risk_level, fix_plan_id,
                        )
            except Exception as e:
                logger.warning("Smart model lookup failed, using default: %s", e)

        cache_kwargs: dict = {}
        if settings.bedrock_cache_enabled:
            cache_kwargs = {"cache_config": CacheConfig(strategy="auto"), "cache_tools": "default"}
        model = BedrockModel(
            model_id=model_id,
            boto_session=get_bedrock_boto_session(),
            max_tokens=max_tokens,
            **cache_kwargs,
        )

        agent = Agent(
            system_prompt=build_system_prompt(_build_executor_prompt(), include_account=False, agent_type="executor", agent_name="executor"),
            model=model,
            callback_handler=None,
            conversation_manager=get_agent_conversation_manager("executor"),
            context_manager=get_agent_context_manager("executor"),
            interventions=get_executor_interventions(),
            tools=[
                # Plan verification (safety gate)
                get_approved_fix_plan,
                # Cloud CLI (provider-resolved with security filtering, fallback to AWS)
                *(([cli_tool] if cli_tool else [run_aws_cli, run_aws_cli_readonly])),
                # Execution — Host-level (SSM/SSH)
                run_on_host,
                # Execution — Kubernetes (kubectl)
                run_kubectl,
                # Verification (describe tools)
                describe_ec2,
                describe_rds,
                describe_vpcs,
                describe_security_groups,
                describe_load_balancers,
                describe_eks_clusters,
                # Network verification
                query_reachability,
                find_network_path,
                detect_network_anomalies,
                # Result recording
                save_execution_result,
                mark_fix_executed,
                mark_fix_failed,
                # Context
                get_active_account,
                get_health_issue,
                assume_role,
                # Agent Skills (domain knowledge + dynamic tool loading)
                activate_skill,
                read_skill_reference,
                # Agent Memory (cross-agent search)
                search_agent_memory,
            ],
        )

        from agenticops.agents.preamble import invoke_with_retry
        from agenticops.services.agent_log_service import track_agent
        with track_agent("executor", "execute_fix", f"fix_plan_id={fix_plan_id}", parent_agent="main") as tracker:
            result = invoke_with_retry(agent,
                f"Execute FixPlan #{fix_plan_id}. "
                f"Follow the 7-step execution protocol exactly. "
                f"Start with step 1: call get_approved_fix_plan({fix_plan_id})."
            )
            tracker.set_result(result)
        return str(result)
    except Exception as e:
        logger.exception("Executor agent failed for FixPlan #%d", fix_plan_id)
        return f"Executor agent error: {e}"
