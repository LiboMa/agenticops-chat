"""Tests for agenticops.tools.aws_tools — targeting uncovered lines."""

import json
from unittest.mock import MagicMock, patch

import pytest

from agenticops.tools.aws_tools import (
    _session_cache,
    _get_session,
    _get_client,
    _extract_items,
    _format_ec2_instance,
    _scan_service_generic,
    _format_resource,
    _format_simple_resource,
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
from agenticops.scan.services import AWSServiceDef


# ---------------------------------------------------------------------------
# Setup / teardown
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_session_cache():
    """Clear the module-level session cache between tests."""
    _session_cache.clear()
    yield
    _session_cache.clear()


# ---------------------------------------------------------------------------
# assume_role
# ---------------------------------------------------------------------------


class TestAssumeRole:
    def test_already_cached(self):
        """Returns immediately if session already cached."""
        _session_cache["123456789:us-east-1"] = MagicMock()
        result = assume_role(
            account_id="123456789",
            role_arn="arn:aws:iam::123456789:role/Test",
            region="us-east-1",
        )
        assert "already cached" in result

    @patch("boto3.client")
    @patch("boto3.Session")
    def test_successful_assume(self, mock_session_cls, mock_client_fn):
        """Successful role assumption caches session."""
        mock_sts = MagicMock()
        mock_sts.assume_role.return_value = {
            "Credentials": {
                "AccessKeyId": "AKIA...",
                "SecretAccessKey": "secret",
                "SessionToken": "token",
            }
        }
        mock_client_fn.return_value = mock_sts

        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session

        result = assume_role(
            account_id="111222333",
            role_arn="arn:aws:iam::111222333:role/AgenticOps",
            region="us-west-2",
            external_id="ext-123",
        )
        assert "Assumed role" in result
        assert "111222333:us-west-2" in _session_cache

    @patch("boto3.client")
    def test_client_error(self, mock_client_fn):
        """ClientError returns error message."""
        from botocore.exceptions import ClientError

        mock_sts = MagicMock()
        mock_sts.assume_role.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "denied"}},
            "AssumeRole",
        )
        mock_client_fn.return_value = mock_sts

        result = assume_role(
            account_id="999",
            role_arn="arn:aws:iam::999:role/Bad",
            region="eu-west-1",
        )
        assert "Error assuming role" in result


# ---------------------------------------------------------------------------
# _get_session / _get_client
# ---------------------------------------------------------------------------


class TestGetSession:
    def test_session_found(self):
        mock_session = MagicMock()
        _session_cache["123:us-east-1"] = mock_session
        assert _get_session("us-east-1") is mock_session

    def test_session_not_found(self):
        with pytest.raises(RuntimeError, match="No assumed session"):
            _get_session("ap-southeast-1")


class TestGetClient:
    def test_get_client(self):
        mock_session = MagicMock()
        mock_client = MagicMock()
        mock_session.client.return_value = mock_client
        _session_cache["123:us-east-1"] = mock_session

        result = _get_client("ec2", "us-east-1")
        assert result is mock_client
        mock_session.client.assert_called_with("ec2")


# ---------------------------------------------------------------------------
# _extract_items
# ---------------------------------------------------------------------------


class TestExtractItems:
    def test_simple_key(self):
        response = {"Instances": [1, 2, 3]}
        assert _extract_items(response, "Instances") == [1, 2, 3]

    def test_nested_key(self):
        response = {"Data": {"Items": ["a", "b"]}}
        assert _extract_items(response, "Data.Items") == ["a", "b"]

    def test_missing_key(self):
        response = {"Other": "value"}
        assert _extract_items(response, "Missing.Key") == []

    def test_non_list_result(self):
        response = {"Data": "not_a_list"}
        assert _extract_items(response, "Data") == []

    def test_non_dict_intermediate(self):
        response = {"Data": "string"}
        assert _extract_items(response, "Data.Nested") == []


# ---------------------------------------------------------------------------
# _format_ec2_instance
# ---------------------------------------------------------------------------


class TestFormatEc2Instance:
    def test_full_instance(self):
        instance = {
            "InstanceId": "i-123",
            "Tags": [{"Key": "Name", "Value": "web-server"}],
            "State": {"Name": "running"},
            "InstanceType": "t3.medium",
            "LaunchTime": "2025-01-01T00:00:00",
            "PrivateIpAddress": "10.0.0.1",
            "PublicIpAddress": "54.1.2.3",
            "VpcId": "vpc-123",
            "SubnetId": "subnet-456",
        }
        result = _format_ec2_instance(instance, "us-east-1")
        assert result["resource_id"] == "i-123"
        assert result["resource_name"] == "web-server"
        assert result["status"] == "running"
        assert result["metadata"]["instance_type"] == "t3.medium"

    def test_no_name_tag(self):
        instance = {
            "InstanceId": "i-456",
            "Tags": [{"Key": "Env", "Value": "prod"}],
            "State": {"Name": "stopped"},
        }
        result = _format_ec2_instance(instance, "us-west-2")
        assert result["resource_name"] is None

    def test_no_tags(self):
        instance = {"InstanceId": "i-789", "State": {"Name": "terminated"}}
        result = _format_ec2_instance(instance, "eu-west-1")
        assert result["resource_name"] is None
        assert result["tags"] == {}


# ---------------------------------------------------------------------------
# _format_resource / _format_simple_resource
# ---------------------------------------------------------------------------


class TestFormatResource:
    def test_format_resource_basic(self):
        service_def = AWSServiceDef(
            name="Lambda",
            boto3_service="lambda",
            description="Lambda functions",
            list_method="list_functions",
            list_key="Functions",
            id_field="FunctionName",
            name_field="FunctionName",
            arn_field="FunctionArn",
            status_field="State",
        )
        item = {
            "FunctionName": "my-func",
            "FunctionArn": "arn:aws:lambda:us-east-1:123:function:my-func",
            "State": "Active",
            "Runtime": "python3.11",
            "Tags": {"env": "prod"},
        }
        result = _format_resource(item, service_def, "us-east-1")
        assert result["resource_id"] == "my-func"
        assert result["status"] == "Active"
        assert result["resource_arn"].startswith("arn:")

    def test_format_resource_no_optional_fields(self):
        service_def = AWSServiceDef(
            name="S3",
            boto3_service="s3",
            description="S3 buckets",
            list_method="list_buckets",
            list_key="Buckets",
            id_field="Name",
            name_field=None,
            arn_field=None,
            status_field=None,
        )
        item = {"Name": "my-bucket", "CreationDate": "2025-01-01"}
        result = _format_resource(item, service_def, "us-east-1")
        assert result["resource_id"] == "my-bucket"
        assert result["resource_name"] == "my-bucket"  # falls back to id
        assert result["resource_arn"] is None
        assert result["status"] == "unknown"

    def test_format_simple_resource_string(self):
        service_def = AWSServiceDef(
            name="ECS",
            boto3_service="ecs",
            description="ECS clusters",
            list_method="list_clusters",
            list_key="clusterArns",
            id_field="clusterArn",
            name_field=None,
            arn_field=None,
            status_field=None,
        )
        result = _format_simple_resource(
            "arn:aws:ecs:us-east-1:123:cluster/my-cluster",
            service_def,
            "us-east-1",
        )
        assert result["resource_id"] == "arn:aws:ecs:us-east-1:123:cluster/my-cluster"
        assert result["resource_name"] == "my-cluster"
        assert result["resource_arn"] == result["resource_id"]

    def test_format_simple_resource_no_slash(self):
        service_def = AWSServiceDef(
            name="EKS",
            boto3_service="eks",
            description="EKS clusters",
            list_method="list_clusters",
            list_key="clusters",
            id_field="",
            name_field=None,
            arn_field=None,
            status_field=None,
        )
        result = _format_simple_resource("my-cluster", service_def, "us-west-2")
        assert result["resource_name"] == "my-cluster"
        assert result["resource_arn"] is None


# ---------------------------------------------------------------------------
# _scan_service_generic
# ---------------------------------------------------------------------------


class TestScanServiceGeneric:
    def test_paginated_scan(self):
        service_def = AWSServiceDef(
            name="Lambda",
            boto3_service="lambda",
            description="Lambda functions",
            list_method="list_functions",
            list_key="Functions",
            id_field="FunctionName",
            name_field="FunctionName",
            arn_field="FunctionArn",
            status_field=None,
        )
        mock_client = MagicMock()
        mock_client.can_paginate.return_value = True
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [
            {"Functions": [{"FunctionName": "f1"}, {"FunctionName": "f2"}]},
            {"Functions": [{"FunctionName": "f3"}]},
        ]
        mock_client.get_paginator.return_value = mock_paginator

        with patch(
            "agenticops.tools.aws_tools._get_client", return_value=mock_client
        ):
            result = _scan_service_generic("Lambda", "us-east-1", service_def)
            assert len(result) == 3

    def test_non_paginated_scan(self):
        service_def = AWSServiceDef(
            name="S3",
            boto3_service="s3",
            description="S3 buckets",
            list_method="list_buckets",
            list_key="Buckets",
            id_field="Name",
            name_field=None,
            arn_field=None,
            status_field=None,
        )
        mock_client = MagicMock()
        mock_client.can_paginate.return_value = False
        mock_client.list_buckets.return_value = {
            "Buckets": [{"Name": "b1"}, {"Name": "b2"}]
        }

        with patch(
            "agenticops.tools.aws_tools._get_client", return_value=mock_client
        ):
            result = _scan_service_generic("S3", "us-east-1", service_def)
            assert len(result) == 2

    def test_client_error(self):
        from botocore.exceptions import ClientError

        service_def = AWSServiceDef(
            name="EC2",
            boto3_service="ec2",
            description="EC2 instances",
            list_method="describe_instances",
            list_key="Reservations",
            id_field="InstanceId",
            name_field=None,
            arn_field=None,
            status_field=None,
        )
        mock_client = MagicMock()
        mock_client.can_paginate.return_value = False
        mock_client.describe_instances.side_effect = ClientError(
            {"Error": {"Code": "UnauthorizedOperation", "Message": "denied"}},
            "DescribeInstances",
        )

        with patch(
            "agenticops.tools.aws_tools._get_client", return_value=mock_client
        ):
            with pytest.raises(RuntimeError, match="AWS error"):
                _scan_service_generic("EC2", "us-east-1", service_def)


# ---------------------------------------------------------------------------
# Tool functions (describe_ec2, list_lambda, etc.)
# ---------------------------------------------------------------------------


class TestDescribeEc2:
    def test_success(self):
        _session_cache["123:us-east-1"] = MagicMock()

        with patch(
            "agenticops.tools.aws_tools._scan_service_generic"
        ) as mock_scan:
            mock_scan.return_value = [
                {
                    "Instances": [
                        {
                            "InstanceId": "i-1",
                            "Tags": [{"Key": "Name", "Value": "web"}],
                            "State": {"Name": "running"},
                        }
                    ]
                }
            ]
            result = describe_ec2(region="us-east-1")
            data = json.loads(result)
            assert len(data) == 1
            assert data[0]["resource_id"] == "i-1"

    def test_error(self):
        with patch(
            "agenticops.tools.aws_tools._scan_service_generic",
            side_effect=RuntimeError("no session"),
        ):
            result = describe_ec2(region="us-east-1")
            assert "Error" in result


class TestListLambda:
    def test_success(self):
        _session_cache["123:us-east-1"] = MagicMock()

        with patch(
            "agenticops.tools.aws_tools._scan_service_generic"
        ) as mock_scan:
            mock_scan.return_value = [
                {
                    "FunctionName": "my-func",
                    "FunctionArn": "arn:aws:lambda:us-east-1:123:function:my-func",
                    "State": "Active",
                }
            ]
            result = list_lambda_functions(region="us-east-1")
            data = json.loads(result)
            assert len(data) == 1


class TestDescribeRds:
    def test_success(self):
        _session_cache["123:us-east-1"] = MagicMock()

        with patch(
            "agenticops.tools.aws_tools._scan_service_generic"
        ) as mock_scan:
            mock_scan.return_value = [
                {"DBInstanceIdentifier": "mydb", "DBInstanceStatus": "available"}
            ]
            result = describe_rds(region="us-east-1")
            data = json.loads(result)
            assert len(data) == 1


class TestListS3:
    def test_success(self):
        _session_cache["123:us-east-1"] = MagicMock()

        with patch(
            "agenticops.tools.aws_tools._scan_service_generic"
        ) as mock_scan:
            mock_scan.return_value = [{"Name": "my-bucket"}]
            result = list_s3_buckets(region="us-east-1")
            data = json.loads(result)
            assert len(data) == 1


class TestDescribeEcs:
    def test_success(self):
        _session_cache["123:us-east-1"] = MagicMock()

        with patch(
            "agenticops.tools.aws_tools._scan_service_generic"
        ) as mock_scan:
            mock_scan.return_value = [
                "arn:aws:ecs:us-east-1:123:cluster/prod"
            ]
            result = describe_ecs(region="us-east-1")
            data = json.loads(result)
            assert data[0]["resource_name"] == "prod"


class TestDescribeEks:
    def test_success(self):
        _session_cache["123:us-east-1"] = MagicMock()

        with patch(
            "agenticops.tools.aws_tools._scan_service_generic"
        ) as mock_scan:
            mock_scan.return_value = ["my-cluster"]
            result = describe_eks(region="us-east-1")
            data = json.loads(result)
            assert data[0]["resource_name"] == "my-cluster"


class TestListDynamodb:
    def test_success(self):
        _session_cache["123:us-east-1"] = MagicMock()

        with patch(
            "agenticops.tools.aws_tools._scan_service_generic"
        ) as mock_scan:
            mock_scan.return_value = ["users-table"]
            result = list_dynamodb(region="us-east-1")
            data = json.loads(result)
            assert len(data) == 1


class TestListSqs:
    def test_success(self):
        _session_cache["123:us-east-1"] = MagicMock()

        with patch(
            "agenticops.tools.aws_tools._scan_service_generic"
        ) as mock_scan:
            mock_scan.return_value = [
                "https://sqs.us-east-1.amazonaws.com/123/my-queue"
            ]
            result = list_sqs(region="us-east-1")
            data = json.loads(result)
            assert data[0]["resource_name"] == "my-queue"
            assert data[0]["status"] == "available"


class TestListSns:
    def test_success(self):
        _session_cache["123:us-east-1"] = MagicMock()

        with patch(
            "agenticops.tools.aws_tools._scan_service_generic"
        ) as mock_scan:
            mock_scan.return_value = [
                {"TopicArn": "arn:aws:sns:us-east-1:123:my-topic"}
            ]
            result = list_sns(region="us-east-1")
            data = json.loads(result)
            assert len(data) == 1
