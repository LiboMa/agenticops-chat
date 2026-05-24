"""Targeted tests for src/agenticops/scan/scanner.py — covering low-coverage paths."""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

from agenticops.scan.scanner import ScanResult, AWSScanner


# ---------------------------------------------------------------------------
# ScanResult dataclass
# ---------------------------------------------------------------------------

class TestScanResult:
    def test_success_when_no_error(self):
        r = ScanResult(account_id="123", region="us-east-1", service="EC2")
        assert r.success is True

    def test_success_false_when_error(self):
        r = ScanResult(account_id="123", region="us-east-1", service="EC2", error="boom")
        assert r.success is False

    def test_count_empty(self):
        r = ScanResult(account_id="123", region="us-east-1", service="EC2")
        assert r.count == 0

    def test_count_with_resources(self):
        r = ScanResult(account_id="123", region="us-east-1", service="EC2",
                       resources=[{"id": "1"}, {"id": "2"}])
        assert r.count == 2


# ---------------------------------------------------------------------------
# AWSScanner — init validation
# ---------------------------------------------------------------------------

class TestAWSScannerInit:
    def test_rejects_non_aws_provider(self):
        account = MagicMock()
        account.provider = "gcp"
        with pytest.raises(ValueError, match="only supports AWS"):
            AWSScanner(account)

    @patch("agenticops.providers.get_provider")
    def test_accepts_aws_provider(self, mock_get_provider):
        mock_provider = MagicMock()
        mock_get_provider.return_value = mock_provider
        account = MagicMock()
        account.provider = "aws"
        scanner = AWSScanner(account)
        assert scanner.account is account
        mock_provider.resolve_credentials.assert_called_once()


# ---------------------------------------------------------------------------
# Fixture: build scanner with mocked provider
# ---------------------------------------------------------------------------

@pytest.fixture
def scanner():
    with patch("agenticops.providers.get_provider") as mock_gp:
        mock_gp.return_value = MagicMock()
        account = MagicMock()
        account.provider = "aws"
        account.credentials = {"account_id": "111222333444"}
        account.regions = ["us-east-1"]
        account.id = 1
        s = AWSScanner(account)
    return s


# ---------------------------------------------------------------------------
# Helper methods
# ---------------------------------------------------------------------------

class TestExtractItems:
    def test_simple_key(self, scanner):
        resp = {"Instances": [{"id": "1"}]}
        assert scanner._extract_items(resp, "Instances") == [{"id": "1"}]

    def test_dot_notation(self, scanner):
        resp = {"DescribeResult": {"Items": [1, 2, 3]}}
        assert scanner._extract_items(resp, "DescribeResult.Items") == [1, 2, 3]

    def test_missing_key_returns_empty(self, scanner):
        assert scanner._extract_items({}, "Missing") == []

    def test_non_dict_in_path_returns_empty(self, scanner):
        resp = {"Level1": "not_a_dict"}
        assert scanner._extract_items(resp, "Level1.Level2") == []

    def test_non_list_result_returns_empty(self, scanner):
        resp = {"Key": "string_value"}
        assert scanner._extract_items(resp, "Key") == []


class TestNormalizeTags:
    def test_list_format(self):
        tags = [{"Key": "Name", "Value": "test"}, {"Key": "Env", "Value": "prod"}]
        assert AWSScanner._normalize_tags(tags) == {"Name": "test", "Env": "prod"}

    def test_dict_passthrough(self):
        assert AWSScanner._normalize_tags({"Name": "test"}) == {"Name": "test"}

    def test_invalid_type_returns_empty(self):
        assert AWSScanner._normalize_tags("invalid") == {}

    def test_list_with_missing_keys(self):
        tags = [{"Key": "Name", "Value": "ok"}, {"Nope": "bad"}]
        assert AWSScanner._normalize_tags(tags) == {"Name": "ok"}


class TestJsonSafe:
    def test_datetime_conversion(self):
        dt = datetime(2025, 1, 1, tzinfo=timezone.utc)
        assert AWSScanner._json_safe(dt) == "2025-01-01T00:00:00+00:00"

    def test_nested_dict(self):
        dt = datetime(2025, 1, 1, tzinfo=timezone.utc)
        result = AWSScanner._json_safe({"ts": dt, "n": 42})
        assert result == {"ts": "2025-01-01T00:00:00+00:00", "n": 42}

    def test_list(self):
        dt = datetime(2025, 1, 1, tzinfo=timezone.utc)
        assert AWSScanner._json_safe([dt, "hello"]) == ["2025-01-01T00:00:00+00:00", "hello"]

    def test_plain_value(self):
        assert AWSScanner._json_safe(42) == 42


class TestFormatEc2Instance:
    def test_basic_instance(self, scanner):
        instance = {
            "InstanceId": "i-12345",
            "InstanceType": "t3.micro",
            "LaunchTime": datetime(2025, 1, 1, tzinfo=timezone.utc),
            "PrivateIpAddress": "10.0.0.1",
            "PublicIpAddress": "1.2.3.4",
            "VpcId": "vpc-abc",
            "SubnetId": "subnet-def",
            "Placement": {"AvailabilityZone": "us-east-1a"},
            "State": {"Name": "running"},
            "Tags": [{"Key": "Name", "Value": "web-server"}],
        }
        result = scanner._format_ec2_instance(instance, "us-east-1")
        assert result["resource_id"] == "i-12345"
        assert result["resource_name"] == "web-server"
        assert result["status"] == "running"
        assert result["tags"] == {"Name": "web-server"}
        assert "111222333444" in result["resource_arn"]

    def test_instance_no_tags(self, scanner):
        instance = {"InstanceId": "i-99999", "State": {"Name": "stopped"}}
        result = scanner._format_ec2_instance(instance, "us-west-2")
        assert result["resource_name"] is None
        assert result["status"] == "stopped"


class TestFormatSimpleResource:
    def test_string_resource(self, scanner):
        svc = MagicMock(name_attr="EKS")
        svc.name = "EKS"
        result = scanner._format_simple_resource("my-cluster", svc, "us-east-1")
        assert result["resource_id"] == "my-cluster"
        assert result["resource_name"] == "my-cluster"

    def test_arn_resource(self, scanner):
        svc = MagicMock()
        svc.name = "ECS"
        arn = "arn:aws:ecs:us-east-1:123:cluster/my-cluster"
        result = scanner._format_simple_resource(arn, svc, "us-east-1")
        assert result["resource_arn"] == arn
        assert result["resource_name"] == "my-cluster"

    def test_non_string_resource(self, scanner):
        svc = MagicMock()
        svc.name = "DynamoDB"
        result = scanner._format_simple_resource(123, svc, "us-east-1")
        assert result["resource_id"] == "123"


class TestFormatSqsQueue:
    def test_basic_queue(self, scanner):
        url = "https://sqs.us-east-1.amazonaws.com/123/my-queue"
        result = scanner._format_sqs_queue(url, "us-east-1")
        assert result["resource_name"] == "my-queue"
        assert result["resource_type"] == "SQS"
        assert result["status"] == "available"


class TestFormatResource:
    def test_generic_resource_with_tags_name(self, scanner):
        svc = MagicMock()
        svc.name = "S3"
        svc.id_field = "BucketName"
        svc.name_field = "Tags"
        svc.arn_field = "BucketArn"
        svc.status_field = "Status.State"

        item = {
            "BucketName": "my-bucket",
            "BucketArn": "arn:aws:s3:::my-bucket",
            "Tags": [{"Key": "Name", "Value": "prod-bucket"}],
            "Status": {"State": "active"},
        }
        result = scanner._format_resource(item, svc, "us-east-1")
        assert result["resource_name"] == "prod-bucket"
        assert result["status"] == "active"

    def test_name_from_name_field(self, scanner):
        svc = MagicMock()
        svc.name = "RDS"
        svc.id_field = "DBInstanceIdentifier"
        svc.name_field = "DBInstanceIdentifier"
        svc.arn_field = None
        svc.status_field = "DBInstanceStatus"

        item = {"DBInstanceIdentifier": "mydb", "DBInstanceStatus": "available", "Tags": []}
        result = scanner._format_resource(item, svc, "us-east-1")
        assert result["resource_name"] == "mydb"
        assert result["status"] == "available"

    def test_no_name_field_uses_id(self, scanner):
        svc = MagicMock()
        svc.name = "Lambda"
        svc.id_field = "FunctionName"
        svc.name_field = None
        svc.arn_field = "FunctionArn"
        svc.status_field = None

        item = {"FunctionName": "my-func", "FunctionArn": "arn:aws:lambda:us-east-1:123:function:my-func", "Tags": []}
        result = scanner._format_resource(item, svc, "us-east-1")
        assert result["resource_name"] == "my-func"
        assert result["status"] == "unknown"

    def test_tags_name_fallback_to_id(self, scanner):
        svc = MagicMock()
        svc.name = "S3"
        svc.id_field = "BucketName"
        svc.name_field = "Tags"
        svc.arn_field = None
        svc.status_field = None

        item = {"BucketName": "bucket-123", "Tags": []}
        result = scanner._format_resource(item, svc, "us-east-1")
        assert result["resource_name"] == "bucket-123"

    def test_status_field_non_dict_in_path(self, scanner):
        svc = MagicMock()
        svc.name = "X"
        svc.id_field = "Id"
        svc.name_field = None
        svc.arn_field = None
        svc.status_field = "Deep.Nested.Status"

        item = {"Id": "x-1", "Deep": "not_a_dict", "Tags": []}
        result = scanner._format_resource(item, svc, "us-east-1")
        assert result["status"] == "unknown"


class TestExtractMetadata:
    def test_skips_common_and_large_fields(self, scanner):
        svc = MagicMock()
        svc.id_field = "Id"
        svc.name_field = "Name"
        svc.arn_field = "Arn"

        item = {
            "Id": "i-1", "Name": "test", "Arn": "arn:...",
            "Tags": [{"Key": "k", "Value": "v"}],
            "SmallField": "hello",
            "BigField": {"data": "x" * 2000},
        }
        meta = scanner._extract_metadata(item, svc)
        assert "SmallField" in meta
        assert "BigField" not in meta
        assert "Id" not in meta
        assert "Tags" not in meta


class TestProcessItems:
    def test_ec2_nested_reservations(self, scanner):
        svc = MagicMock()
        svc.name = "EC2"
        items = [{"Instances": [
            {"InstanceId": "i-1", "State": {"Name": "running"}},
            {"InstanceId": "i-2", "State": {"Name": "stopped"}},
        ]}]
        result = scanner._process_items(items, svc, "us-east-1")
        assert len(result) == 2

    def test_simple_services(self, scanner):
        svc = MagicMock()
        svc.name = "EKS"
        result = scanner._process_items(["cluster-a", "cluster-b"], svc, "us-east-1")
        assert len(result) == 2

    def test_sqs_queues(self, scanner):
        svc = MagicMock()
        svc.name = "SQS"
        result = scanner._process_items(["https://sqs.us-east-1.amazonaws.com/123/q1"], svc, "us-east-1")
        assert result[0]["resource_type"] == "SQS"

    def test_generic_service(self, scanner):
        svc = MagicMock()
        svc.name = "RDS"
        svc.id_field = "DBId"
        svc.name_field = "DBId"
        svc.arn_field = None
        svc.status_field = None
        result = scanner._process_items([{"DBId": "db-1", "Tags": []}], svc, "us-east-1")
        assert len(result) == 1


class TestScanService:
    def test_unknown_service(self, scanner):
        result = scanner.scan_service("nonexistent_service_xyz", "us-east-1")
        assert not result.success
        assert "Unknown service" in result.error

    @patch("agenticops.scan.scanner.AWS_SERVICES")
    def test_client_error_handling(self, mock_services, scanner):
        from botocore.exceptions import ClientError
        mock_svc = MagicMock()
        mock_services.get.return_value = mock_svc
        mock_svc.boto3_service = "ec2"

        scanner._get_client = MagicMock(return_value=MagicMock())
        scanner._list_resources = MagicMock(
            side_effect=ClientError(
                {"Error": {"Code": "AccessDenied", "Message": "forbidden"}},
                "DescribeInstances"
            )
        )
        result = scanner.scan_service("EC2", "us-east-1")
        assert not result.success
        assert "AccessDenied" in result.error

    @patch("agenticops.scan.scanner.AWS_SERVICES")
    def test_botocore_error_handling(self, mock_services, scanner):
        from botocore.exceptions import BotoCoreError
        mock_svc = MagicMock()
        mock_services.get.return_value = mock_svc
        mock_svc.boto3_service = "ec2"

        scanner._get_client = MagicMock(return_value=MagicMock())
        scanner._list_resources = MagicMock(side_effect=BotoCoreError())
        result = scanner.scan_service("EC2", "us-east-1")
        assert not result.success
        assert "BotoCore" in result.error

    @patch("agenticops.scan.scanner.AWS_SERVICES")
    def test_unexpected_error_handling(self, mock_services, scanner):
        mock_svc = MagicMock()
        mock_services.get.return_value = mock_svc
        mock_svc.boto3_service = "ec2"

        scanner._get_client = MagicMock(return_value=MagicMock())
        scanner._list_resources = MagicMock(side_effect=RuntimeError("oops"))
        result = scanner.scan_service("EC2", "us-east-1")
        assert not result.success
        assert "Unexpected" in result.error

    @patch("agenticops.scan.scanner.AWS_SERVICES")
    def test_successful_scan(self, mock_services, scanner):
        mock_svc = MagicMock()
        mock_services.get.return_value = mock_svc
        mock_svc.boto3_service = "s3"

        scanner._get_client = MagicMock(return_value=MagicMock())
        scanner._list_resources = MagicMock(return_value=[{"resource_id": "bucket-1"}])
        result = scanner.scan_service("S3", "us-east-1")
        assert result.success
        assert result.count == 1


class TestListResources:
    def test_paginated(self, scanner):
        svc = MagicMock()
        svc.list_method = "describe_instances"
        svc.list_key = "Reservations"

        client = MagicMock()
        client.can_paginate.return_value = True
        paginator = MagicMock()
        paginator.paginate.return_value = [
            {"Reservations": [{"id": "1"}]},
            {"Reservations": [{"id": "2"}]},
        ]
        client.get_paginator.return_value = paginator
        scanner._process_items = MagicMock(side_effect=lambda items, sd, r: items)
        result = scanner._list_resources(client, svc, "us-east-1")
        assert len(result) == 2

    def test_non_paginated(self, scanner):
        svc = MagicMock()
        svc.list_method = "list_buckets"
        svc.list_key = "Buckets"

        client = MagicMock()
        client.can_paginate.return_value = False
        client.list_buckets.return_value = {"Buckets": [{"Name": "b1"}]}
        scanner._process_items = MagicMock(side_effect=lambda items, sd, r: items)
        result = scanner._list_resources(client, svc, "us-east-1")
        assert len(result) == 1


class TestScanAllServices:
    @patch("agenticops.scan.scanner.AWS_SERVICES", {"EC2": "mock", "S3": "mock"})
    def test_scans_all_regions_and_services(self, scanner):
        scanner.scan_service = MagicMock(
            return_value=ScanResult(account_id="123", region="us-east-1", service="EC2",
                                    resources=[{"id": "1"}])
        )
        results = scanner.scan_all_services(regions=["us-east-1"], services=["EC2", "S3"])
        assert len(results) == 2

    @patch("agenticops.scan.scanner.AWS_SERVICES", {"EC2": "mock"})
    def test_uses_account_regions(self, scanner):
        scanner.account.regions = ["eu-west-1"]
        scanner.scan_service = MagicMock(
            return_value=ScanResult(account_id="123", region="eu-west-1", service="EC2")
        )
        results = scanner.scan_all_services(services=["EC2"])
        assert len(results) == 1
        scanner.scan_service.assert_called_with("EC2", "eu-west-1")

    @patch("agenticops.scan.scanner.AWS_SERVICES", {"EC2": "mock"})
    def test_error_results_included(self, scanner):
        scanner.scan_service = MagicMock(
            return_value=ScanResult(account_id="123", region="us-east-1",
                                    service="EC2", error="boom")
        )
        results = scanner.scan_all_services(regions=["us-east-1"], services=["EC2"])
        assert len(results) == 1
        assert not results[0].success
