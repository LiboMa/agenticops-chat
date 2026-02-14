"""CloudWatch Monitor - Metrics and Logs collection."""

import logging
from datetime import datetime, timedelta
from typing import Any, Optional

import boto3
from botocore.exceptions import ClientError

from agenticops.config import settings
from agenticops.models import AWSAccount, MetricDataPoint, get_session
from agenticops.scan.services import AWS_SERVICES

logger = logging.getLogger(__name__)


class CloudWatchMonitor:
    """CloudWatch metrics and logs monitor."""

    def __init__(self, account: AWSAccount):
        """Initialize with AWS account."""
        self.account = account
        self._session_cache: dict[str, boto3.Session] = {}

    def _get_assumed_session(self, region: str) -> boto3.Session:
        """Get boto3 session with assumed role."""
        cache_key = f"{self.account.account_id}:{region}"

        if cache_key in self._session_cache:
            return self._session_cache[cache_key]

        sts = boto3.client("sts", region_name=region)

        assume_kwargs = {
            "RoleArn": self.account.role_arn,
            "RoleSessionName": f"AgenticOps-Monitor-{self.account.account_id}",
            "DurationSeconds": 3600,
        }
        if self.account.external_id:
            assume_kwargs["ExternalId"] = self.account.external_id

        response = sts.assume_role(**assume_kwargs)
        credentials = response["Credentials"]

        session = boto3.Session(
            aws_access_key_id=credentials["AccessKeyId"],
            aws_secret_access_key=credentials["SecretAccessKey"],
            aws_session_token=credentials["SessionToken"],
            region_name=region,
        )
        self._session_cache[cache_key] = session
        return session

    def _get_cloudwatch_client(self, region: str):
        """Get CloudWatch client for region."""
        session = self._get_assumed_session(region)
        return session.client("cloudwatch")

    def _get_logs_client(self, region: str):
        """Get CloudWatch Logs client for region."""
        session = self._get_assumed_session(region)
        return session.client("logs")

    # =========================================================================
    # Metrics Collection
    # =========================================================================

    def get_metric_data(
        self,
        region: str,
        namespace: str,
        metric_name: str,
        dimensions: list[dict],
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        period: int = 300,
        statistic: str = "Average",
    ) -> list[dict]:
        """
        Get metric data from CloudWatch.

        Args:
            region: AWS region
            namespace: CloudWatch namespace (e.g., AWS/EC2)
            metric_name: Name of the metric
            dimensions: List of dimension dicts [{"Name": "...", "Value": "..."}]
            start_time: Start time for data (default: 1 hour ago)
            end_time: End time for data (default: now)
            period: Data point period in seconds
            statistic: Statistic type (Average, Sum, Maximum, Minimum, SampleCount)

        Returns:
            List of data points with timestamp and value
        """
        client = self._get_cloudwatch_client(region)

        if end_time is None:
            end_time = datetime.utcnow()
        if start_time is None:
            start_time = end_time - timedelta(hours=1)

        try:
            response = client.get_metric_data(
                MetricDataQueries=[
                    {
                        "Id": "m1",
                        "MetricStat": {
                            "Metric": {
                                "Namespace": namespace,
                                "MetricName": metric_name,
                                "Dimensions": dimensions,
                            },
                            "Period": period,
                            "Stat": statistic,
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
                    data_points.append(
                        {
                            "timestamp": ts,
                            "value": val,
                            "metric_name": metric_name,
                            "namespace": namespace,
                        }
                    )

            return data_points

        except ClientError as e:
            logger.error(f"Error getting metric {metric_name}: {e}")
            return []

    def get_ec2_metrics(
        self,
        instance_id: str,
        region: str,
        metrics: Optional[list[str]] = None,
        hours: int = 1,
    ) -> dict[str, list[dict]]:
        """Get common EC2 metrics for an instance."""
        if metrics is None:
            metrics = AWS_SERVICES["EC2"].default_metrics

        dimensions = [{"Name": "InstanceId", "Value": instance_id}]
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(hours=hours)

        results = {}
        for metric_name in metrics:
            data = self.get_metric_data(
                region=region,
                namespace="AWS/EC2",
                metric_name=metric_name,
                dimensions=dimensions,
                start_time=start_time,
                end_time=end_time,
            )
            results[metric_name] = data

        return results

    def get_lambda_metrics(
        self,
        function_name: str,
        region: str,
        metrics: Optional[list[str]] = None,
        hours: int = 1,
    ) -> dict[str, list[dict]]:
        """Get common Lambda metrics for a function."""
        if metrics is None:
            metrics = AWS_SERVICES["Lambda"].default_metrics

        dimensions = [{"Name": "FunctionName", "Value": function_name}]
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(hours=hours)

        results = {}
        for metric_name in metrics:
            data = self.get_metric_data(
                region=region,
                namespace="AWS/Lambda",
                metric_name=metric_name,
                dimensions=dimensions,
                start_time=start_time,
                end_time=end_time,
            )
            results[metric_name] = data

        return results

    def get_rds_metrics(
        self,
        db_identifier: str,
        region: str,
        metrics: Optional[list[str]] = None,
        hours: int = 1,
    ) -> dict[str, list[dict]]:
        """Get common RDS metrics for a database."""
        if metrics is None:
            metrics = AWS_SERVICES["RDS"].default_metrics

        dimensions = [{"Name": "DBInstanceIdentifier", "Value": db_identifier}]
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(hours=hours)

        results = {}
        for metric_name in metrics:
            data = self.get_metric_data(
                region=region,
                namespace="AWS/RDS",
                metric_name=metric_name,
                dimensions=dimensions,
                start_time=start_time,
                end_time=end_time,
            )
            results[metric_name] = data

        return results

    def get_service_metrics(
        self,
        service_type: str,
        resource_id: str,
        region: str,
        hours: int = 1,
    ) -> dict[str, list[dict]]:
        """Get metrics for any supported service."""
        service_def = AWS_SERVICES.get(service_type)
        if not service_def or not service_def.cloudwatch_namespace:
            logger.warning(f"No CloudWatch metrics defined for {service_type}")
            return {}

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

        dim_name, dim_value = dimension_map.get(service_type, ("ResourceId", resource_id))
        dimensions = [{"Name": dim_name, "Value": dim_value}]

        end_time = datetime.utcnow()
        start_time = end_time - timedelta(hours=hours)

        results = {}
        for metric_name in service_def.default_metrics:
            data = self.get_metric_data(
                region=region,
                namespace=service_def.cloudwatch_namespace,
                metric_name=metric_name,
                dimensions=dimensions,
                start_time=start_time,
                end_time=end_time,
            )
            results[metric_name] = data

        return results

    # =========================================================================
    # Logs Collection
    # =========================================================================

    def get_log_groups(self, region: str, prefix: Optional[str] = None) -> list[dict]:
        """List CloudWatch log groups."""
        client = self._get_logs_client(region)

        log_groups = []
        kwargs = {}
        if prefix:
            kwargs["logGroupNamePrefix"] = prefix

        try:
            paginator = client.get_paginator("describe_log_groups")
            for page in paginator.paginate(**kwargs):
                for group in page.get("logGroups", []):
                    log_groups.append(
                        {
                            "name": group["logGroupName"],
                            "arn": group.get("arn"),
                            "stored_bytes": group.get("storedBytes", 0),
                            "retention_days": group.get("retentionInDays"),
                            "created_at": datetime.fromtimestamp(
                                group.get("creationTime", 0) / 1000
                            ),
                        }
                    )
        except ClientError as e:
            logger.error(f"Error listing log groups: {e}")

        return log_groups

    def query_logs(
        self,
        region: str,
        log_group: str,
        query: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 100,
    ) -> list[dict]:
        """
        Query CloudWatch logs using Insights.

        Args:
            region: AWS region
            log_group: Log group name
            query: CloudWatch Insights query
            start_time: Query start time (default: 1 hour ago)
            end_time: Query end time (default: now)
            limit: Max results to return

        Returns:
            List of log entries
        """
        client = self._get_logs_client(region)

        if end_time is None:
            end_time = datetime.utcnow()
        if start_time is None:
            start_time = end_time - timedelta(hours=1)

        try:
            # Start query
            response = client.start_query(
                logGroupName=log_group,
                startTime=int(start_time.timestamp()),
                endTime=int(end_time.timestamp()),
                queryString=query,
                limit=limit,
            )
            query_id = response["queryId"]

            # Wait for results
            import time

            status = "Running"
            while status in ["Running", "Scheduled"]:
                time.sleep(0.5)
                result = client.get_query_results(queryId=query_id)
                status = result["status"]

            if status == "Complete":
                results = []
                for row in result.get("results", []):
                    entry = {}
                    for field in row:
                        entry[field["field"]] = field["value"]
                    results.append(entry)
                return results
            else:
                logger.warning(f"Query failed with status: {status}")
                return []

        except ClientError as e:
            logger.error(f"Error querying logs: {e}")
            return []

    def get_recent_errors(
        self,
        region: str,
        log_group: str,
        hours: int = 1,
        limit: int = 50,
    ) -> list[dict]:
        """Get recent error logs from a log group."""
        query = """
        fields @timestamp, @message, @logStream
        | filter @message like /(?i)(error|exception|fail|critical)/
        | sort @timestamp desc
        """
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(hours=hours)

        return self.query_logs(
            region=region,
            log_group=log_group,
            query=query,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
        )

    def get_lambda_errors(
        self, function_name: str, region: str, hours: int = 1
    ) -> list[dict]:
        """Get recent Lambda function errors."""
        log_group = f"/aws/lambda/{function_name}"
        return self.get_recent_errors(region, log_group, hours)

    # =========================================================================
    # Save Metrics to Database
    # =========================================================================

    def save_metric_data(
        self,
        resource_id: str,
        metrics_data: dict[str, list[dict]],
    ) -> int:
        """Save metric data points to database."""
        session = get_session()
        saved_count = 0

        try:
            for metric_name, data_points in metrics_data.items():
                for dp in data_points:
                    # Check for duplicate
                    existing = (
                        session.query(MetricDataPoint)
                        .filter_by(
                            resource_id=resource_id,
                            metric_name=metric_name,
                            timestamp=dp["timestamp"],
                        )
                        .first()
                    )

                    if not existing:
                        point = MetricDataPoint(
                            resource_id=resource_id,
                            metric_namespace=dp.get("namespace", ""),
                            metric_name=metric_name,
                            timestamp=dp["timestamp"],
                            value=dp["value"],
                        )
                        session.add(point)
                        saved_count += 1

            session.commit()
        except Exception as e:
            session.rollback()
            logger.exception("Failed to save metric data")
            raise
        finally:
            session.close()

        return saved_count
