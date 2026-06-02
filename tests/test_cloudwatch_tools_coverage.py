"""Unit tests for agenticops.tools.cloudwatch_tools module.

Covers: list_alarms, get_alarm_history, get_metrics, query_logs.
"""

import json
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

import pytest

from agenticops.tools.cloudwatch_tools import (
    list_alarms,
    get_alarm_history,
    get_metrics,
    query_logs,
)


# ── list_alarms tests ────────────────────────────────────────────────


class TestListAlarms:
    def _call(self, **kwargs):
        return list_alarms._tool_func(**kwargs)

    @patch("agenticops.tools.cloudwatch_tools._get_client")
    def test_list_all_alarms(self, mock_get_client):
        mock_cw = MagicMock()
        mock_get_client.return_value = mock_cw
        mock_paginator = MagicMock()
        mock_cw.get_paginator.return_value = mock_paginator
        mock_paginator.paginate.return_value = [{
            "MetricAlarms": [{
                "AlarmName": "HighCPU",
                "StateValue": "ALARM",
                "MetricName": "CPUUtilization",
                "Namespace": "AWS/EC2",
                "Dimensions": [{"Name": "InstanceId", "Value": "i-123"}],
                "Threshold": 80.0,
                "ComparisonOperator": "GreaterThanThreshold",
                "StateReason": "Threshold crossed",
                "StateUpdatedTimestamp": "2026-05-27T05:00:00Z",
            }]
        }]

        result = self._call(region="us-east-1")
        alarms = json.loads(result)
        assert len(alarms) == 1
        assert alarms[0]["alarm_name"] == "HighCPU"
        assert alarms[0]["state"] == "ALARM"
        assert alarms[0]["dimensions"] == {"InstanceId": "i-123"}

    @patch("agenticops.tools.cloudwatch_tools._get_client")
    def test_filter_by_state(self, mock_get_client):
        mock_cw = MagicMock()
        mock_get_client.return_value = mock_cw
        mock_paginator = MagicMock()
        mock_cw.get_paginator.return_value = mock_paginator
        mock_paginator.paginate.return_value = [{"MetricAlarms": []}]

        self._call(region="us-east-1", state="ALARM")
        mock_paginator.paginate.assert_called_with(StateValue="ALARM")

    @patch("agenticops.tools.cloudwatch_tools._get_client")
    def test_filter_by_resource_type(self, mock_get_client):
        mock_cw = MagicMock()
        mock_get_client.return_value = mock_cw
        mock_paginator = MagicMock()
        mock_cw.get_paginator.return_value = mock_paginator
        mock_paginator.paginate.return_value = [{
            "MetricAlarms": [
                {"AlarmName": "A1", "StateValue": "OK", "Namespace": "AWS/EC2",
                 "Dimensions": [], "MetricName": "CPUUtilization"},
                {"AlarmName": "A2", "StateValue": "OK", "Namespace": "AWS/RDS",
                 "Dimensions": [], "MetricName": "FreeableMemory"},
            ]
        }]

        result = self._call(region="us-east-1", resource_type="AWS/EC2")
        alarms = json.loads(result)
        assert len(alarms) == 1
        assert alarms[0]["alarm_name"] == "A1"

    @patch("agenticops.tools.cloudwatch_tools._get_client")
    def test_client_error(self, mock_get_client):
        from botocore.exceptions import ClientError
        mock_cw = MagicMock()
        mock_get_client.return_value = mock_cw
        mock_paginator = MagicMock()
        mock_cw.get_paginator.return_value = mock_paginator
        mock_paginator.paginate.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "no access"}}, "DescribeAlarms"
        )

        result = self._call(region="us-east-1")
        assert "Error listing alarms" in result

    @patch("agenticops.tools.cloudwatch_tools._get_client")
    def test_runtime_error_from_get_client(self, mock_get_client):
        mock_get_client.side_effect = RuntimeError("No session")
        result = self._call(region="us-east-1")
        assert "No session" in result


# ── get_alarm_history tests ──────────────────────────────────────────


class TestGetAlarmHistory:
    def _call(self, **kwargs):
        return get_alarm_history._tool_func(**kwargs)

    @patch("agenticops.tools.cloudwatch_tools._get_client")
    def test_returns_history(self, mock_get_client):
        mock_cw = MagicMock()
        mock_get_client.return_value = mock_cw
        mock_cw.describe_alarm_history.return_value = {
            "AlarmHistoryItems": [
                {
                    "Timestamp": "2026-05-27T04:00:00Z",
                    "HistoryItemType": "StateUpdate",
                    "HistorySummary": "OK to ALARM",
                },
                {
                    "Timestamp": "2026-05-27T03:00:00Z",
                    "HistoryItemType": "StateUpdate",
                    "HistorySummary": "ALARM to OK",
                },
            ]
        }

        result = self._call(alarm_name="HighCPU", region="us-east-1")
        history = json.loads(result)
        assert len(history) == 2
        assert history[0]["summary"] == "OK to ALARM"

    @patch("agenticops.tools.cloudwatch_tools._get_client")
    def test_empty_history(self, mock_get_client):
        mock_cw = MagicMock()
        mock_get_client.return_value = mock_cw
        mock_cw.describe_alarm_history.return_value = {"AlarmHistoryItems": []}

        result = self._call(alarm_name="NeverFired", region="us-east-1")
        history = json.loads(result)
        assert history == []

    @patch("agenticops.tools.cloudwatch_tools._get_client")
    def test_client_error(self, mock_get_client):
        from botocore.exceptions import ClientError
        mock_cw = MagicMock()
        mock_get_client.return_value = mock_cw
        mock_cw.describe_alarm_history.side_effect = ClientError(
            {"Error": {"Code": "ResourceNotFound", "Message": "not found"}}, "DescribeAlarmHistory"
        )

        result = self._call(alarm_name="Missing", region="us-east-1")
        assert "Error getting alarm history" in result

    @patch("agenticops.tools.cloudwatch_tools._get_client")
    def test_hours_capped_at_168(self, mock_get_client):
        mock_cw = MagicMock()
        mock_get_client.return_value = mock_cw
        mock_cw.describe_alarm_history.return_value = {"AlarmHistoryItems": []}

        self._call(alarm_name="Test", region="us-east-1", hours=500)
        call_args = mock_cw.describe_alarm_history.call_args
        start_time = call_args[1]["StartDate"]
        end_time = call_args[1]["EndDate"]
        diff = end_time - start_time
        assert diff <= timedelta(hours=169)  # max 168 with small timing tolerance


# ── get_metrics tests ────────────────────────────────────────────────


class TestGetMetrics:
    def _call(self, **kwargs):
        return get_metrics._tool_func(**kwargs)

    @patch("agenticops.tools.cloudwatch_tools._get_client")
    def test_ec2_default_metrics(self, mock_get_client):
        mock_cw = MagicMock()
        mock_get_client.return_value = mock_cw
        mock_cw.get_metric_data.return_value = {
            "MetricDataResults": [{
                "Timestamps": [datetime(2026, 5, 27, 5, 0, tzinfo=timezone.utc)],
                "Values": [45.1234],
            }]
        }

        result = self._call(resource_id="i-123", resource_type="EC2", region="us-east-1")
        data = json.loads(result)
        # Should have fetched default metrics for EC2
        assert isinstance(data, dict)

    @patch("agenticops.tools.cloudwatch_tools._get_client")
    def test_custom_metric_names(self, mock_get_client):
        mock_cw = MagicMock()
        mock_get_client.return_value = mock_cw
        mock_cw.get_metric_data.return_value = {
            "MetricDataResults": [{
                "Timestamps": [],
                "Values": [],
            }]
        }

        result = self._call(
            resource_id="i-123", resource_type="EC2", region="us-east-1",
            metric_names="CPUUtilization,NetworkIn"
        )
        data = json.loads(result)
        assert "CPUUtilization" in data
        assert "NetworkIn" in data

    @patch("agenticops.tools.cloudwatch_tools._get_client")
    def test_unknown_resource_type(self, mock_get_client):
        mock_cw = MagicMock()
        mock_get_client.return_value = mock_cw
        result = self._call(resource_id="x", resource_type="UnknownService", region="us-east-1")
        assert "No CloudWatch metrics defined" in result

    @patch("agenticops.tools.cloudwatch_tools._get_client")
    def test_client_error_per_metric(self, mock_get_client):
        from botocore.exceptions import ClientError
        mock_cw = MagicMock()
        mock_get_client.return_value = mock_cw
        mock_cw.get_metric_data.side_effect = ClientError(
            {"Error": {"Code": "InvalidParameterValue", "Message": "bad"}}, "GetMetricData"
        )

        result = self._call(
            resource_id="i-123", resource_type="EC2", region="us-east-1",
            metric_names="CPUUtilization"
        )
        data = json.loads(result)
        assert "error" in str(data.get("CPUUtilization", [{}])[0])

    @patch("agenticops.tools.cloudwatch_tools._get_client")
    def test_sqs_dimension_splits_queue_name(self, mock_get_client):
        mock_cw = MagicMock()
        mock_get_client.return_value = mock_cw
        mock_cw.get_metric_data.return_value = {
            "MetricDataResults": [{"Timestamps": [], "Values": []}]
        }

        self._call(
            resource_id="https://sqs.us-east-1.amazonaws.com/123/my-queue",
            resource_type="SQS",
            region="us-east-1",
            metric_names="NumberOfMessagesSent",
        )
        call_args = mock_cw.get_metric_data.call_args
        query = call_args[1]["MetricDataQueries"][0]
        dims = query["MetricStat"]["Metric"]["Dimensions"]
        assert dims[0]["Value"] == "my-queue"


# ── query_logs tests ─────────────────────────────────────────────────


class TestQueryLogs:
    def _call(self, **kwargs):
        return query_logs._tool_func(**kwargs)

    @patch("agenticops.tools.cloudwatch_tools.time_module.sleep")
    @patch("agenticops.tools.cloudwatch_tools._get_client")
    def test_successful_query(self, mock_get_client, mock_sleep):
        mock_logs = MagicMock()
        mock_get_client.return_value = mock_logs
        mock_logs.start_query.return_value = {"queryId": "q-123"}
        mock_logs.get_query_results.return_value = {
            "status": "Complete",
            "results": [
                [
                    {"field": "@timestamp", "value": "2026-05-27T05:00:00Z"},
                    {"field": "@message", "value": "ERROR: connection refused"},
                ]
            ],
        }

        result = self._call(log_group="/aws/lambda/my-func", region="us-east-1")
        entries = json.loads(result)
        assert len(entries) == 1
        assert "ERROR" in entries[0]["@message"]

    @patch("agenticops.tools.cloudwatch_tools.time_module.sleep")
    @patch("agenticops.tools.cloudwatch_tools._get_client")
    def test_custom_query(self, mock_get_client, mock_sleep):
        mock_logs = MagicMock()
        mock_get_client.return_value = mock_logs
        mock_logs.start_query.return_value = {"queryId": "q-456"}
        mock_logs.get_query_results.return_value = {
            "status": "Complete",
            "results": [],
        }

        result = self._call(
            log_group="/my/log-group", region="us-east-1",
            query="fields @message | limit 10"
        )
        entries = json.loads(result)
        assert entries == []

    @patch("agenticops.tools.cloudwatch_tools.time_module.sleep")
    @patch("agenticops.tools.cloudwatch_tools._get_client")
    def test_query_timeout(self, mock_get_client, mock_sleep):
        mock_logs = MagicMock()
        mock_get_client.return_value = mock_logs
        mock_logs.start_query.return_value = {"queryId": "q-slow"}
        mock_logs.get_query_results.return_value = {"status": "Running"}

        result = self._call(log_group="/my/log", region="us-east-1")
        assert "Running" in result

    @patch("agenticops.tools.cloudwatch_tools._get_client")
    def test_client_error(self, mock_get_client):
        from botocore.exceptions import ClientError
        mock_logs = MagicMock()
        mock_get_client.return_value = mock_logs
        mock_logs.start_query.side_effect = ClientError(
            {"Error": {"Code": "ResourceNotFoundException", "Message": "no group"}}, "StartQuery"
        )

        result = self._call(log_group="/missing/group", region="us-east-1")
        assert "Error querying logs" in result

    @patch("agenticops.tools.cloudwatch_tools._get_client")
    def test_runtime_error_from_get_client(self, mock_get_client):
        mock_get_client.side_effect = RuntimeError("No session")
        result = self._call(log_group="/x", region="us-east-1")
        assert "No session" in result
