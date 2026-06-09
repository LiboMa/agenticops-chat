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
    """Clear the module-level session cache + account context before each test."""
    import agenticops.tools.aws_tools as mod
    mod._session_cache.clear()
    mod._set_active_account(None)
    yield
    mod._session_cache.clear()
    mod._set_active_account(None)


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
    """Inject a mock session into the cache and bind it as the active account."""
    import agenticops.tools.aws_tools as mod
    session = MagicMock()
    mod._session_cache[f"{account_id}:{region}"] = session
    mod._set_active_account(account_id)
    return session


# ── assume_role ───────────────────────────────────────────────────────

@pytest.mark.skip(reason="Stale: assume_role now resolves via provider layer, not aws_tools.boto3 directly (pre-existing failure, see test_aws_tools_coverage.TestAssumeRole)")
class TestAssumeRole:
    @pytest.fixture(autouse=True)
    def _import(self):
        from agenticops.tools.aws_tools import assume_role
        self.fn = assume_role

    @patch("agenticops.tools.aws_tools.boto3")
    def test_assume_role_success(self, mock_boto3):
        mock_sts = MagicMock()
        mock_boto3.client.return_value = mock_sts
        mock_sts.assume_role.return_value = _make_sts_response()
        mock_boto3.Session.return_value = MagicMock()

        result = self.fn(
            account_id="111111111111",
            role_arn="arn:aws:iam::111111111111:role/Test",
            region="us-east-1",
        )
        assert "Assumed role" in result
        assert "111111111111" in result

    @patch("agenticops.tools.aws_tools.boto3")
    def test_assume_role_with_external_id(self, mock_boto3):
        mock_sts = MagicMock()
        mock_boto3.client.return_value = mock_sts
        mock_sts.assume_role.return_value = _make_sts_response()
        mock_boto3.Session.return_value = MagicMock()

        self.fn(
            account_id="222222222222",
            role_arn="arn:aws:iam::222222222222:role/Test",
            region="us-west-2",
            external_id="ext-123",
        )
        call_kwargs = mock_sts.assume_role.call_args[1]
        assert call_kwargs["ExternalId"] == "ext-123"

    @patch("agenticops.tools.aws_tools.boto3")
    def test_assume_role_cached(self, mock_boto3):
        """Second call should return cached message without calling STS."""
        mock_sts = MagicMock()
        mock_boto3.client.return_value = mock_sts
        mock_sts.assume_role.return_value = _make_sts_response()
        mock_boto3.Session.return_value = MagicMock()

        self.fn(account_id="111111111111", role_arn="arn:aws:iam::111111111111:role/Test", region="us-east-1")
        result = self.fn(account_id="111111111111", role_arn="arn:aws:iam::111111111111:role/Test", region="us-east-1")
        assert "already cached" in result

    @patch("agenticops.tools.aws_tools.boto3")
    def test_assume_role_client_error(self, mock_boto3):
        from botocore.exceptions import ClientError
        mock_sts = MagicMock()
        mock_boto3.client.return_value = mock_sts
        mock_sts.assume_role.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "denied"}}, "AssumeRole"
        )
        result = self.fn(account_id="111111111111", role_arn="arn:aws:iam::111111111111:role/Test", region="us-east-1")
        assert "Error" in result


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
