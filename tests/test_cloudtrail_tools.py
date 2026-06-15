"""Tests for cloudtrail_tools module - improving coverage from 32% to ~90%+."""

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from agenticops.tools.cloudtrail_tools import lookup_cloudtrail_events


class TestLookupCloudtrailEvents:
    """Tests for lookup_cloudtrail_events tool."""

    @patch("agenticops.tools.cloudtrail_tools._get_client")
    def test_returns_events_successfully(self, mock_get_client):
        """Should return formatted events when CloudTrail has results."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        cloud_trail_event = json.dumps({
            "sourceIPAddress": "10.0.0.1",
            "userAgent": "console.amazonaws.com",
            "eventSource": "ec2.amazonaws.com",
            "errorCode": None,
            "errorMessage": "",
        })

        mock_client.lookup_events.return_value = {
            "Events": [
                {
                    "EventName": "StopInstances",
                    "EventTime": datetime(2026, 6, 15, 3, 0, 0, tzinfo=timezone.utc),
                    "Username": "admin-user",
                    "CloudTrailEvent": cloud_trail_event,
                    "Resources": [
                        {"ResourceType": "AWS::EC2::Instance", "ResourceName": "i-abc123"}
                    ],
                }
            ]
        }

        result = lookup_cloudtrail_events(
            resource_id="i-abc123", region="us-east-1", hours=2
        )

        events = json.loads(result)
        assert len(events) == 1
        assert events[0]["event_name"] == "StopInstances"
        assert events[0]["username"] == "admin-user"
        assert events[0]["source_ip"] == "10.0.0.1"
        assert events[0]["event_source"] == "ec2.amazonaws.com"
        assert events[0]["resources"][0]["type"] == "AWS::EC2::Instance"

    @patch("agenticops.tools.cloudtrail_tools._get_client")
    def test_no_events_found(self, mock_get_client):
        """Should return informative message when no events found."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.lookup_events.return_value = {"Events": []}

        result = lookup_cloudtrail_events(
            resource_id="i-missing", region="us-west-2", hours=4
        )

        assert "No CloudTrail events found" in result
        assert "i-missing" in result
        assert "us-west-2" in result
        assert "4h" in result

    @patch("agenticops.tools.cloudtrail_tools._get_client")
    def test_client_error_handling(self, mock_get_client):
        """Should handle ClientError gracefully."""
        from botocore.exceptions import ClientError

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.lookup_events.side_effect = ClientError(
            {"Error": {"Code": "AccessDeniedException", "Message": "Not authorized"}},
            "LookupEvents",
        )

        result = lookup_cloudtrail_events(
            resource_id="i-abc123", region="us-east-1", hours=2
        )

        assert "Error looking up CloudTrail events" in result
        assert "i-abc123" in result

    @patch("agenticops.tools.cloudtrail_tools._get_client")
    def test_get_client_runtime_error(self, mock_get_client):
        """Should handle RuntimeError from _get_client (no credentials)."""
        mock_get_client.side_effect = RuntimeError("AWS credentials not configured")

        result = lookup_cloudtrail_events(
            resource_id="i-abc123", region="us-east-1", hours=2
        )

        assert "AWS credentials not configured" in result

    @patch("agenticops.tools.cloudtrail_tools._get_client")
    def test_malformed_cloudtrail_event_json(self, mock_get_client):
        """Should handle malformed CloudTrailEvent JSON gracefully."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_client.lookup_events.return_value = {
            "Events": [
                {
                    "EventName": "TerminateInstances",
                    "EventTime": datetime(2026, 6, 15, 2, 0, 0, tzinfo=timezone.utc),
                    "Username": "root",
                    "CloudTrailEvent": "not-valid-json{{{",
                    "Resources": [],
                }
            ]
        }

        result = lookup_cloudtrail_events(
            resource_id="i-abc123", region="eu-west-1", hours=1
        )

        events = json.loads(result)
        assert len(events) == 1
        assert events[0]["event_name"] == "TerminateInstances"
        assert events[0]["source_ip"] is None

    @patch("agenticops.tools.cloudtrail_tools._get_client")
    def test_hours_capped_at_24(self, mock_get_client):
        """Should cap hours at 24 even if larger value passed."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.lookup_events.return_value = {"Events": []}

        lookup_cloudtrail_events(
            resource_id="i-abc123", region="us-east-1", hours=100
        )

        call_kwargs = mock_client.lookup_events.call_args[1]
        time_diff = call_kwargs["EndTime"] - call_kwargs["StartTime"]
        assert time_diff.total_seconds() == 24 * 3600

    @patch("agenticops.tools.cloudtrail_tools._get_client")
    def test_long_user_agent_truncated(self, mock_get_client):
        """Should truncate user_agent to 100 chars."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        long_agent = "x" * 200
        cloud_trail_event = json.dumps({
            "sourceIPAddress": "1.2.3.4",
            "userAgent": long_agent,
            "eventSource": "s3.amazonaws.com",
        })

        mock_client.lookup_events.return_value = {
            "Events": [
                {
                    "EventName": "PutObject",
                    "EventTime": datetime(2026, 6, 15, 1, 0, 0, tzinfo=timezone.utc),
                    "Username": "svc-account",
                    "CloudTrailEvent": cloud_trail_event,
                    "Resources": [],
                }
            ]
        }

        result = lookup_cloudtrail_events(
            resource_id="my-bucket", region="us-east-1", hours=2
        )

        events = json.loads(result)
        assert len(events[0]["user_agent"]) == 100

    @patch("agenticops.tools.cloudtrail_tools._get_client")
    def test_error_fields_in_event(self, mock_get_client):
        """Should include error_code and error_message when present."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        cloud_trail_event = json.dumps({
            "sourceIPAddress": "192.168.1.1",
            "userAgent": "aws-cli/2.0",
            "eventSource": "ec2.amazonaws.com",
            "errorCode": "UnauthorizedOperation",
            "errorMessage": "You are not authorized to perform this operation." * 5,
        })

        mock_client.lookup_events.return_value = {
            "Events": [
                {
                    "EventName": "RunInstances",
                    "EventTime": datetime(2026, 6, 15, 0, 30, 0, tzinfo=timezone.utc),
                    "Username": "hacker",
                    "CloudTrailEvent": cloud_trail_event,
                    "Resources": [],
                }
            ]
        }

        result = lookup_cloudtrail_events(
            resource_id="i-target", region="ap-southeast-1", hours=1
        )

        events = json.loads(result)
        assert events[0]["error_code"] == "UnauthorizedOperation"
        assert len(events[0]["error_message"]) <= 200
