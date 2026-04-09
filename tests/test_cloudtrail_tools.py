"""Tests for agenticops.tools.cloudtrail_tools — cover lookup_cloudtrail_events."""

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError


class TestLookupCloudtrailEvents:
    """Cover lines 35-86 of cloudtrail_tools.py."""

    @patch("agenticops.tools.cloudtrail_tools._get_client")
    def test_basic_lookup_returns_events(self, mock_get_client):
        from agenticops.tools.cloudtrail_tools import lookup_cloudtrail_events

        cloud_trail_event = json.dumps({
            "sourceIPAddress": "203.0.113.1",
            "userAgent": "console.amazonaws.com",
            "eventSource": "ec2.amazonaws.com",
            "errorCode": None,
            "errorMessage": "",
        })

        client = MagicMock()
        client.lookup_events.return_value = {
            "Events": [
                {
                    "EventName": "StopInstances",
                    "EventTime": datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc),
                    "Username": "admin",
                    "CloudTrailEvent": cloud_trail_event,
                    "Resources": [
                        {"ResourceType": "AWS::EC2::Instance", "ResourceName": "i-abc123"}
                    ],
                }
            ]
        }
        mock_get_client.return_value = client

        result = lookup_cloudtrail_events(
            resource_id="i-abc123", region="us-east-1", hours=2
        )
        events = json.loads(result)
        assert len(events) == 1
        assert events[0]["event_name"] == "StopInstances"
        assert events[0]["username"] == "admin"
        assert events[0]["source_ip"] == "203.0.113.1"
        assert events[0]["resources"][0]["type"] == "AWS::EC2::Instance"

    @patch("agenticops.tools.cloudtrail_tools._get_client")
    def test_no_events_found(self, mock_get_client):
        from agenticops.tools.cloudtrail_tools import lookup_cloudtrail_events

        client = MagicMock()
        client.lookup_events.return_value = {"Events": []}
        mock_get_client.return_value = client

        result = lookup_cloudtrail_events(
            resource_id="i-missing", region="us-west-2", hours=4
        )
        assert "No CloudTrail events found" in result
        assert "i-missing" in result
        assert "us-west-2" in result

    @patch("agenticops.tools.cloudtrail_tools._get_client")
    def test_client_error_handled(self, mock_get_client):
        from agenticops.tools.cloudtrail_tools import lookup_cloudtrail_events

        client = MagicMock()
        client.lookup_events.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "Not authorized"}},
            "LookupEvents",
        )
        mock_get_client.return_value = client

        result = lookup_cloudtrail_events(
            resource_id="i-abc123", region="eu-west-1", hours=1
        )
        assert "Error looking up CloudTrail events" in result

    @patch("agenticops.tools.cloudtrail_tools._get_client")
    def test_get_client_runtime_error(self, mock_get_client):
        from agenticops.tools.cloudtrail_tools import lookup_cloudtrail_events

        mock_get_client.side_effect = RuntimeError("No credentials")

        result = lookup_cloudtrail_events(
            resource_id="i-abc123", region="us-east-1", hours=2
        )
        assert "No credentials" in result

    @patch("agenticops.tools.cloudtrail_tools._get_client")
    def test_malformed_cloudtrail_event_json(self, mock_get_client):
        """Cover the JSONDecodeError except branch."""
        from agenticops.tools.cloudtrail_tools import lookup_cloudtrail_events

        client = MagicMock()
        client.lookup_events.return_value = {
            "Events": [
                {
                    "EventName": "RunInstances",
                    "EventTime": datetime(2025, 6, 1, tzinfo=timezone.utc),
                    "Username": "dev",
                    "CloudTrailEvent": "NOT-VALID-JSON{{{",
                    "Resources": [],
                }
            ]
        }
        mock_get_client.return_value = client

        result = lookup_cloudtrail_events(
            resource_id="i-abc123", region="us-east-1", hours=2
        )
        events = json.loads(result)
        assert len(events) == 1
        assert events[0]["event_name"] == "RunInstances"
        # source_ip should be None since JSON parse failed
        assert events[0]["source_ip"] is None

    @patch("agenticops.tools.cloudtrail_tools._get_client")
    def test_hours_capped_at_24(self, mock_get_client):
        from agenticops.tools.cloudtrail_tools import lookup_cloudtrail_events

        client = MagicMock()
        client.lookup_events.return_value = {"Events": []}
        mock_get_client.return_value = client

        result = lookup_cloudtrail_events(
            resource_id="i-abc123", region="us-east-1", hours=100
        )
        # Verify it ran without error (hours capped internally to 24)
        assert "No CloudTrail events found" in result

    @patch("agenticops.tools.cloudtrail_tools._get_client")
    def test_event_with_error_code(self, mock_get_client):
        from agenticops.tools.cloudtrail_tools import lookup_cloudtrail_events

        cloud_trail_event = json.dumps({
            "sourceIPAddress": "10.0.0.1",
            "userAgent": "aws-cli/2.0" * 20,  # long user agent gets truncated
            "eventSource": "iam.amazonaws.com",
            "errorCode": "UnauthorizedAccess",
            "errorMessage": "User is not authorized to perform this action" * 5,
        })

        client = MagicMock()
        client.lookup_events.return_value = {
            "Events": [
                {
                    "EventName": "CreateRole",
                    "EventTime": datetime(2025, 6, 1, tzinfo=timezone.utc),
                    "Username": "hacker",
                    "CloudTrailEvent": cloud_trail_event,
                    "Resources": [
                        {"ResourceType": "AWS::IAM::Role", "ResourceName": "bad-role"},
                        {"ResourceType": "AWS::IAM::Policy", "ResourceName": "bad-policy"},
                    ],
                }
            ]
        }
        mock_get_client.return_value = client

        result = lookup_cloudtrail_events(
            resource_id="bad-role", region="us-east-1", hours=2
        )
        events = json.loads(result)
        assert events[0]["error_code"] == "UnauthorizedAccess"
        # user_agent truncated to 100 chars
        assert len(events[0]["user_agent"]) <= 100
        # error_message truncated to 200 chars
        assert len(events[0]["error_message"]) <= 200
        # Multiple resources
        assert len(events[0]["resources"]) == 2

    @patch("agenticops.tools.cloudtrail_tools._get_client")
    def test_missing_optional_fields(self, mock_get_client):
        """Event with minimal fields — no CloudTrailEvent, no Resources."""
        from agenticops.tools.cloudtrail_tools import lookup_cloudtrail_events

        client = MagicMock()
        client.lookup_events.return_value = {
            "Events": [
                {
                    "EventName": "DescribeInstances",
                }
            ]
        }
        mock_get_client.return_value = client

        result = lookup_cloudtrail_events(
            resource_id="i-abc123", region="us-east-1", hours=1
        )
        events = json.loads(result)
        assert len(events) == 1
        assert events[0]["event_name"] == "DescribeInstances"
        assert events[0]["username"] is None
        assert events[0]["resources"] == []
