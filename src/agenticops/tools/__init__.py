"""Strands SDK tools for AgenticOps agents."""

from agenticops.tools.aws_tools import (
    assume_role,
    describe_ec2,
    list_lambda_functions,
    describe_rds,
    list_s3_buckets,
    describe_ecs,
    describe_eks,
    list_dynamodb,
    list_sqs,
    list_sns,
)
from agenticops.tools.cloudwatch_tools import (
    list_alarms,
    get_alarm_history,
    get_metrics,
    query_logs,
)
from agenticops.tools.cloudtrail_tools import lookup_cloudtrail_events
from agenticops.tools.metadata_tools import (
    get_active_account,
    get_managed_resources,
    save_resources,
    create_health_issue,
    get_health_issue,
    list_health_issues,
    update_health_issue_status,
    save_rca_result,
    save_fix_plan,
    get_fix_plan,
    approve_fix_plan,
)
from agenticops.tools.detect_tools import (
    run_zscore_detection,
    run_rule_evaluation,
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
from agenticops.tools.kb_tools import (
    search_sops,
    search_similar_cases,
    read_kb_sops,
    write_kb_case,
    write_kb_sop,
    distill_case_study,
)
from agenticops.tools.aws_cli_tool import run_aws_cli
from agenticops.graph.tools import (
    query_reachability,
    query_impact_radius,
    find_network_path,
    detect_network_anomalies,
    analyze_network_segments,
)

__all__ = [
    # AWS tools
    "assume_role",
    "describe_ec2",
    "list_lambda_functions",
    "describe_rds",
    "list_s3_buckets",
    "describe_ecs",
    "describe_eks",
    "list_dynamodb",
    "list_sqs",
    "list_sns",
    # Network tools
    "describe_vpcs",
    "describe_subnets",
    "describe_security_groups",
    "describe_route_tables",
    "describe_nat_gateways",
    "describe_transit_gateways",
    "describe_load_balancers",
    "describe_region_topology",
    "analyze_vpc_topology",
    # EKS tools
    "describe_eks_clusters",
    "describe_eks_nodegroups",
    "check_eks_pod_ip_capacity",
    "map_eks_to_vpc_topology",
    # CloudWatch tools
    "list_alarms",
    "get_alarm_history",
    "get_metrics",
    "query_logs",
    # CloudTrail tools
    "lookup_cloudtrail_events",
    # Metadata tools
    "get_active_account",
    "get_managed_resources",
    "save_resources",
    "create_health_issue",
    "get_health_issue",
    "list_health_issues",
    "update_health_issue_status",
    "save_rca_result",
    "save_fix_plan",
    "get_fix_plan",
    "approve_fix_plan",
    # Detect tools
    "run_zscore_detection",
    "run_rule_evaluation",
    # KB tools
    "search_sops",
    "search_similar_cases",
    "read_kb_sops",
    "write_kb_case",
    "write_kb_sop",
    "distill_case_study",
    # AWS CLI tool
    "run_aws_cli",
    # Graph tools
    "query_reachability",
    "query_impact_radius",
    "find_network_path",
    "detect_network_anomalies",
    "analyze_network_segments",
]
