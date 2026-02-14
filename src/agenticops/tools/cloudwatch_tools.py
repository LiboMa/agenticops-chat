"""CloudWatch tools for Strands agents.

Wraps existing logic from monitor/cloudwatch.py and adds new alarm tools.
"""

import json
import logging
import time as time_module
from datetime import datetime, timedelta
from typing import Optional

from botocore.exceptions import ClientError
from strands import tool

from agenticops.tools.aws_tools import _get_client
from agenticops.scan.services import AWS_SERVICES

logger = logging.getLogger(__name__)


@tool
def list_alarms(region: str, resource_type: str = "", state: str = "") -> str:
    """List CloudWatch Alarms, optionally filtered by resource type or state.

    Args:
        region: AWS region
        resource_type: Filter by namespace prefix (e.g., 'AWS/EC2', 'AWS/RDS'). Empty for all.
        state: Filter by alarm state ('ALARM', 'OK', 'INSUFFICIENT_DATA'). Empty for all.

    Returns:
        JSON list of alarms with name, state, metric, namespace, and dimensions.
    """
    try:
        client = _get_client("cloudwatch", region)
    except RuntimeError as e:
        return str(e)

    alarms = []
    kwargs = {}
    if state:
        kwargs["StateValue"] = state

    try:
        paginator = client.get_paginator("describe_alarms")
        for page in paginator.paginate(**kwargs):
            for alarm in page.get("MetricAlarms", []):
                # Filter by resource_type (namespace) if specified
                if resource_type and not alarm.get("Namespace", "").startswith(
                    resource_type
                ):
                    continue

                dimensions = {
                    d["Name"]: d["Value"]
                    for d in alarm.get("Dimensions", [])
                }
                alarms.append({
                    "alarm_name": alarm["AlarmName"],
                    "state": alarm["StateValue"],
                    "metric_name": alarm.get("MetricName"),
                    "namespace": alarm.get("Namespace"),
                    "dimensions": dimensions,
                    "threshold": alarm.get("Threshold"),
                    "comparison": alarm.get("ComparisonOperator"),
                    "state_reason": alarm.get("StateReason", "")[:200],
                    "updated_at": str(alarm.get("StateUpdatedTimestamp", "")),
                })

        return json.dumps(alarms, default=str)
    except ClientError as e:
        return f"Error listing alarms in {region}: {e}"


@tool
def get_alarm_history(alarm_name: str, region: str, hours: int = 24) -> str:
    """Get state change history for a specific CloudWatch alarm.

    Args:
        alarm_name: Name of the CloudWatch alarm
        region: AWS region
        hours: Hours of history to retrieve (1-168)

    Returns:
        JSON list of alarm state transitions with timestamps and reasons.
    """
    try:
        client = _get_client("cloudwatch", region)
    except RuntimeError as e:
        return str(e)

    end_time = datetime.utcnow()
    start_time = end_time - timedelta(hours=min(hours, 168))

    try:
        response = client.describe_alarm_history(
            AlarmName=alarm_name,
            HistoryItemType="StateUpdate",
            StartDate=start_time,
            EndDate=end_time,
            MaxRecords=50,
        )

        history = []
        for item in response.get("AlarmHistoryItems", []):
            history.append({
                "timestamp": str(item.get("Timestamp", "")),
                "type": item.get("HistoryItemType"),
                "summary": item.get("HistorySummary", ""),
            })

        return json.dumps(history, default=str)
    except ClientError as e:
        return f"Error getting alarm history for {alarm_name}: {e}"


@tool
def get_metrics(
    resource_id: str,
    resource_type: str,
    region: str,
    metric_names: str = "",
    hours: int = 1,
) -> str:
    """Get CloudWatch metrics for a specific resource.

    Args:
        resource_id: AWS resource identifier (instance ID, function name, etc.)
        resource_type: Service type (EC2, RDS, Lambda, S3, DynamoDB, SQS, ECS)
        region: AWS region
        metric_names: Comma-separated metric names, or empty for service defaults
        hours: Hours of data to retrieve (1-72)

    Returns:
        JSON object mapping metric names to data points (timestamp, value).
    """
    try:
        client = _get_client("cloudwatch", region)
    except RuntimeError as e:
        return str(e)

    service_def = AWS_SERVICES.get(resource_type)
    if not service_def or not service_def.cloudwatch_namespace:
        return f"No CloudWatch metrics defined for {resource_type}"

    # Determine which metrics to fetch
    if metric_names:
        metrics = [m.strip() for m in metric_names.split(",")]
    else:
        metrics = service_def.default_metrics

    if not metrics:
        return f"No default metrics for {resource_type}"

    # Build dimensions based on service type
    dimension_map = {
        "EC2": ("InstanceId", resource_id),
        "Lambda": ("FunctionName", resource_id),
        "RDS": ("DBInstanceIdentifier", resource_id),
        "S3": ("BucketName", resource_id),
        "DynamoDB": ("TableName", resource_id),
        "SQS": ("QueueName", resource_id.split("/")[-1]),
        "ECS": ("ClusterName", resource_id.split("/")[-1]),
    }
    dim_name, dim_value = dimension_map.get(
        resource_type, ("ResourceId", resource_id)
    )
    dimensions = [{"Name": dim_name, "Value": dim_value}]

    end_time = datetime.utcnow()
    start_time = end_time - timedelta(hours=min(hours, 72))

    results = {}
    for metric_name in metrics:
        try:
            response = client.get_metric_data(
                MetricDataQueries=[
                    {
                        "Id": "m1",
                        "MetricStat": {
                            "Metric": {
                                "Namespace": service_def.cloudwatch_namespace,
                                "MetricName": metric_name,
                                "Dimensions": dimensions,
                            },
                            "Period": 300,
                            "Stat": "Average",
                        },
                        "ReturnData": True,
                    }
                ],
                StartTime=start_time,
                EndTime=end_time,
            )

            data_points = []
            if response.get("MetricDataResults"):
                result = response["MetricDataResults"][0]
                timestamps = result.get("Timestamps", [])
                values = result.get("Values", [])
                for ts, val in zip(timestamps, values):
                    data_points.append({
                        "timestamp": str(ts),
                        "value": round(val, 4),
                    })

            results[metric_name] = data_points
        except ClientError as e:
            results[metric_name] = [{"error": str(e)}]

    return json.dumps(results, default=str)


@tool
def query_logs(
    log_group: str, region: str, query: str = "", hours: int = 1
) -> str:
    """Run a CloudWatch Logs Insights query.

    Args:
        log_group: Log group name or pattern
        region: AWS region
        query: Logs Insights query string. Default: error/exception filter.
        hours: Hours of logs to search (1-48)

    Returns:
        JSON list of matching log entries.
    """
    try:
        client = _get_client("logs", region)
    except RuntimeError as e:
        return str(e)

    if not query:
        query = """
        fields @timestamp, @message, @logStream
        | filter @message like /(?i)(error|exception|fail|critical)/
        | sort @timestamp desc
        | limit 50
        """

    end_time = datetime.utcnow()
    start_time = end_time - timedelta(hours=min(hours, 48))

    try:
        response = client.start_query(
            logGroupName=log_group,
            startTime=int(start_time.timestamp()),
            endTime=int(end_time.timestamp()),
            queryString=query,
            limit=100,
        )
        query_id = response["queryId"]

        # Poll for results
        status = "Running"
        max_wait = 30  # seconds
        elapsed = 0
        while status in ["Running", "Scheduled"] and elapsed < max_wait:
            time_module.sleep(0.5)
            elapsed += 0.5
            result = client.get_query_results(queryId=query_id)
            status = result["status"]

        if status == "Complete":
            entries = []
            for row in result.get("results", []):
                entry = {}
                for field in row:
                    entry[field["field"]] = field["value"]
                entries.append(entry)
            return json.dumps(entries, default=str)
        else:
            return f"Log query finished with status: {status}"

    except ClientError as e:
        return f"Error querying logs in {log_group}: {e}"
