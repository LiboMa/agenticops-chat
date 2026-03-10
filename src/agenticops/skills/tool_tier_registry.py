"""Tool Security Tier Registry — maps each @tool function to its SecurityTier.

This registry is the Step 5 wire-up from SECURE_TOOL_MIGRATION_GUIDE.md.
It provides a lookup table that agent_binding.py uses to enforce tier restrictions
without modifying the existing @tool decorators (Strands compatibility).

Usage:
    from agenticops.skills.tool_tier_registry import TOOL_TIERS, get_tool_tier
    tier = get_tool_tier("describe_ec2")  # → SecurityTier.T0
"""

from agenticops.skills._models import SecurityTier

T0 = SecurityTier.T0_READONLY  # Read-only diagnostic
T1 = SecurityTier.T1_LOW_RISK  # State-modifying (logged)
T2 = SecurityTier.T2_HIGH_RISK  # Risky operations (requires approval)
T3 = SecurityTier.T3_DESTRUCTIVE  # Destructive/irreversible (requires dual approval)

# ── Tool → Tier mapping ──────────────────────────────────────────────

TOOL_TIERS: dict[str, SecurityTier] = {
    # --- aws_tools.py (T0: read-only AWS describe/list) ---
    "assume_role": T1,              # Creates STS session
    "describe_ec2": T0,
    "list_lambda_functions": T0,
    "describe_rds": T0,
    "list_s3_buckets": T0,
    "describe_ecs": T0,
    "describe_eks": T0,
    "list_dynamodb": T0,
    "list_sqs": T0,
    "list_sns": T0,

    # --- aws_cli_tool.py ---
    "run_aws_cli": T2,              # Arbitrary AWS CLI — risky
    "run_aws_cli_readonly": T0,     # Read-only wrapper

    # --- cloudtrail_tools.py (T0: read-only) ---
    "lookup_cloudtrail_events": T0,

    # --- cloudwatch_tools.py (T0: read-only) ---
    "list_alarms": T0,
    "get_alarm_history": T0,
    "get_metrics": T0,
    "query_logs": T0,

    # --- detect_tools.py (T0: read-only analysis) ---
    "run_zscore_detection": T0,
    "run_rule_evaluation": T0,

    # --- eks_tools.py (T0: read-only) ---
    "describe_eks_clusters": T0,
    "describe_eks_nodegroups": T0,
    "check_eks_pod_ip_capacity": T0,
    "map_eks_to_vpc_topology": T0,

    # --- file_tools.py ---
    "read_local_file": T0,
    "tail_local_file": T0,
    "search_local_file": T0,
    "list_local_directory": T0,
    "file_stat": T0,
    "write_local_file": T2,         # Writes to filesystem — risky

    # --- integration_tools.py (T0: read-only) ---
    "query_provider_metrics": T0,
    "query_provider_logs": T0,
    "list_provider_alerts": T0,
    "list_monitoring_providers": T0,
    "store_metric_snapshot": T1,     # Writes metric data

    # --- kb_tools.py ---
    "search_sops": T0,
    "search_similar_cases": T0,
    "read_kb_sops": T0,
    "write_kb_case": T1,            # Writes to knowledge base
    "write_kb_sop": T1,             # Writes to knowledge base
    "distill_case_study": T1,       # Creates derived content

    # --- memory_tools.py ---
    "remember_this": T0,            # Memory write (WAL-protected, T0-safe)
    "recall_memories": T0,          # Memory read

    # --- metadata_tools.py ---
    "get_active_account": T0,
    "get_managed_resources": T0,
    "save_resources": T1,           # Writes resource metadata
    "create_health_issue": T1,      # Creates issue
    "get_health_issue": T0,
    "get_resource_by_id": T0,
    "list_health_issues": T0,
    "update_health_issue_status": T1,  # Modifies issue state
    "save_rca_result": T1,          # Writes RCA result
    "get_rca_result": T0,
    "save_fix_plan": T1,            # Creates fix plan
    "get_fix_plan": T0,
    "approve_fix_plan": T2,         # Approves execution — risky
    "get_approved_fix_plan": T0,
    "save_execution_result": T1,    # Writes execution result
    "mark_fix_executed": T2,        # Changes fix state — risky
    "mark_fix_failed": T1,          # Marks failure
    "list_send_targets": T0,

    # --- network_tools.py (T0: read-only) ---
    "describe_vpcs": T0,
    "describe_subnets": T0,
    "describe_security_groups": T0,
    "describe_route_tables": T0,
    "describe_nat_gateways": T0,
    "describe_transit_gateways": T0,
    "describe_load_balancers": T0,
    "describe_region_topology": T0,
    "describe_tgw_peering_attachments": T0,
    "describe_cross_region_topology": T0,
    "analyze_vpc_topology": T0,

    # --- notification_tools.py ---
    "list_notification_channels": T0,
    "send_to_channel": T1,          # Sends notifications
    "distribute_report": T1,        # Distributes reports

    # --- report_tools.py ---
    "save_report": T1,              # Writes report
    "list_reports": T0,

    # --- trace_tools.py (T0: read-only) ---
    "query_traces": T0,
    "get_trace_detail": T0,
    "get_service_dependencies": T0,
    "find_error_traces": T0,
}


def get_tool_tier(tool_name: str) -> SecurityTier:
    """Get the security tier for a tool. Defaults to T1 for unknown tools."""
    return TOOL_TIERS.get(tool_name, SecurityTier.T1_LOW_RISK)
