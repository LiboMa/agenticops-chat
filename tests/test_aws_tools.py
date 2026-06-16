"""Tests for agenticops.tools.aws_tools — the @tool wrappers.

All AWS calls are mocked; no real credentials needed.
"""

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest


# ── Helpers ───────────────────────────────────────────────────────────

# Holds the snapshot the patched resolver returns as the single enabled account.
_DEFAULT_ACCOUNT = {"snap": None}


@pytest.fixture(autouse=True)
def _resolver_env(monkeypatch):
    """Clear the shared session cache and drive resolution to one mock account."""
    from types import SimpleNamespace
    import agenticops.tools.aws_tools as mod
    from agenticops.credentials import resolver

    mod._session_cache.clear()
    _DEFAULT_ACCOUNT["snap"] = None

    def _list_enabled(provider=""):
        snap = _DEFAULT_ACCOUNT["snap"]
        return [snap] if snap else []

    # Drive both resolution entry points off the single registered account.
    monkeypatch.setattr(resolver, "list_enabled_accounts", _list_enabled)
    yield
    mod._session_cache.clear()
    _DEFAULT_ACCOUNT["snap"] = None


def _inject_session(region="us-east-1", account_id="111111111111"):
    """Register a single enabled account and seed its cached session."""
    from types import SimpleNamespace
    import agenticops.tools.aws_tools as mod

    session = MagicMock()
    # resolve_account_session looks up {account_id}:{region} as a fallback key.
    mod._session_cache[f"{account_id}:{region}"] = session
    _DEFAULT_ACCOUNT["snap"] = SimpleNamespace(
        id=1, name="acct", provider="aws",
        credentials={"account_id": account_id}, regions=[region], labels={},
        credential_source_type="assume_role",
    )
    return session


# ── Internal helpers ──────────────────────────────────────────────────

class TestExtractItems:
    def test_simple_key(self):
        from agenticops.tools.aws_tools import _extract_items
        resp = {"Reservations": [{"a": 1}, {"b": 2}]}
        assert _extract_items(resp, "Reservations") == [{"a": 1}, {"b": 2}]

    def test_dotted_key(self):
        from agenticops.tools.aws_tools import _extract_items
        resp = {"TopicList": {"Topics": [{"arn": "x"}]}}
        assert _extract_items(resp, "TopicList.Topics") == [{"arn": "x"}]

    def test_missing_key_returns_empty(self):
        from agenticops.tools.aws_tools import _extract_items
        assert _extract_items({}, "Missing") == []

    def test_non_list_returns_empty(self):
        from agenticops.tools.aws_tools import _extract_items
        assert _extract_items({"Key": "string"}, "Key") == []


class TestFormatEc2Instance:
    def test_basic_format(self):
        from agenticops.tools.aws_tools import _format_ec2_instance
        instance = {
            "InstanceId": "i-123",
            "InstanceType": "t3.micro",
            "State": {"Name": "running"},
            "LaunchTime": datetime(2026, 1, 1, tzinfo=timezone.utc),
            "PrivateIpAddress": "10.0.0.1",
            "PublicIpAddress": "54.1.2.3",
            "VpcId": "vpc-abc",
            "SubnetId": "subnet-abc",
            "Tags": [{"Key": "Name", "Value": "web-1"}],
        }
        result = _format_ec2_instance(instance, "us-east-1")
        assert result["resource_id"] == "i-123"
        assert result["resource_name"] == "web-1"
        assert result["resource_type"] == "EC2"
        assert result["status"] == "running"
        assert result["metadata"]["instance_type"] == "t3.micro"
        assert result["tags"]["Name"] == "web-1"

    def test_no_tags(self):
        from agenticops.tools.aws_tools import _format_ec2_instance
        instance = {"InstanceId": "i-456", "State": {"Name": "stopped"}}
        result = _format_ec2_instance(instance, "us-west-2")
        assert result["resource_name"] is None
        assert result["tags"] == {}


class TestFormatResource:
    def test_basic_format(self):
        from agenticops.tools.aws_tools import _format_resource
        from agenticops.scan.services import AWS_SERVICES
        sdef = AWS_SERVICES["Lambda"]
        item = {
            "FunctionName": "my-func",
            "FunctionArn": "arn:aws:lambda:us-east-1:111:function:my-func",
            "Runtime": "python3.12",
            "MemorySize": 128,
        }
        result = _format_resource(item, sdef, "us-east-1")
        assert result["resource_type"] == "Lambda"
        assert result["resource_name"] == "my-func"


class TestFormatSimpleResource:
    def test_string_item(self):
        from agenticops.tools.aws_tools import _format_simple_resource
        from agenticops.scan.services import AWS_SERVICES
        sdef = AWS_SERVICES["EKS"]
        result = _format_simple_resource("my-cluster", sdef, "us-east-1")
        assert result["resource_id"] == "my-cluster"
        assert result["resource_type"] == "EKS"

    def test_arn_item(self):
        from agenticops.tools.aws_tools import _format_simple_resource
        from agenticops.scan.services import AWS_SERVICES
        sdef = AWS_SERVICES["ECS"]
        arn = "arn:aws:ecs:us-east-1:111:cluster/prod"
        result = _format_simple_resource(arn, sdef, "us-east-1")
        assert result["resource_arn"] == arn
        assert result["resource_name"] == "prod"


# ── Tool wrappers (mocked AWS calls) ─────────────────────────────────

class TestDescribeEc2:
    @pytest.fixture(autouse=True)
    def _import(self):
        from agenticops.tools.aws_tools import describe_ec2
        self.fn = describe_ec2

    def test_returns_instances(self):
        session = _inject_session()
        mock_client = MagicMock()
        session.client.return_value = mock_client
        mock_client.can_paginate.return_value = False
        mock_client.describe_instances.return_value = {
            "Reservations": [
                {"Instances": [
                    {"InstanceId": "i-001", "State": {"Name": "running"},
                     "InstanceType": "t3.micro", "Tags": [{"Key": "Name", "Value": "web"}]}
                ]}
            ]
        }
        result = json.loads(self.fn(region="us-east-1"))
        assert len(result) == 1
        assert result[0]["resource_id"] == "i-001"

    def test_error_handling(self):
        session = _inject_session()
        mock_client = MagicMock()
        session.client.return_value = mock_client
        mock_client.can_paginate.return_value = False
        mock_client.describe_instances.side_effect = Exception("boom")
        result = self.fn(region="us-east-1")
        assert "Error" in result

    def test_no_session_error(self):
        result = self.fn(region="eu-west-1")
        assert "Error" in result


class TestListLambdaFunctions:
    @pytest.fixture(autouse=True)
    def _import(self):
        from agenticops.tools.aws_tools import list_lambda_functions
        self.fn = list_lambda_functions

    def test_returns_functions(self):
        session = _inject_session()
        mock_client = MagicMock()
        session.client.return_value = mock_client
        mock_client.can_paginate.return_value = False
        mock_client.list_functions.return_value = {
            "Functions": [
                {"FunctionName": "fn1", "FunctionArn": "arn:aws:lambda:us-east-1:111:function:fn1",
                 "Runtime": "python3.12"}
            ]
        }
        result = json.loads(self.fn(region="us-east-1"))
        assert len(result) == 1
        assert result[0]["resource_name"] == "fn1"


class TestListSqs:
    @pytest.fixture(autouse=True)
    def _import(self):
        from agenticops.tools.aws_tools import list_sqs
        self.fn = list_sqs

    def test_returns_queues(self):
        session = _inject_session()
        mock_client = MagicMock()
        session.client.return_value = mock_client
        mock_client.can_paginate.return_value = False
        mock_client.list_queues.return_value = {
            "QueueUrls": [
                "https://sqs.us-east-1.amazonaws.com/111/my-queue"
            ]
        }
        result = json.loads(self.fn(region="us-east-1"))
        assert len(result) == 1
        assert result[0]["resource_name"] == "my-queue"
        assert result[0]["status"] == "available"


class TestDescribeRds:
    @pytest.fixture(autouse=True)
    def _import(self):
        from agenticops.tools.aws_tools import describe_rds
        self.fn = describe_rds

    def test_returns_instances(self):
        session = _inject_session()
        mock_client = MagicMock()
        session.client.return_value = mock_client
        mock_client.can_paginate.return_value = False
        mock_client.describe_db_instances.return_value = {
            "DBInstances": [
                {"DBInstanceIdentifier": "mydb", "DBInstanceArn": "arn:aws:rds:us-east-1:111:db:mydb",
                 "Engine": "postgres", "DBInstanceStatus": "available"}
            ]
        }
        result = json.loads(self.fn(region="us-east-1"))
        assert len(result) == 1
        assert result[0]["resource_id"] == "mydb"


class TestListS3Buckets:
    @pytest.fixture(autouse=True)
    def _import(self):
        from agenticops.tools.aws_tools import list_s3_buckets
        self.fn = list_s3_buckets

    def test_returns_buckets(self):
        session = _inject_session()
        mock_client = MagicMock()
        session.client.return_value = mock_client
        mock_client.can_paginate.return_value = False
        mock_client.list_buckets.return_value = {
            "Buckets": [
                {"Name": "my-bucket", "CreationDate": datetime(2026, 1, 1, tzinfo=timezone.utc)}
            ]
        }
        result = json.loads(self.fn(region="us-east-1"))
        assert len(result) == 1
        assert result[0]["resource_name"] == "my-bucket"


class TestDescribeEcs:
    @pytest.fixture(autouse=True)
    def _import(self):
        from agenticops.tools.aws_tools import describe_ecs
        self.fn = describe_ecs

    def test_returns_clusters(self):
        session = _inject_session()
        mock_client = MagicMock()
        session.client.return_value = mock_client
        mock_client.can_paginate.return_value = False
        mock_client.list_clusters.return_value = {
            "clusterArns": ["arn:aws:ecs:us-east-1:111:cluster/prod"]
        }
        result = json.loads(self.fn(region="us-east-1"))
        assert len(result) == 1
        assert result[0]["resource_name"] == "prod"


class TestDescribeEks:
    @pytest.fixture(autouse=True)
    def _import(self):
        from agenticops.tools.aws_tools import describe_eks
        self.fn = describe_eks

    def test_returns_clusters(self):
        session = _inject_session()
        mock_client = MagicMock()
        session.client.return_value = mock_client
        mock_client.can_paginate.return_value = False
        mock_client.list_clusters.return_value = {
            "clusters": ["my-eks-cluster"]
        }
        result = json.loads(self.fn(region="us-east-1"))
        assert len(result) == 1
        assert result[0]["resource_id"] == "my-eks-cluster"


class TestListDynamodb:
    @pytest.fixture(autouse=True)
    def _import(self):
        from agenticops.tools.aws_tools import list_dynamodb
        self.fn = list_dynamodb

    def test_returns_tables(self):
        session = _inject_session()
        mock_client = MagicMock()
        session.client.return_value = mock_client
        mock_client.can_paginate.return_value = False
        mock_client.list_tables.return_value = {
            "TableNames": ["users", "orders"]
        }
        result = json.loads(self.fn(region="us-east-1"))
        assert len(result) == 2


class TestListSns:
    @pytest.fixture(autouse=True)
    def _import(self):
        from agenticops.tools.aws_tools import list_sns
        self.fn = list_sns

    def test_returns_topics(self):
        session = _inject_session()
        mock_client = MagicMock()
        session.client.return_value = mock_client
        mock_client.can_paginate.return_value = False
        mock_client.list_topics.return_value = {
            "Topics": [{"TopicArn": "arn:aws:sns:us-east-1:111:alerts"}]
        }
        result = json.loads(self.fn(region="us-east-1"))
        assert len(result) == 1
