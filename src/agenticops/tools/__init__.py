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
)
from agenticops.tools.detect_tools import (
    run_zscore_detection,
    run_rule_evaluation,
)
from agenticops.tools.kb_tools import (
    search_sops,
    search_similar_cases,
    read_kb_sops,
    write_kb_case,
    write_kb_sop,
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
    # Detect tools
    "run_zscore_detection",
    "run_rule_evaluation",
    # KB tools
    "search_sops",
    "search_similar_cases",
    "read_kb_sops",
    "write_kb_case",
    "write_kb_sop",
]
