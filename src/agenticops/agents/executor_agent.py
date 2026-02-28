"""Executor Agent - L4 Auto Operation: execute approved fix plans.

Reads an approved FixPlan, executes each step via the appropriate backend
(AWS CLI, SSM/SSH host commands, or kubectl), verifies results with
post-checks, and records the full execution trail. Follows a strict
7-step protocol with safety gates at every stage.

Exposed as a tool for the Main Agent (agents-as-tools pattern).
"""

import logging

from strands import Agent, tool
from strands.agent.conversation_manager import SlidingWindowConversationManager
from strands.models.bedrock import BedrockModel

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
from agenticops.tools.aws_cli_tool import run_aws_cli, run_aws_cli_readonly
from agenticops.skills.tools import activate_skill, read_skill_reference
from agenticops.skills.execution import run_on_host, run_kubectl
from agenticops.skills.loader import build_prompt_with_skills

logger = logging.getLogger(__name__)

EXECUTOR_SYSTEM_PROMPT = f"""You are the Executor Agent for AgenticOps (L4 Auto Operation).
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
   Call assume_role first to get credentials for the target account.
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
- AWS API operations (e.g., modify-instance-attribute, update-function-code, modify-db-instance):
  Use run_aws_cli (write) or run_aws_cli_readonly (read-only checks).
- Host-level commands (e.g., systemctl restart, kill, disk cleanup, log inspection):
  Use run_on_host with method="ssm" (or "ssh"). Set require_confirmation=True for write commands —
  the plan approval serves as the confirmation.
- Kubernetes operations (e.g., rollout restart, scale deployment, apply manifest):
  Use run_kubectl with the cluster_name and namespace. Set require_confirmation=True for write commands.
- Resource verification: Use describe tools (describe_ec2, describe_rds, etc.) for targeted checks.

SKILL ACTIVATION:
Before executing steps that involve host-level or Kubernetes operations, call activate_skill
to load relevant domain knowledge (e.g., activate_skill("linux-admin") for host commands,
activate_skill("kubernetes-admin") for kubectl operations). This helps you understand the
commands and verify they are correct before execution.

STEP TYPE IDENTIFICATION:
When the plan's steps include a field like "action" or "runner_type", use it to route:
  - "aws_cli" → run_aws_cli / run_aws_cli_readonly
  - "host_command" / "ssm" / "ssh" → run_on_host
  - "kubectl" → run_kubectl
  - "verify" → appropriate read-only tool
When the step has no explicit type, infer from the command:
  - Starts with "aws " → run_aws_cli
  - Starts with "kubectl " → run_kubectl
  - OS-level commands (systemctl, kill, df, ps, etc.) → run_on_host
"""


@tool
def executor_agent(fix_plan_id: int) -> str:
    """Execute an approved FixPlan following the L4 execution protocol.

    Retrieves the approved plan, runs pre-checks, executes each step,
    verifies with post-checks, and records the full execution trail.
    Only approved plans are executed; unapproved plans are rejected.

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
        model = BedrockModel(
            model_id=settings.bedrock_model_id,
            region_name=settings.bedrock_region,
            max_tokens=settings.bedrock_max_tokens,
        )

        agent = Agent(
            system_prompt=build_prompt_with_skills(EXECUTOR_SYSTEM_PROMPT, agent_type="executor"),
            model=model,
            callback_handler=None,
            conversation_manager=SlidingWindowConversationManager(
                window_size=settings.bedrock_window_size, per_turn=True
            ),
            tools=[
                # Plan verification (safety gate)
                get_approved_fix_plan,
                # Execution — AWS CLI (write + read-only)
                run_aws_cli,
                run_aws_cli_readonly,
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
                # Agent Skills (domain knowledge for understanding commands)
                activate_skill,
                read_skill_reference,
            ],
        )

        result = agent(
            f"Execute FixPlan #{fix_plan_id}. "
            f"Follow the 7-step execution protocol exactly. "
            f"Start with step 1: call get_approved_fix_plan({fix_plan_id})."
        )
        return str(result)
    except Exception as e:
        logger.exception("Executor agent failed for FixPlan #%d", fix_plan_id)
        return f"Executor agent error: {e}"
