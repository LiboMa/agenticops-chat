"""SRE Agent - Read-only Fix Plan generation using Strands SDK.

Generates structured fix plans from RCA results with risk-level classification
(L0-L3) and an approval gate model. This agent NEVER executes fixes — it only
produces plans. Exposed as a tool for the Main Agent (agents-as-tools pattern).
"""

import logging

from strands import Agent, tool
from strands.models.bedrock import BedrockModel

from agenticops.config import settings
from agenticops.tools.aws_tools import (
    assume_role,
    describe_ec2,
    describe_rds,
    list_lambda_functions,
)
from agenticops.tools.network_tools import (
    describe_vpcs,
    describe_subnets,
    describe_security_groups,
    describe_route_tables,
    describe_nat_gateways,
    describe_transit_gateways,
    describe_load_balancers,
    describe_region_topology,
    analyze_vpc_topology,
)
from agenticops.tools.eks_tools import (
    describe_eks_clusters,
    describe_eks_nodegroups,
    check_eks_pod_ip_capacity,
    map_eks_to_vpc_topology,
)
from agenticops.tools.metadata_tools import (
    get_active_account,
    get_managed_resources,
    get_health_issue,
    get_rca_result,
    save_fix_plan,
)
from agenticops.tools.kb_tools import search_sops, search_similar_cases
from agenticops.tools.change_tools import (
    get_change_request,
    ground_change_targets,
    attach_change_target,
    evaluate_change_policy,
    submit_change_review,
)
from agenticops.graph.tools import (
    query_reachability,
    query_impact_radius,
    find_network_path,
    detect_network_anomalies,
    analyze_dependency_chain,
    detect_single_points_of_failure,
    analyze_capacity_risk,
    simulate_edge_removal,
)
from agenticops.tools.aws_cli_tool import run_aws_cli_readonly  # fallback
from agenticops.providers.base import get_cli_tool_for_issue, get_all_cli_tools
from agenticops.skills.tools import activate_skill, read_skill_reference
from agenticops.skills.execution import run_on_host, run_kubectl
from agenticops.agents.preamble import (
    LOCAL_FILE_INSPECTION_BLOCK,
    build_system_prompt,
    skills_activation_block,
)
from agenticops.tools.memory_tools import search_agent_memory
from agenticops.agents.enhanced import enhanced_task

logger = logging.getLogger(__name__)

_SRE_SKILLS_BLOCK = skills_activation_block(
    extra_routes=['Security → activate_skill("security-engineer")'],
    outro=(
        "The skill provides decision trees, command references, and fix patterns — use them to\n"
        "     inform your risk assessment and fix plan steps."
    ),
)

SRE_SYSTEM_PROMPT = """You are the SRE Agent for AgenticOps.
You have THREE modes of operation:
  A) Fix Plan generation — structured plans from RCA results.
  B) General AWS investigation — answer any question about AWS resources and
     infrastructure using your tools and the AWS CLI.
  C) Change review — review a human's CHANGE REQUEST (C#N) for legitimacy and
     produce the change plan the Executor will run after approval.
You are READ-ONLY — you NEVER execute fixes or modify AWS resources.

MODE A — FIX PLAN PROTOCOL:
1. SETUP: Call get_active_account to see enabled accounts. Tools are account-addressed —
   pass account='<name>' when known, or omit it (single-account / inventory-matched
   hosts resolve automatically). Credentials come ONLY from registered accounts.
1.5. __SKILLS_BLOCK__
2. READ: Call get_health_issue and get_rca_result for the given issue.
3. SEARCH KB: Call search_sops for relevant procedures.
   Call search_similar_cases with a detailed description for past resolutions.
4. ASSESS RISK: Classify the fix as:
   - L0: Read-only verification (e.g., confirm metric recovered)
   - L1: Low-risk remediation of a SINGLE workload — these are the most common:
     * kubectl rollout undo/restart on a single deployment
     * kubectl set resources (adjust memory/cpu limits) on a single deployment
     * kubectl delete pod (force restart a single pod)
     * kubectl delete networkpolicy (remove blocking policy)
     * kubectl scale deployment (adjust replica count)
     * kubectl set image (rollback to known-good image)
     * kubectl apply for a single resource fix
     * Adjust alarm threshold, update tag
   - L2: Multi-resource or service-affecting changes (e.g., resize instance, modify SG rules,
     changes affecting multiple deployments or namespaces, node-level operations)
   - L3: High-risk change (e.g., restart service, failover, data migration, node drain)
   IMPORTANT: Simple single-workload kubectl fixes (rollback, set resources, delete policy)
   should be L1. Only escalate to L2 if the change affects multiple resources or has broad blast radius.
5. INVESTIGATE: Gather current state of affected resource:
   - Call describe_region_topology for a region-level view of all VPCs, Transit Gateways,
     and peering connections — understand cross-VPC blast radius first.
   - Call analyze_vpc_topology for VPC-level blast radius analysis (subnet classification,
     blackhole routes, SG dependency map, peering/endpoint connectivity).
   - Call relevant describe tools (EC2, RDS, network tools, etc.)
   - For EKS issues: use describe_eks_clusters, describe_eks_nodegroups,
     check_eks_pod_ip_capacity, and map_eks_to_vpc_topology.
   - Call query_reachability to verify subnet internet connectivity with exact path trace.
   - Call find_network_path for point-to-point traffic path analysis.
   - Call detect_network_anomalies to find structural issues (routing loops, orphan nodes, blackholes).
   - Call query_impact_radius to assess blast radius of proposed changes.
   - Call analyze_dependency_chain to trace which services depend on the failing resource.
   - Call detect_single_points_of_failure to identify infrastructure SPOFs.
   - Call analyze_capacity_risk to check for IP exhaustion or pod capacity issues.
   - Call simulate_edge_removal to preview the impact of removing a network link or rule.
   - Check if the issue has already self-resolved
5.5. HOST-LEVEL INVESTIGATION (when you need OS-level data for fix planning):
     a. Use run_on_host(host_id=INSTANCE_ID, command="...") to check current host
        state (disk, memory, processes, service status). method="auto" (default)
        tries SSM then falls back to SSH automatically if SSM is unavailable.
     b. For EKS pods: use run_kubectl(cluster_name=CLUSTER, command="get pods/logs/describe ...")
        to inspect Kubernetes resources directly.
     c. Follow the decision trees from the activated skill for systematic diagnosis.
     d. Read-only commands execute automatically. Write commands (systemctl restart, kill)
        should be included in the fix plan, NOT executed directly.
5.6. __LOCAL_FILE_BLOCK__
6. GENERATE PLAN: Create a structured fix plan with:
   - Ordered steps with specific AWS CLI/API calls
   - Pre-checks (what to verify before starting)
   - Post-checks (what to verify after completion)
   - Rollback plan (how to undo if fix fails)
   - Estimated impact (downtime, performance impact)
7. SAVE: Call save_fix_plan with ALL details in a SINGLE call.
   IMPORTANT: Each HealthIssue must have ONE consolidated fix plan covering ALL fix steps.
   Do NOT call save_fix_plan multiple times for the same issue.
   If the issue needs multiple actions, include them all as ordered steps in the steps array.
   save_fix_plan will automatically update an existing draft plan if one exists.

MODE B — GENERAL AWS INVESTIGATION:
When you receive a general query (not tied to a specific HealthIssue), act as an
AWS infrastructure investigator:
1. SETUP: Call get_active_account to see enabled accounts. Pass account='<name>' to
   tools when known; otherwise single-account / inventory match resolves automatically.
1.5. ACTIVATE SKILLS: If the query involves a specific domain, call activate_skill to
     load relevant troubleshooting knowledge (e.g., activate_skill("network-engineer")
     for network questions, activate_skill("kubernetes-admin") for EKS questions).
     Use read_skill_reference for deep-dive material when needed.
2. QUERY: Use the best tool for the job:
   - Specialized tools first (describe_ec2, describe_rds, network tools, EKS tools, etc.)
   - The cloud CLI tool for ANY service that lacks a specialized tool —
     this covers 60+ services (ElastiCache, Redshift, Step Functions, CloudFront,
     WAF, Route53, DynamoDB, SQS, SNS, Glue, Athena, EMR, CodePipeline,
     GuardDuty, Security Hub, Cost Explorer, Organizations, etc.)
3. HOST-LEVEL DATA: When investigating host or pod issues, use run_on_host
   (method="auto" climbs the SSM→SSH ladder) or run_kubectl to gather OS-level
   or Kubernetes diagnostics directly.
3.5. LOCAL FILE DATA: When you need to read local configs, logs, Terraform, CloudFormation
   templates, Kubernetes manifests, scripts, or other operational artifacts:
   a. First call activate_skill("local-os-operator") to load file operation tools and decision trees.
   b. Then use read_local_file, tail_local_file, search_local_file, list_local_directory, file_stat
      — these tools are dynamically registered when you activate the skill.
   c. Sensitive files (.env, credentials, private keys, etc.) are automatically blocked.
3.7. WEB RESEARCH: Call activate_skill("web-research") to load web_search + web_fetch,
     then check cloud provider status pages or upstream documentation for
     additional context during investigation.
4. RESPOND: Present findings clearly with resource IDs, status, and key attributes.

MODE C — CHANGE REVIEW PROTOCOL (ChangeRequest C#N; you decide legitimacy, the platform decides state):
1. READ: get_change_request(N) — intent, targets (target_hints), account, requested type (normal|emergency).
2. GROUND: ground_change_targets(N). For every UNRESOLVED hint run a read-only describe yourself; if
   the resource exists call attach_change_target(N, resource_id, resource_type, region,
   hint='<the unresolved hint, verbatim>') — the platform re-verifies it. If any target cannot be
   verified, STOP and submit verdict needs_clarification listing the unresolved targets. Never invent ids.
3. ASSESS: risk L0-L3 with the Mode A rubric (a tag update is L1; SG rules / resize are L2; restart service,
   failover, data migration, node drain are L3) and action_type tag|scale|config|network|iam|delete|other.
4. POLICY: evaluate_change_policy(N, risk_level, action_type). Action 'block' → skip PLAN and submit
   verdict rejected, quoting the rule.
5. PLAN: save_fix_plan(plan_kind='change', change_request_id=N, risk_level, title, summary, steps,
   pre_checks, post_checks, rollback_plan, estimated_impact). MANDATORY: post_checks that PROVE the change
   took effect (e.g. describe-tags shows the tag) and a rollback_plan that undoes it exactly.
   Steps are exact CLI commands with real ids — the Executor runs them verbatim after approval.
6. VERDICT: submit_change_review(N, verdict, risk_level, action_type, reasons). Verdicts:
   approved_for_planning | needs_clarification | rejected. The platform (not you) routes approval,
   applies the policy and writes every state — you only recommend.

RULES & GUARDRAILS (CRITICAL):
- NEVER execute fixes. Only generate plans (Mode A/C) or query information (Mode B).
- Only READ operations on AWS.
- Always include rollback plans for L2+ fixes.
- Reference SOP steps when available.
- Be specific: use actual resource IDs, exact CLI commands, specific parameter values.
- **NO HALLUCINATION**: Never invent inventories, like - AWS ARNs, Instance IDs, IP addresses, or metrics. If you cannot find the resource, state clearly that it was not found.
- **ERROR RECOVERY**: If a tool or CLI command returns an error (e.g., syntax error, resource not found), DO NOT stop. Analyze the error message, adjust your query parameters, and try again up to 3 times before reporting failure.
- **CONTEXT MANAGEMENT**: When reading logs or files (via the cloud CLI tool or `read_local_file`), ALWAYS use limits (e.g., `tail -n 50` or `--max-items 10`) to prevent context window overflow.
- **SECRET REDACTION**: If your queries return sensitive data (passwords, tokens, API keys) in configs or logs, you MUST mask them (e.g., `[REDACTED]`) before outputting the final response or fix plan.

TOOL SELECTION — accuracy first:
- Use specialized tools (describe_ec2, describe_rds, network tools, etc.) when they cover the service.
- Use the cloud CLI tool when: (a) the service has no specialized tool, OR (b) the CLI
  gives more precise/complete data (e.g., specific fields, parameters not exposed by
  specialized tools), OR (c) the user asks about any service/resource not covered
  by specialized tools.
- Choose whichever tool produces the most accurate result for the task at hand.
- When using the cloud CLI tool, always use --query to filter output fields.
  Example: `aws rds describe-db-instances --query 'DBInstances[].{Id:DBInstanceIdentifier,Status:DBInstanceStatus,Class:DBInstanceClass}'`
  Example: `aws elasticache describe-cache-clusters --query 'CacheClusters[].{Id:CacheClusterId,Status:CacheClusterStatus,Engine:Engine}'`
  Example: `aws ce get-cost-and-usage --time-period Start=2026-02-01,End=2026-02-28 --granularity MONTHLY --metrics BlendedCost --query 'ResultsByTime[].Total'`

"""

# Shared fragments live in preamble.py (single-source for RCA + SRE);
# placeholder substitution avoids f-string brace escaping in the long prompt.
SRE_SYSTEM_PROMPT = SRE_SYSTEM_PROMPT.replace("__SKILLS_BLOCK__", _SRE_SKILLS_BLOCK)
SRE_SYSTEM_PROMPT = SRE_SYSTEM_PROMPT.replace("__LOCAL_FILE_BLOCK__", LOCAL_FILE_INSPECTION_BLOCK)


def _once(text: str, old: str) -> str:
    """`old`, checked to occur exactly once in `text` (a RuntimeError, not an assert that -O strips)."""
    found = text.count(old)
    if found != 1:
        raise RuntimeError(f"SRE prompt: {old[:60]!r} must occur exactly once, found {found}")
    return old


def _without_mode_c(full: str) -> str:
    """The Mode A/B prompt: `full` without Mode C. Every anchor must occur exactly once, so a prompt edit that
    breaks one fails at import instead of leaking Mode C into the other builds."""
    start = full.index(_once(full, "MODE C — CHANGE REVIEW PROTOCOL"))
    end = full.index(_once(full, "RULES & GUARDRAILS (CRITICAL):"))
    text = full
    for old, new in (
        ("You have THREE modes of operation:", "You have TWO modes of operation:"),
        ("  C) Change review — review a human's CHANGE REQUEST (C#N) for legitimacy and\n"
         "     produce the change plan the Executor will run after approval.\n", ""),
        (full[start:end], ""),  # the blank line before MODE C stays, as the one before RULES
        ("(Mode A/C)", "(Mode A)"),
    ):
        text = text.replace(_once(text, old), new)
    return text


# Mode A (sre_agent) and Mode B (sre_query) builds: they do not carry the Mode C tools, so they must not see Mode C
# (an agent must never see a tool it cannot use). Only the change-review build gets SRE_SYSTEM_PROMPT.
SRE_BASE_PROMPT = _without_mode_c(SRE_SYSTEM_PROMPT)


# Mode C tools — only in the change-review build (least privilege): the Mode A (sre_agent) and Mode B
# (sre_query) builds never carry them (the Main agent has its own read tools for change requests).
_CHANGE_REVIEW_TOOLS = (
    get_change_request,
    ground_change_targets,
    attach_change_target,
    evaluate_change_policy,
    submit_change_review,
)


def _create_sre_agent(cli_tool=None, cli_tools: list | None = None, *, change_review: bool = False) -> Agent:
    """Create a reusable SRE Agent instance.

    change_review=True builds the Mode C (change review) agent: the only build that carries the change tools
    and the only one whose prompt describes Mode C (SRE_SYSTEM_PROMPT; every other build gets SRE_BASE_PROMPT).
    """
    from agenticops.config import get_agent_model_config, get_agent_conversation_manager, get_agent_context_manager, get_bedrock_boto_session

    model_id, max_tokens = get_agent_model_config("sre")
    from agenticops.agents.preamble import bedrock_model_kwargs
    cache_kwargs = bedrock_model_kwargs(model_id)
    model = BedrockModel(
        model_id=model_id,
        boto_session=get_bedrock_boto_session(),
        max_tokens=max_tokens,
        **cache_kwargs,
    )
    _tools = [
        assume_role,
        get_active_account,
        get_managed_resources,
        get_health_issue,
        get_rca_result,
        search_sops,
        search_similar_cases,
        save_fix_plan,
        # Change review (Mode C) — the change-review build only
        *(_CHANGE_REVIEW_TOOLS if change_review else ()),
        # AWS describe tools (read-only)
        describe_ec2,
        describe_rds,
        list_lambda_functions,
        # Network tools (read-only)
        describe_vpcs,
        describe_subnets,
        describe_security_groups,
        describe_route_tables,
        describe_nat_gateways,
        describe_transit_gateways,
        describe_load_balancers,
        describe_region_topology,
        analyze_vpc_topology,
        # EKS networking tools
        describe_eks_clusters,
        describe_eks_nodegroups,
        check_eks_pod_ip_capacity,
        map_eks_to_vpc_topology,
        # Graph-based analysis tools
        query_reachability,
        query_impact_radius,
        find_network_path,
        detect_network_anomalies,
        # SRE analysis tools
        analyze_dependency_chain,
        detect_single_points_of_failure,
        analyze_capacity_risk,
        simulate_edge_removal,
        # Cloud CLI (provider-resolved, fallback to AWS read-only)
        *(cli_tools if cli_tools else [cli_tool or run_aws_cli_readonly]),
        # Agent Skills (domain knowledge + host/kubectl execution)
        activate_skill,
        read_skill_reference,
        run_on_host,
        run_kubectl,
        # Agent Memory (cross-agent search)
        search_agent_memory,
    ]
    # Optional ACP enhanced backend — delegate complex tasks to Claude Code (default off)
    if settings.acp_enhanced_enabled:
        _tools.append(enhanced_task)
    return Agent(
        system_prompt=build_system_prompt(SRE_SYSTEM_PROMPT if change_review else SRE_BASE_PROMPT,
                                          include_account=False, agent_type="sre", agent_name="sre"),
        model=model,
        callback_handler=None,
        conversation_manager=get_agent_conversation_manager("sre"),
        context_manager=get_agent_context_manager("sre"),
        tools=_tools,
    )


@tool
def sre_agent(issue_id: int) -> str:
    """Generate a Fix Plan for a HealthIssue based on RCA results.

    USE FOR: "fix", "plan fix", "remediate", "how do I resolve" + an issue ID
    (I#N). READ-ONLY: never executes — produces a plan with risk level (L0-L3),
    ordered steps, rollback plan, and pre/post checks for the approval gate.
    NOT FOR: executing plans (executor_agent) or general queries (sre_query).

    Args:
        issue_id: The HealthIssue ID to create a fix plan for.

    Returns:
        Fix plan summary with risk level, steps, and rollback plan.
    """
    try:
        # Resolve provider CLI tool from issue's account
        cli_tool = None
        try:
            from agenticops.models import HealthIssue, get_db_session
            with get_db_session() as db:
                issue = db.query(HealthIssue).filter_by(id=issue_id).first()
                if issue and issue.account_id:
                    cli_tool = get_cli_tool_for_issue(issue.account_id)
        except Exception:
            pass

        from agenticops.agents.preamble import invoke_with_retry, infer_parent_agent
        from agenticops.services.agent_log_service import track_agent
        agent = _create_sre_agent(cli_tool=cli_tool)
        with track_agent("sre", "fix_plan", f"issue_id={issue_id}", parent_agent=infer_parent_agent()) as tracker:
            result = invoke_with_retry(agent,
                f"Generate a Fix Plan for HealthIssue #{issue_id}. "
                f"Follow the fix plan protocol (Mode A). Be specific with resource IDs and CLI commands."
            )
            tracker.set_result(result)
        return str(result)
    except Exception as e:
        logger.exception("SRE agent failed")
        return f"SRE agent error: {e}"


def _account_name(account_id: int) -> str:
    from agenticops.models import CloudAccount, get_db_session
    with get_db_session() as db:
        return db.query(CloudAccount.name).filter_by(id=account_id).scalar() or ""


def sre_agent_review_change(change_request_id: int) -> str:
    """Run the SRE agent in Mode C for one change request (called by change_service._run_review).

    State transitions and 'a review must end with a verdict' are enforced by change_service — this
    function only builds the agent and runs it. The review watchdog guards only the async path
    (start_review(sync=False)); with sync=True (Main's review_change) the review runs in the caller's
    thread with no timeout, and the caller blocks until it returns.

    A request bound to an account is reviewed with THAT account's CLI tool or not at all. Any exception
    propagates on purpose: change_service._run_review logs it and rolls the request back to draft with
    the reason (fail-closed).
    """
    from agenticops.agents.preamble import infer_parent_agent, invoke_with_retry
    from agenticops.services import change_service as cs
    from agenticops.services.agent_log_service import track_agent

    cr = cs.get_change(change_request_id)
    cli_tool = None
    account_hint = ""
    if cr.get("account_id"):
        # Credential rule: a CR bound to an account is reviewed on THAT account or not at all — never
        # fall back to the default, auto-resolving CLI tool (it may resolve to another account).
        cli_tool = get_cli_tool_for_issue(cr["account_id"])
        if cli_tool is None:
            raise RuntimeError(
                f"credentials for account #{cr['account_id']} of ChangeRequest #{change_request_id} could not "
                "be resolved — refusing to review it on any other account")
        name = _account_name(cr["account_id"])
        if name:
            account_hint = f" Target account: '{name}' — pass account='{name}' to every tool that takes an account."
    agent = _create_sre_agent(cli_tool=cli_tool, change_review=True)
    prompt = (
        f"Review ChangeRequest #{change_request_id}. Follow MODE C — CHANGE REVIEW PROTOCOL exactly: "
        "read, ground every target (fail closed), assess risk and action_type, evaluate policy, save the change plan "
        "with plan_kind='change' (post_checks + rollback_plan mandatory), then submit_change_review with your verdict."
    ) + account_hint
    with track_agent("sre", "change_review", f"change_request_id={change_request_id}", parent_agent=infer_parent_agent()) as tracker:
        result = invoke_with_retry(agent, prompt)
        tracker.set_result(result)
    return str(result)


@tool
def review_change(change_request_id: int) -> str:
    """Review a CHANGE REQUEST (C#N) — legitimacy, risk, policy and the change plan.

    USE FOR: right after request_change, or "review change", "review CR", "change request" + C#N.
    READ-ONLY: never executes — the SRE grounds targets, classifies risk, evaluates policy and saves
    the plan; approval is a separate human step (Web Plans & Changes, or /approve C<N> in the CLI).
    NOT FOR: incident fix plans (sre_agent) or executing (execute_change).

    Args:
        change_request_id: The C# number returned by request_change.

    Returns:
        The SRE's review summary (verdict, risk, plan) or why the review could not start.
    """
    from agenticops.services import change_service as cs
    try:
        text = cs.start_review(change_request_id, sync=True)
    except cs.ChangeError as e:
        return f"Change review not started: {e}"
    try:
        cr = cs.get_change(change_request_id)
    except cs.ChangeError:
        return text or "Review ended; the change request could not be re-read."
    status = f"Platform status of C#{change_request_id}: {cr['status']}"
    if cr["status"] == "draft":  # rolled back: crash, timeout or no verdict — the review did NOT complete
        reason = "; ".join(cr.get("review_reasons") or []) or "no verdict was recorded"
        status += f" — the review did not complete ({reason}). Nothing was approved."
    return f"{text}\n\n{status}" if text else status


@tool
def sre_query(query: str, region: str = "us-east-1") -> str:
    """CATCH-ALL for any AWS question that doesn't fit another agent.

    USE FOR: ad-hoc queries on ANY AWS service via read-only CLI (60+ services
    — ElastiCache, CloudFront, Route53, Step Functions, API Gateway, cost
    breakdowns, GuardDuty findings...), any CLI command request, kubectl /
    run_on_host operations, deep dependency-chain or change-simulation asks.
    When unsure which agent fits an AWS question, choose this one.
    NOT FOR: full inventory (scan_agent), health sweeps (detect_agent),
    issue analysis (rca_agent), or fix plans (sre_agent).

    Args:
        query: The question or investigation request (e.g., 'list ElastiCache
               clusters', 'show CloudFront distributions', 'cost breakdown').
        region: AWS region to investigate (default: us-east-1).

    Returns:
        Investigation results with resource details.
    """
    try:
        from agenticops.agents.preamble import invoke_with_retry, infer_parent_agent
        from agenticops.services.agent_log_service import track_agent
        cli_tools = get_all_cli_tools() or [run_aws_cli_readonly]
        agent = _create_sre_agent(cli_tools=cli_tools)
        with track_agent("sre", "query", f"region={region} query={query[:200]}", parent_agent=infer_parent_agent()) as tracker:
            result = invoke_with_retry(agent,
                f"General AWS investigation (Mode B). Region: {region}\n"
                f"Query: {query}\n"
                f"Pass account='<name>' to tools when the target account is known; otherwise "
                f"tools auto-resolve (single-account / inventory match). "
                f"If no specialized tool covers the service, use run_aws_cli_readonly with --query filters."
            )
            tracker.set_result(result)
        return str(result)
    except Exception as e:
        logger.exception("SRE query failed")
        return f"SRE query error: {e}"
