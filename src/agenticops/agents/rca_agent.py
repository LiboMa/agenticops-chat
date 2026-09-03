"""RCA Agent - Root Cause Analysis using Strands SDK.

Receives a HealthIssue ID, investigates using AWS tools + Knowledge Base,
and persists structured RCA results. Exposed as a tool for the Main Agent
(agents-as-tools pattern).
"""

import logging
from datetime import datetime, timezone

from strands import Agent, tool
from strands.models.bedrock import BedrockModel

from agenticops.config import settings
from agenticops.tools.aws_tools import assume_role
from agenticops.tools.cloudwatch_tools import get_metrics, query_logs
from agenticops.tools.cloudtrail_tools import lookup_cloudtrail_events
from agenticops.tools.kb_tools import search_sops, search_similar_cases
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
    update_health_issue_status,
    save_rca_result,
)
from agenticops.graph.tools import (
    query_reachability,
    query_impact_radius,
    find_network_path,
    detect_network_anomalies,
)
from agenticops.tools.aws_cli_tool import run_aws_cli_readonly  # fallback
from agenticops.providers.base import get_cli_tool_for_issue
from agenticops.skills.tools import activate_skill, read_skill_reference
from agenticops.skills.execution import run_on_host, run_kubectl
from agenticops.agents.preamble import (
    LOCAL_FILE_INSPECTION_BLOCK,
    build_system_prompt,
    skills_activation_block,
)
from agenticops.tools.memory_tools import search_agent_memory
from agenticops.tools.integration_tools import (
    query_provider_metrics,
    query_provider_logs,
)

logger = logging.getLogger(__name__)

_RCA_SKILLS_BLOCK = skills_activation_block(
    extra_routes=[
        'Service degradation/latency/5xx/cascading failures → activate_skill("distributed-tracing")',
        'Unknown errors/CVE/vendor docs → activate_skill("web-research") for web_search + web_fetch',
    ],
    outro="The skill provides decision trees and command references — use them to guide your investigation.",
)

RCA_SYSTEM_PROMPT = """You are the RCA Agent for AgenticOps.
Your job is to perform Root Cause Analysis on a specific HealthIssue.

INVESTIGATION PROTOCOL — follow this order strictly:

1. SETUP: Call get_active_account to see enabled accounts. Tools are account-addressed —
   pass account='<name>' when known, or omit it (single-account / inventory-matched
   hosts resolve automatically). Credentials come ONLY from registered accounts.
1.5. __SKILLS_BLOCK__
2. READ ISSUE: Call get_health_issue with the given issue_id to understand the problem.
3. SET STATUS: Call update_health_issue_status to set status to 'investigating'.
4. SEARCH KNOWLEDGE BASE:
   a. Call search_sops with the resource type and issue keywords to find relevant SOPs.
   b. Call search_similar_cases with resource type and a full symptom description
      (not just keywords) for better vector-based semantic matching.
5. INVESTIGATE CHANGES (80% of issues are caused by recent changes):
   a. Call lookup_cloudtrail_events for the affected resource (last 24 hours).
   b. Look for deployment, config change, security group, IAM, or scaling events.
5.5. INVESTIGATE NETWORK PATH (when resource has connectivity issues):
   a. Call describe_region_topology to understand cross-VPC connectivity (Transit Gateways,
      peering connections) and identify which VPCs can communicate.
   b. Call analyze_vpc_topology with the affected resource's VPC ID for a holistic view
      of subnets (public/private), routing, gateways, peering, endpoints, SG dependencies,
      and blackhole routes. Check the reachability_summary for issues.
   c. For individual deep-dives, use describe_security_groups, describe_route_tables, etc.
   d. If behind a load balancer, call describe_load_balancers to check target health.
   e. For EKS workloads: call describe_eks_clusters and map_eks_to_vpc_topology to understand
      cluster networking. Use check_eks_pod_ip_capacity if pod scheduling failures are suspected.
      Call describe_eks_nodegroups for node-level health issues.
   f. Call query_reachability to verify subnet internet connectivity with exact path trace.
   g. Call find_network_path for point-to-point traffic path analysis.
   h. Call detect_network_anomalies to find structural issues (routing loops, orphan nodes, blackholes).
   i. Call query_impact_radius to assess blast radius of suspected failed component.
6. INVESTIGATE METRICS:
   a. Call get_metrics for the affected resource (relevant metrics based on resource type).
   b. Call query_logs if log patterns are relevant to the issue.
   c. Call query_provider_metrics/query_provider_logs to pull cross-platform data from
      Datadog or other configured providers for additional context.
6.5. INVESTIGATE DISTRIBUTED TRACES (when the issue involves service degradation, latency, or errors):
   a. First activate the skill: activate_skill("distributed-tracing") — this loads trace
      query tools and decision trees for cross-service analysis.
   b. Call get_service_dependencies() to understand the service call graph.
   c. Call query_traces(service=AFFECTED_SERVICE, lookback="15m") to find recent traces.
   d. For traces with high latency or errors, call get_trace_detail(trace_id) to see the
      full span tree — this reveals which downstream service is the actual bottleneck.
   e. Call find_error_traces(service=AFFECTED_SERVICE) to find error patterns across traces.
   f. KEY INSIGHT: If the affected service (e.g., frontend) shows errors, but the trace reveals
      the latency/error originates in a downstream service (e.g., redis, database), the ROOT CAUSE
      is the downstream service — not the one that triggered the alert.
   g. Example: Alert on "frontend HighErrorRate" → trace shows:
      frontend(5s) → checkoutservice(4.8s) → cartservice(4.5s) → redis(4.2s TIMEOUT)
      Root cause: redis, not frontend.
   NOTE: Trace investigation requires Jaeger to be deployed. If trace tools return a
   connection error, skip trace investigation and note "Distributed tracing not available"
   in your analysis. Do NOT let trace query failures block the RCA.
7. SYNTHESIZE: Combine all evidence into a root cause analysis:
   - Identify the most likely root cause with confidence score (0.0-1.0).
   - List contributing factors.
   - Provide actionable recommendations ordered by impact.
   - Compile the evidence list: every CloudTrail event, metric, log line, KB case,
     or trace you are citing, as [{"type", "ref", "summary"}]. Only cite what you
     actually retrieved THIS run — refs are verified against your tool calls, and
     fabricated refs reduce the stored confidence.
   NOTE: Do NOT create a fix plan — remediation planning is the SRE agent's job;
   your recommendations feed it.
8. SAVE: Call save_rca_result with all findings, including the evidence parameter.
   An INCIDENT MEMORY block may be present in your task prompt (prior conclusions
   for this same problem) — treat it as a prior to confirm or refute with fresh
   evidence, never as the answer.
8.5. EXTENDED INVESTIGATION: Use the provided cloud CLI tool for services not covered
     by specialized tools (ElastiCache, Redshift, Step Functions, API Gateway, etc.).
8.6. __LOCAL_FILE_BLOCK__
8.7. HOST-LEVEL INVESTIGATION (when you need OS-level data from an EC2 instance):
     a. Use run_on_host(host_id=INSTANCE_ID, command="...") to execute diagnostic
        commands (ps, top, df, free, journalctl, ss, etc.). method="auto" (default)
        tries SSM then falls back to SSH automatically if SSM is unavailable.
     b. For EKS pods: use run_kubectl(cluster_name=CLUSTER, command="get pods/logs/describe ...")
        to inspect Kubernetes resources directly.
     c. Follow the decision trees from the activated skill for systematic diagnosis.
     d. Read-only commands execute automatically. Write commands (systemctl restart, kill)
        require confirmation — present them to the user first.

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
- Verify resource validity and account permissions up front so tool calls do not fail.
- Only READ operations on AWS. The only writes are to our metadata DB.
- Always search SOPs and similar cases BEFORE forming conclusions.
- Include CloudTrail evidence when available — cite specific event names and timestamps.
- If you cannot determine root cause with confidence > 0.3, say so explicitly.
- Return a structured summary at the end.
TOOL SELECTION — accuracy first:
- Use specialized tools (get_metrics, query_logs, describe_* tools, etc.) when they cover the service.
- Use the cloud CLI tool when: (a) the service has no specialized tool (e.g., ElastiCache,
  Redshift, Step Functions, API Gateway), OR (b) the CLI gives more precise/complete data
  for investigation (e.g., specific fields, parameters not exposed by specialized tools).
- Choose whichever tool produces the most accurate result for the task at hand.
- When using the cloud CLI tool, always use --query to filter output fields.
  Example: `aws elasticache describe-cache-clusters --query 'CacheClusters[].{Id:CacheClusterId,Status:CacheClusterStatus,Engine:Engine}'`

"""

# Shared fragments live in preamble.py (single-source for RCA + SRE);
# placeholder substitution avoids f-string brace escaping in the long prompt.
RCA_SYSTEM_PROMPT = RCA_SYSTEM_PROMPT.replace("__SKILLS_BLOCK__", _RCA_SKILLS_BLOCK)
RCA_SYSTEM_PROMPT = RCA_SYSTEM_PROMPT.replace("__LOCAL_FILE_BLOCK__", LOCAL_FILE_INSPECTION_BLOCK)


def _build_topology_context(resource_id: str, max_chars: int = 2000) -> str:
    """Build a TOPOLOGY CONTEXT block from the persisted graph (zero AWS, zero LLM).

    Combines the resource's graph neighborhood (get_alert_context) with recent
    topology-change snapshots so the RCA agent sees "what changed" without
    extra tool calls. Fail-soft: any error returns "" and never blocks RCA.
    """
    if not settings.rca_topology_context_enabled or not resource_id or resource_id == "unknown":
        return ""
    try:
        lines: list[str] = []

        from agenticops.graph.context import get_alert_context
        ctx = get_alert_context(resource_id)
        if ctx:
            lines.append(f"Resource position: {ctx['topology_summary']}")
            deps = ctx.get("dependencies", {})
            downstream = deps.get("downstream", [])[:5]
            if downstream:
                dep_strs = [f"{d['label'] or d['id']} ({d['node_type']})" for d in downstream]
                lines.append(f"Downstream dependents: {', '.join(dep_strs)}")
            upstream = deps.get("upstream", [])[:5]
            if upstream:
                dep_strs = [f"{d['label'] or d['id']} ({d['node_type']})" for d in upstream]
                lines.append(f"Upstream dependencies: {', '.join(dep_strs)}")

        from agenticops.graph.store import GraphStore
        snapshots = GraphStore().get_recent_snapshots(limit=5)
        changed = [
            s for s in snapshots
            if (s.get("nodes_added") or 0) + (s.get("nodes_removed") or 0) + (s.get("nodes_updated") or 0) > 0
        ]
        if changed:
            lines.append("Recent topology changes (graph sync history):")
            for s in changed:
                lines.append(
                    f"  {s['snapshot_at']}: +{s['nodes_added']} added, "
                    f"~{s['nodes_updated']} updated, -{s['nodes_removed']} removed"
                    f" (scope={s['scope'] or 'all'})"
                )

        if not lines:
            return ""
        block = "TOPOLOGY CONTEXT (from infrastructure graph — pre-fetched, no tool call needed):\n" + "\n".join(lines)
        return block[:max_chars]
    except Exception:
        logger.debug("Topology context unavailable for %s", resource_id, exc_info=True)
        return ""


def _build_incident_memory(issue, max_chars: int = 2000) -> str:
    """INCIDENT MEMORY block: prior verified conclusions for the same problem.

    Precise recall (same fingerprint, else same issue_type+resource) of up to
    rca_incident_memory_max FINISHED issues, each with its verification status
    (human verdict > critic verdict) and fix outcome. Priors, not answers —
    the prompt tells the agent to confirm or refute with fresh evidence.
    Fail-soft: any error returns "".
    """
    if not settings.rca_incident_memory_enabled or issue is None:
        return ""
    try:
        from agenticops.models import FixExecution, FixPlan, HealthIssue, RCAResult, get_db_session

        with get_db_session() as db:
            candidates = []
            if issue.fingerprint:
                candidates = (
                    db.query(HealthIssue)
                    .filter(HealthIssue.fingerprint == issue.fingerprint,
                            HealthIssue.id != issue.id,
                            HealthIssue.status.in_(("resolved", "dismissed")))
                    .order_by(HealthIssue.detected_at.desc())
                    .limit(settings.rca_incident_memory_max)
                    .all()
                )
            if not candidates and issue.resource_id and issue.resource_id != "unknown":
                candidates = (
                    db.query(HealthIssue)
                    .filter(HealthIssue.resource_id == issue.resource_id,
                            HealthIssue.issue_type == getattr(issue, "issue_type", "other"),
                            HealthIssue.id != issue.id,
                            HealthIssue.status.in_(("resolved", "dismissed")))
                    .order_by(HealthIssue.detected_at.desc())
                    .limit(settings.rca_incident_memory_max)
                    .all()
                )
            if not candidates:
                return ""

            entries = []
            for prior in candidates:
                rca = (
                    db.query(RCAResult)
                    .filter_by(health_issue_id=prior.id)
                    .order_by(RCAResult.created_at.desc())
                    .first()
                )
                if rca is None:
                    continue
                verdict_bits = []
                if rca.human_verdict:
                    verdict_bits.append(f"human={rca.human_verdict}")
                if rca.critic_verdict:
                    verdict_bits.append(f"critic={rca.critic_verdict}")
                flag = " ⚠ this conclusion was refuted by a failed fix" \
                    if rca.critic_verdict == "disputed_by_execution" else ""
                fix_bit = ""
                plan = (
                    db.query(FixPlan)
                    .filter_by(health_issue_id=prior.id)
                    .order_by(FixPlan.created_at.desc())
                    .first()
                )
                if plan is not None:
                    execution = (
                        db.query(FixExecution)
                        .filter_by(fix_plan_id=plan.id)
                        .order_by(FixExecution.id.desc())
                        .first()
                    )
                    exec_status = execution.status if execution else plan.status
                    fix_bit = f" | fix: {plan.title[:60]} → {exec_status}"
                when = prior.resolved_at or prior.detected_at
                entries.append(
                    (1 if rca.human_verdict == "correct" else 0,
                     f"- I#{prior.id} [{when:%Y-%m-%d}] root_cause: {rca.root_cause[:200]} "
                     f"(confidence {rca.confidence:.0%}"
                     f"{', ' + ', '.join(verdict_bits) if verdict_bits else ''})"
                     f"{fix_bit}{flag}")
                )
            if not entries:
                return ""
            entries.sort(key=lambda e: e[0], reverse=True)  # human-confirmed first
            block = (
                "INCIDENT MEMORY (prior conclusions for this same problem — treat as PRIORS, "
                "not answers; confirm or refute with THIS run's evidence):\n"
                + "\n".join(e[1] for e in entries)
            )
            return block[:max_chars]
    except Exception:
        logger.debug("incident memory unavailable for issue #%s", getattr(issue, "id", "?"), exc_info=True)
        return ""


def _rca_escalation(issue, last_rca) -> tuple[int, str]:
    """How many effort tiers this RCA run earns, and why (pure, fail-safe).

    Two inputs only (MVP-2.2.1 experiment — deliberately narrow so the effect
    stays attributable): critical severity, and a rerun after the previous
    conclusion failed the quality gate or was refuted by a failed fix. They
    stack. Any uncertainty resolves to 0 — attribution failure must never
    raise the price.
    """
    if issue is None:
        return 0, ""
    reasons: list[str] = []
    try:
        if (issue.severity or "").lower() == "critical":
            reasons.append("critical")
        metric_data = issue.metric_data if isinstance(issue.metric_data, dict) else {}
        rerun = bool(metric_data.get("needs_review")) or (
            last_rca is not None
            and last_rca.critic_verdict in ("refuted", "disputed_by_execution")
        )
        if rerun:
            reasons.append("rerun")
    except Exception:
        logger.debug("escalation attribution failed; staying at base effort", exc_info=True)
        return 0, ""
    return len(reasons), "+".join(reasons)


def resolve_rca_effort(issue_id: int) -> tuple[int, str]:
    """(thinking_budget, escalate_reason) for an RCA run on this issue.

    Single source of truth so the rca_started event reports exactly what the
    model was given. Never raises — falls back to the base budget.
    """
    from agenticops.agents.preamble import resolve_thinking_budget
    from agenticops.config import get_agent_model_config

    _, max_tokens = get_agent_model_config("rca")
    escalate, reason = 0, ""
    try:
        from agenticops.models import HealthIssue, RCAResult, get_db_session
        with get_db_session() as db:
            issue = db.query(HealthIssue).filter_by(id=issue_id).first()
            last_rca = (
                db.query(RCAResult)
                .filter_by(health_issue_id=issue_id)
                .order_by(RCAResult.created_at.desc())
                .first()
            )
            escalate, reason = _rca_escalation(issue, last_rca)
    except Exception:
        logger.debug("RCA effort attribution failed for #%s", issue_id, exc_info=True)
    return resolve_thinking_budget("rca", max_tokens, escalate=escalate), reason


@tool
def rca_agent(issue_id: int) -> str:
    """Perform Root Cause Analysis on a HealthIssue.

    USE FOR: "analyze", "investigate", "RCA", "root cause", "why did this
    happen" + an issue ID (I#N). Also host-level troubleshooting during an
    investigation (has run_on_host + run_kubectl). Investigates via CloudTrail,
    metrics/logs, topology, and the KB; saves a structured RCAResult.
    NOT FOR: generating fix plans (sre_agent) or general AWS queries (sre_query).

    Args:
        issue_id: The HealthIssue ID to analyze.

    Returns:
        RCA summary with root cause, confidence, recommendations, and fix plan.
    """
    try:
        from agenticops.config import get_agent_model_config, get_agent_conversation_manager, get_agent_context_manager, get_bedrock_boto_session
        from agenticops.services.notification_service import batch_mode
        with batch_mode():
            # Resolve provider CLI tool from issue's account (+ incident memory)
            cli_tool = None
            issue_resource_id = ""
            incident_memory_block = ""
            try:
                from agenticops.models import HealthIssue, get_db_session
                with get_db_session() as db:
                    issue = db.query(HealthIssue).filter_by(id=issue_id).first()
                    if issue:
                        issue_resource_id = issue.resource_id or ""
                        if issue.account_id:
                            cli_tool = get_cli_tool_for_issue(issue.account_id)
                        incident_memory_block = _build_incident_memory(issue)
            except Exception:
                pass

            model_id, max_tokens = get_agent_model_config("rca")
            from agenticops.agents.preamble import bedrock_model_kwargs, thinking_fields_for_budget
            thinking_budget, escalate_reason = resolve_rca_effort(issue_id)
            thinking_fields = thinking_fields_for_budget(thinking_budget, max_tokens)
            cache_kwargs = bedrock_model_kwargs(model_id, thinking_fields)
            if thinking_fields and escalate_reason:
                logger.info(
                    "RCA #%d effort escalated to %d tokens (%s)",
                    issue_id, thinking_budget, escalate_reason,
                )
            model = BedrockModel(
                model_id=model_id,
                boto_session=get_bedrock_boto_session(),
                max_tokens=max_tokens,
                **cache_kwargs,
            )

            agent = Agent(
                system_prompt=build_system_prompt(RCA_SYSTEM_PROMPT, include_account=False, agent_type="rca", agent_name="rca"),
                model=model,
                callback_handler=None,
                conversation_manager=get_agent_conversation_manager("rca"),
                context_manager=get_agent_context_manager("rca"),
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
                    # Network investigation tools
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
                    # Cloud CLI (provider-resolved, fallback to AWS read-only)
                    cli_tool or run_aws_cli_readonly,
                    # Agent Skills (domain knowledge + host/kubectl execution + dynamic tools)
                    activate_skill,
                    read_skill_reference,
                    run_on_host,
                    run_kubectl,
                    # External monitoring providers
                    query_provider_metrics,
                    query_provider_logs,
                    # Agent Memory (cross-agent search)
                    search_agent_memory,
                ],
            )

            prompt = f"Analyze HealthIssue #{issue_id}. Follow the investigation protocol."
            topology_block = _build_topology_context(issue_resource_id)
            if topology_block:
                prompt = f"{prompt}\n\n{topology_block}"
            if incident_memory_block:
                prompt = f"{prompt}\n\n{incident_memory_block}"

            from agenticops.agents.preamble import invoke_with_retry, infer_parent_agent
            from agenticops.services.agent_log_service import track_agent
            invoke_kwargs = {}
            if settings.rca_max_iterations > 0:
                invoke_kwargs["limits"] = {"turns": settings.rca_max_iterations}
            started_at = datetime.now(timezone.utc)
            with track_agent("rca", "analyze_issue", f"issue_id={issue_id}", parent_agent=infer_parent_agent()) as tracker:
                result = invoke_with_retry(agent, prompt, **invoke_kwargs)
                tracker.set_result(result)

            # Post-RCA quality pipeline: evidence verification → critic →
            # confidence gate → (pass) auto-SRE / (fail) needs_review.
            # save_rca_result is pure persistence since MVP-2.2.0.
            try:
                from agenticops.services.rca_quality import run_post_rca_pipeline
                run_post_rca_pipeline(issue_id, list(agent.messages), started_at)
            except Exception:
                logger.exception("post-RCA quality pipeline failed for issue #%d", issue_id)
            return str(result)
    except Exception as e:
        logger.exception("RCA agent failed")
        return f"RCA agent error: {e}"
