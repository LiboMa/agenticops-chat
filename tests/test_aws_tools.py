"""Tests for agenticops.tools.aws_tools — the @tool wrappers.

All AWS calls are mocked; no real credentials needed.
"""

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest


# ── Helpers ───────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _clear_session_cache():
    """Clear the module-level session cache before each test."""
    import agenticops.tools.aws_tools as mod
    mod._session_cache.clear()
    yield
    mod._session_cache.clear()


def _make_sts_response():
    return {
        "Credentials": {
            "AccessKeyId": "AKIAIOSFODNN7EXAMPLE",
            "SecretAccessKey": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
            "SessionToken": "FwoGZXIvYXdzE...",
            "Expiration": datetime(2026, 12, 31, tzinfo=timezone.utc),
        }
    }


def _inject_session(region="us-east-1", account_id="111111111111"):
    """Inject a mock session into the cache."""
    import agenticops.tools.aws_tools as mod
    session = MagicMock()
    mod._session_cache[f"{account_id}:{region}"] = session
    return session


# ── assume_role ───────────────────────────────────────────────────────

class TestAssumeRole:
    """Tests for assume_role using the provider abstraction layer.

    The function now resolves credentials via:
      get_db_session() → find matching CloudAccount → get_provider(account) →
      provider.resolve_credentials() → provider.sdk_session() → cache
    """

    @pytest.fixture(autouse=True)
    def _import(self):
        from agenticops.tools.aws_tools import assume_role
        self.fn = assume_role

    @patch("agenticops.models.get_db_session")
    @patch("agenticops.providers.get_provider")
    def test_assume_role_success(self, mock_get_provider, mock_get_db_session):
        """Successful assume_role resolves credentials and caches session."""
        # Set up DB to return a matching CloudAccount
        mock_account = MagicMock()
        mock_account.id = 1
        mock_account.name = "prod-account"
        mock_account.provider = "aws"
        mock_account.credentials = {"role_arn": "arn:aws:iam::111111111111:role/Test", "account_id": "111111111111"}
        mock_account.regions = ["us-east-1"]
        mock_account.labels = {}
        mock_account.is_enabled = True

        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.all.return_value = [mock_account]
        mock_get_db_session.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_get_db_session.return_value.__exit__ = MagicMock(return_value=False)

        # Set up provider to succeed
        mock_provider = MagicMock()
        mock_provider.resolve_credentials.return_value = True
        mock_provider.sdk_session.return_value = MagicMock()
        mock_get_provider.return_value = mock_provider

        result = self.fn(
            account_id="111111111111",
            role_arn="arn:aws:iam::111111111111:role/Test",
            region="us-east-1",
        )
        assert "Credentials resolved" in result or "cached" in result
        mock_provider.resolve_credentials.assert_called_once()
        mock_provider.sdk_session.assert_called_once()

    @patch("agenticops.models.get_db_session")
    @patch("agenticops.providers.get_provider")
    def test_assume_role_no_matching_account(self, mock_get_provider, mock_get_db_session):
        """Returns error message when no matching account found in DB."""
        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.all.return_value = []
        mock_get_db_session.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_get_db_session.return_value.__exit__ = MagicMock(return_value=False)

        result = self.fn(
            account_id="999999999999",
            role_arn="arn:aws:iam::999999999999:role/NonExistent",
            region="us-east-1",
        )
        assert "No enabled account found" in result
        mock_get_provider.assert_not_called()

    def test_assume_role_cached(self):
        """Second call with same account+region returns cached message without re-resolving."""
        # Pre-inject a session into cache
        _inject_session(region="us-east-1", account_id="111111111111")

        result = self.fn(
            account_id="111111111111",
            role_arn="arn:aws:iam::111111111111:role/Test",
            region="us-east-1",
        )
        assert "already cached" in result

    @patch("agenticops.models.get_db_session")
    @patch("agenticops.providers.get_provider")
    def test_assume_role_resolve_fails(self, mock_get_provider, mock_get_db_session):
        """Returns failure message when provider.resolve_credentials() returns False."""
        mock_account = MagicMock()
        mock_account.id = 2
        mock_account.name = "broken-account"
        mock_account.provider = "aws"
        mock_account.credentials = {"role_arn": "arn:aws:iam::333333333333:role/Broken"}
        mock_account.regions = ["us-west-2"]
        mock_account.labels = {}
        mock_account.is_enabled = True

        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.all.return_value = [mock_account]
        mock_get_db_session.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_get_db_session.return_value.__exit__ = MagicMock(return_value=False)

        mock_provider = MagicMock()
        mock_provider.resolve_credentials.return_value = False
        mock_get_provider.return_value = mock_provider

        result = self.fn(
            account_id="333333333333",
            role_arn="arn:aws:iam::333333333333:role/Broken",
            region="us-west-2",
        )
        assert "Failed to resolve credentials" in result


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
