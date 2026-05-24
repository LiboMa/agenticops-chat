"""Tests for agenticops.tools.cloudwatch_tools — targeting uncovered lines."""

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError


# ── list_alarms ──────────────────────────────────────────────────────

class TestListAlarms:
    """Cover lines 33-71 of cloudwatch_tools.py."""

    @patch("agenticops.tools.cloudwatch_tools._get_client")
    def test_list_alarms_no_filters(self, mock_get_client):
        from agenticops.tools.cloudwatch_tools import list_alarms

        paginator = MagicMock()
        paginator.paginate.return_value = [
            {
                "MetricAlarms": [
                    {
                        "AlarmName": "HighCPU",
                        "StateValue": "ALARM",
                        "MetricName": "CPUUtilization",
                        "Namespace": "AWS/EC2",
                        "Dimensions": [{"Name": "InstanceId", "Value": "i-123"}],
                        "Threshold": 90.0,
                        "ComparisonOperator": "GreaterThanThreshold",
                        "StateReason": "Threshold crossed",
                        "StateUpdatedTimestamp": datetime(2025, 1, 1, tzinfo=timezone.utc),
                    }
                ]
            }
        ]
        client = MagicMock()
        client.get_paginator.return_value = paginator
        mock_get_client.return_value = client

        result = list_alarms(region="us-east-1")
        data = json.loads(result)
        assert len(data) == 1
        assert data[0]["alarm_name"] == "HighCPU"
        assert data[0]["dimensions"]["InstanceId"] == "i-123"

    @patch("agenticops.tools.cloudwatch_tools._get_client")
    def test_list_alarms_with_state_filter(self, mock_get_client):
        from agenticops.tools.cloudwatch_tools import list_alarms

        paginator = MagicMock()
        paginator.paginate.return_value = [{"MetricAlarms": []}]
        client = MagicMock()
        client.get_paginator.return_value = paginator
        mock_get_client.return_value = client

        result = list_alarms(region="us-east-1", state="ALARM")
        data = json.loads(result)
        assert data == []
        paginator.paginate.assert_called_once_with(StateValue="ALARM")

    @patch("agenticops.tools.cloudwatch_tools._get_client")
    def test_list_alarms_resource_type_filter(self, mock_get_client):
        from agenticops.tools.cloudwatch_tools import list_alarms

        paginator = MagicMock()
        paginator.paginate.return_value = [
            {
                "MetricAlarms": [
                    {
                        "AlarmName": "RDS-High",
                        "StateValue": "OK",
                        "MetricName": "ReadLatency",
                        "Namespace": "AWS/RDS",
                        "Dimensions": [],
                    },
                    {
                        "AlarmName": "EC2-High",
                        "StateValue": "OK",
                        "MetricName": "CPUUtilization",
                        "Namespace": "AWS/EC2",
                        "Dimensions": [],
                    },
                ]
            }
        ]
        client = MagicMock()
        client.get_paginator.return_value = paginator
        mock_get_client.return_value = client

        result = list_alarms(region="us-east-1", resource_type="AWS/EC2")
        data = json.loads(result)
        assert len(data) == 1
        assert data[0]["alarm_name"] == "EC2-High"

    @patch("agenticops.tools.cloudwatch_tools._get_client")
    def test_list_alarms_client_error(self, mock_get_client):
        from agenticops.tools.cloudwatch_tools import list_alarms

        paginator = MagicMock()
        paginator.paginate.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "nope"}}, "DescribeAlarms"
        )
        client = MagicMock()
        client.get_paginator.return_value = paginator
        mock_get_client.return_value = client

        result = list_alarms(region="us-east-1")
        assert "Error listing alarms" in result

    @patch("agenticops.tools.cloudwatch_tools._get_client")
    def test_list_alarms_get_client_error(self, mock_get_client):
        from agenticops.tools.cloudwatch_tools import list_alarms

        mock_get_client.side_effect = RuntimeError("No credentials")
        result = list_alarms(region="us-east-1")
        assert "No credentials" in result


# ── get_alarm_history ────────────────────────────────────────────────

class TestGetAlarmHistory:
    """Cover lines 86-113."""

    @patch("agenticops.tools.cloudwatch_tools._get_client")
    def test_get_alarm_history_success(self, mock_get_client):
        from agenticops.tools.cloudwatch_tools import get_alarm_history

        client = MagicMock()
        client.describe_alarm_history.return_value = {
            "AlarmHistoryItems": [
                {
                    "Timestamp": datetime(2025, 1, 1, tzinfo=timezone.utc),
                    "HistoryItemType": "StateUpdate",
                    "HistorySummary": "Alarm went ALARM",
                }
            ]
        }
        mock_get_client.return_value = client

        result = get_alarm_history(alarm_name="HighCPU", region="us-east-1", hours=6)
        data = json.loads(result)
        assert len(data) == 1
        assert data[0]["summary"] == "Alarm went ALARM"

    @patch("agenticops.tools.cloudwatch_tools._get_client")
    def test_get_alarm_history_hours_capped(self, mock_get_client):
        from agenticops.tools.cloudwatch_tools import get_alarm_history

        client = MagicMock()
        client.describe_alarm_history.return_value = {"AlarmHistoryItems": []}
        mock_get_client.return_value = client

        result = get_alarm_history(alarm_name="HighCPU", region="us-east-1", hours=999)
        data = json.loads(result)
        assert data == []

    @patch("agenticops.tools.cloudwatch_tools._get_client")
    def test_get_alarm_history_client_error(self, mock_get_client):
        from agenticops.tools.cloudwatch_tools import get_alarm_history

        client = MagicMock()
        client.describe_alarm_history.side_effect = ClientError(
            {"Error": {"Code": "ResourceNotFound", "Message": "not found"}},
            "DescribeAlarmHistory",
        )
        mock_get_client.return_value = client

        result = get_alarm_history(alarm_name="NoAlarm", region="us-east-1")
        assert "Error getting alarm history" in result

    @patch("agenticops.tools.cloudwatch_tools._get_client")
    def test_get_alarm_history_get_client_error(self, mock_get_client):
        from agenticops.tools.cloudwatch_tools import get_alarm_history

        mock_get_client.side_effect = RuntimeError("bad creds")
        result = get_alarm_history(alarm_name="X", region="us-east-1")
        assert "bad creds" in result


# ── get_metrics ──────────────────────────────────────────────────────

class TestGetMetrics:
    """Cover lines 136-210."""

    @patch("agenticops.tools.cloudwatch_tools._get_client")
    def test_get_metrics_ec2_defaults(self, mock_get_client):
        from agenticops.tools.cloudwatch_tools import get_metrics

        client = MagicMock()
        client.get_metric_data.return_value = {
            "MetricDataResults": [
                {
                    "Timestamps": [datetime(2025, 1, 1, tzinfo=timezone.utc)],
                    "Values": [42.1234567],
                }
            ]
        }
        mock_get_client.return_value = client

        result = get_metrics(resource_id="i-123", resource_type="EC2", region="us-east-1")
        data = json.loads(result)
        assert isinstance(data, dict)
        # At least one metric key should have data points
        assert any(len(v) > 0 for v in data.values())

    @patch("agenticops.tools.cloudwatch_tools._get_client")
    def test_get_metrics_custom_metric_names(self, mock_get_client):
        from agenticops.tools.cloudwatch_tools import get_metrics

        client = MagicMock()
        client.get_metric_data.return_value = {
            "MetricDataResults": [{"Timestamps": [], "Values": []}]
        }
        mock_get_client.return_value = client

        result = get_metrics(
            resource_id="my-func",
            resource_type="Lambda",
            region="us-east-1",
            metric_names="Invocations, Duration",
        )
        data = json.loads(result)
        assert "Invocations" in data
        assert "Duration" in data

    @patch("agenticops.tools.cloudwatch_tools._get_client")
    def test_get_metrics_unknown_resource_type(self, mock_get_client):
        from agenticops.tools.cloudwatch_tools import get_metrics

        result = get_metrics(resource_id="x", resource_type="UnknownService", region="us-east-1")
        assert "No CloudWatch metrics defined" in result

    @patch("agenticops.tools.cloudwatch_tools._get_client")
    def test_get_metrics_client_error_per_metric(self, mock_get_client):
        from agenticops.tools.cloudwatch_tools import get_metrics

        client = MagicMock()
        client.get_metric_data.side_effect = ClientError(
            {"Error": {"Code": "InternalError", "Message": "oops"}}, "GetMetricData"
        )
        mock_get_client.return_value = client

        result = get_metrics(resource_id="i-123", resource_type="EC2", region="us-east-1")
        data = json.loads(result)
        # Each metric should have an error entry
        assert any("error" in v[0] for v in data.values() if v)

    @patch("agenticops.tools.cloudwatch_tools._get_client")
    def test_get_metrics_get_client_error(self, mock_get_client):
        from agenticops.tools.cloudwatch_tools import get_metrics

        mock_get_client.side_effect = RuntimeError("no creds")
        result = get_metrics(resource_id="i-1", resource_type="EC2", region="us-east-1")
        assert "no creds" in result

    @patch("agenticops.tools.cloudwatch_tools._get_client")
    def test_get_metrics_sqs_dimension(self, mock_get_client):
        """SQS uses QueueName = last segment of resource_id."""
        from agenticops.tools.cloudwatch_tools import get_metrics

        client = MagicMock()
        client.get_metric_data.return_value = {
            "MetricDataResults": [{"Timestamps": [], "Values": []}]
        }
        mock_get_client.return_value = client

        result = get_metrics(
            resource_id="https://sqs.us-east-1.amazonaws.com/123/my-queue",
            resource_type="SQS",
            region="us-east-1",
        )
        data = json.loads(result)
        assert isinstance(data, dict)


# ── query_logs ───────────────────────────────────────────────────────

class TestQueryLogs:
    """Cover lines 228-276."""

    @patch("agenticops.tools.cloudwatch_tools.time_module")
    @patch("agenticops.tools.cloudwatch_tools._get_client")
    def test_query_logs_default_query(self, mock_get_client, mock_time):
        from agenticops.tools.cloudwatch_tools import query_logs

        mock_time.sleep = MagicMock()
        client = MagicMock()
        client.start_query.return_value = {"queryId": "q-1"}
        client.get_query_results.return_value = {
            "status": "Complete",
            "results": [
                [
                    {"field": "@timestamp", "value": "2025-01-01T00:00:00"},
                    {"field": "@message", "value": "Error: timeout"},
                ]
            ],
        }
        mock_get_client.return_value = client

        result = query_logs(log_group="/aws/lambda/my-func", region="us-east-1")
        data = json.loads(result)
        assert len(data) == 1
        assert data[0]["@message"] == "Error: timeout"

    @patch("agenticops.tools.cloudwatch_tools.time_module")
    @patch("agenticops.tools.cloudwatch_tools._get_client")
    def test_query_logs_custom_query(self, mock_get_client, mock_time):
        from agenticops.tools.cloudwatch_tools import query_logs

        mock_time.sleep = MagicMock()
        client = MagicMock()
        client.start_query.return_value = {"queryId": "q-2"}
        client.get_query_results.return_value = {"status": "Complete", "results": []}
        mock_get_client.return_value = client

        result = query_logs(
            log_group="/aws/ecs/app",
            region="eu-west-1",
            query="fields @message | limit 10",
            hours=2,
        )
        data = json.loads(result)
        assert data == []

    @patch("agenticops.tools.cloudwatch_tools.time_module")
    @patch("agenticops.tools.cloudwatch_tools._get_client")
    def test_query_logs_timeout_status(self, mock_get_client, mock_time):
        from agenticops.tools.cloudwatch_tools import query_logs

        mock_time.sleep = MagicMock()
        client = MagicMock()
        client.start_query.return_value = {"queryId": "q-3"}
        # Always returns Running so we hit max_wait
        client.get_query_results.return_value = {"status": "Running"}
        mock_get_client.return_value = client

        result = query_logs(log_group="/test", region="us-east-1")
        assert "Log query finished with status: Running" in result

    @patch("agenticops.tools.cloudwatch_tools._get_client")
    def test_query_logs_client_error(self, mock_get_client):
        from agenticops.tools.cloudwatch_tools import query_logs

        client = MagicMock()
        client.start_query.side_effect = ClientError(
            {"Error": {"Code": "ResourceNotFoundException", "Message": "no group"}},
            "StartQuery",
        )
        mock_get_client.return_value = client

        result = query_logs(log_group="/nope", region="us-east-1")
        assert "Error querying logs" in result

    @patch("agenticops.tools.cloudwatch_tools._get_client")
    def test_query_logs_get_client_error(self, mock_get_client):
        from agenticops.tools.cloudwatch_tools import query_logs

        mock_get_client.side_effect = RuntimeError("no creds")
        result = query_logs(log_group="/x", region="us-east-1")
        assert "no creds" in result
