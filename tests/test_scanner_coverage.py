"""Tests for src/agenticops/scan/scanner.py — targeting uncovered lines."""

import pytest
from unittest.mock import patch, MagicMock, PropertyMock
from datetime import datetime

from agenticops.scan.scanner import ScanResult, AWSScanner


# ---------------------------------------------------------------------------
# ScanResult dataclass
# ---------------------------------------------------------------------------

class TestScanResult:
    def test_success_property(self):
        r = ScanResult(account_id="123", region="us-east-1", service="EC2")
        assert r.success is True

    def test_failure_property(self):
        r = ScanResult(account_id="123", region="us-east-1", service="EC2", error="fail")
        assert r.success is False

    def test_count_property(self):
        r = ScanResult(
            account_id="123", region="us-east-1", service="EC2",
            resources=[{"id": "1"}, {"id": "2"}]
        )
        assert r.count == 2


# ---------------------------------------------------------------------------
# AWSScanner
# ---------------------------------------------------------------------------

class TestAWSScanner:
    def _make_account(self):
        account = MagicMock()
        account.account_id = "111222333444"
        account.role_arn = "arn:aws:iam::111222333444:role/ScanRole"
        account.external_id = "ext-123"
        account.regions = ["us-east-1"]
        account.id = 1
        return account

    @patch("agenticops.scan.scanner.boto3")
    def test_get_assumed_session(self, mock_boto3):
        account = self._make_account()
        scanner = AWSScanner(account)

        mock_sts = MagicMock()
        mock_boto3.client.return_value = mock_sts
        mock_sts.assume_role.return_value = {
            "Credentials": {
                "AccessKeyId": "AKID",
                "SecretAccessKey": "SECRET",
                "SessionToken": "TOKEN",
            }
        }
        mock_boto3.Session.return_value = MagicMock()

        session = scanner._get_assumed_session("us-east-1")
        mock_sts.assume_role.assert_called_once()
        call_kwargs = mock_sts.assume_role.call_args[1]
        assert call_kwargs["ExternalId"] == "ext-123"

    @patch("agenticops.scan.scanner.boto3")
    def test_get_assumed_session_cached(self, mock_boto3):
        account = self._make_account()
        scanner = AWSScanner(account)
        cached_session = MagicMock()
        scanner._session_cache["111222333444:us-east-1"] = cached_session

        result = scanner._get_assumed_session("us-east-1")
        assert result is cached_session
        mock_boto3.client.assert_not_called()

    @patch("agenticops.scan.scanner.boto3")
    def test_get_assumed_session_client_error(self, mock_boto3):
        from botocore.exceptions import ClientError
        account = self._make_account()
        scanner = AWSScanner(account)

        mock_sts = MagicMock()
        mock_boto3.client.return_value = mock_sts
        mock_sts.assume_role.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "denied"}}, "AssumeRole"
        )

        with pytest.raises(ClientError):
            scanner._get_assumed_session("us-east-1")

    def test_scan_service_unknown(self):
        account = self._make_account()
        scanner = AWSScanner(account)

        result = scanner.scan_service("UnknownService", "us-east-1")
        assert result.error == "Unknown service: UnknownService"
        assert result.success is False

    @patch.object(AWSScanner, "_get_client")
    @patch("agenticops.scan.scanner.AWS_SERVICES")
    def test_scan_service_client_error(self, mock_services, mock_get_client):
        from botocore.exceptions import ClientError
        account = self._make_account()
        scanner = AWSScanner(account)

        svc_def = MagicMock()
        svc_def.boto3_service = "ec2"
        mock_services.get.return_value = svc_def

        mock_get_client.side_effect = ClientError(
            {"Error": {"Code": "Throttling", "Message": "Rate exceeded"}}, "DescribeInstances"
        )

        result = scanner.scan_service("EC2", "us-east-1")
        assert "Throttling" in result.error

    @patch.object(AWSScanner, "_get_client")
    @patch("agenticops.scan.scanner.AWS_SERVICES")
    def test_scan_service_botocore_error(self, mock_services, mock_get_client):
        from botocore.exceptions import BotoCoreError
        account = self._make_account()
        scanner = AWSScanner(account)

        svc_def = MagicMock()
        svc_def.boto3_service = "ec2"
        mock_services.get.return_value = svc_def

        mock_get_client.side_effect = BotoCoreError()
        result = scanner.scan_service("EC2", "us-east-1")
        assert "BotoCore Error" in result.error

    @patch.object(AWSScanner, "_get_client")
    @patch("agenticops.scan.scanner.AWS_SERVICES")
    def test_scan_service_unexpected_error(self, mock_services, mock_get_client):
        account = self._make_account()
        scanner = AWSScanner(account)

        svc_def = MagicMock()
        svc_def.boto3_service = "ec2"
        mock_services.get.return_value = svc_def

        mock_get_client.side_effect = RuntimeError("unexpected")
        result = scanner.scan_service("EC2", "us-east-1")
        assert "Unexpected Error" in result.error

    def test_extract_items_dot_notation(self):
        account = self._make_account()
        scanner = AWSScanner(account)

        response = {"Reservations": [{"Instances": [{"id": "i-123"}]}]}
        items = scanner._extract_items(response, "Reservations")
        assert len(items) == 1

    def test_extract_items_nested(self):
        account = self._make_account()
        scanner = AWSScanner(account)

        response = {"Data": {"Items": [1, 2, 3]}}
        items = scanner._extract_items(response, "Data.Items")
        assert items == [1, 2, 3]

    def test_extract_items_missing_key(self):
        account = self._make_account()
        scanner = AWSScanner(account)
        items = scanner._extract_items({"foo": "bar"}, "Missing.Key")
        assert items == []

    def test_format_ec2_instance(self):
        account = self._make_account()
        scanner = AWSScanner(account)

        instance = {
            "InstanceId": "i-abc123",
            "InstanceType": "t3.micro",
            "State": {"Name": "running"},
            "LaunchTime": datetime(2025, 1, 1),
            "PrivateIpAddress": "10.0.0.1",
            "PublicIpAddress": "1.2.3.4",
            "VpcId": "vpc-123",
            "SubnetId": "subnet-456",
            "Placement": {"AvailabilityZone": "us-east-1a"},
            "Tags": [{"Key": "Name", "Value": "web-server"}],
        }

        result = scanner._format_ec2_instance(instance, "us-east-1")
        assert result["resource_id"] == "i-abc123"
        assert result["resource_name"] == "web-server"
        assert result["status"] == "running"
        assert result["metadata"]["instance_type"] == "t3.micro"

    def test_format_ec2_instance_no_name_tag(self):
        account = self._make_account()
        scanner = AWSScanner(account)

        instance = {
            "InstanceId": "i-xyz",
            "State": {"Name": "stopped"},
            "Tags": [{"Key": "Env", "Value": "prod"}],
            "Placement": {},
        }

        result = scanner._format_ec2_instance(instance, "us-west-2")
        assert result["resource_name"] is None

    def test_format_simple_resource_string(self):
        account = self._make_account()
        scanner = AWSScanner(account)

        svc_def = MagicMock()
        svc_def.name = "EKS"

        result = scanner._format_simple_resource("arn:aws:eks:us-east-1:123:cluster/my-cluster", svc_def, "us-east-1")
        assert result["resource_arn"] == "arn:aws:eks:us-east-1:123:cluster/my-cluster"
        assert result["resource_name"] == "my-cluster"

    def test_format_simple_resource_no_slash(self):
        account = self._make_account()
        scanner = AWSScanner(account)
        svc_def = MagicMock()
        svc_def.name = "DynamoDB"

        result = scanner._format_simple_resource("my-table", svc_def, "us-east-1")
        assert result["resource_name"] == "my-table"
        assert result["resource_arn"] is None

    def test_format_sqs_queue(self):
        account = self._make_account()
        scanner = AWSScanner(account)

        result = scanner._format_sqs_queue("https://sqs.us-east-1.amazonaws.com/123/my-queue", "us-east-1")
        assert result["resource_name"] == "my-queue"
        assert result["status"] == "available"

    def test_format_resource_with_status_field(self):
        account = self._make_account()
        scanner = AWSScanner(account)

        svc_def = MagicMock()
        svc_def.name = "RDS"
        svc_def.id_field = "DBInstanceIdentifier"
        svc_def.name_field = "DBInstanceIdentifier"
        svc_def.arn_field = "DBInstanceArn"
        svc_def.status_field = "DBInstanceStatus"

        item = {
            "DBInstanceIdentifier": "mydb",
            "DBInstanceArn": "arn:aws:rds:us-east-1:123:db:mydb",
            "DBInstanceStatus": "available",
            "Engine": "postgres",
            "Tags": {},
        }

        result = scanner._format_resource(item, svc_def, "us-east-1")
        assert result["status"] == "available"
        assert result["resource_id"] == "mydb"

    def test_format_resource_nested_status(self):
        account = self._make_account()
        scanner = AWSScanner(account)

        svc_def = MagicMock()
        svc_def.name = "Lambda"
        svc_def.id_field = "FunctionName"
        svc_def.name_field = "FunctionName"
        svc_def.arn_field = "FunctionArn"
        svc_def.status_field = "State.Value"

        item = {
            "FunctionName": "my-func",
            "FunctionArn": "arn:aws:lambda:us-east-1:123:function:my-func",
            "State": {"Value": "Active"},
            "Tags": {},
        }

        result = scanner._format_resource(item, svc_def, "us-east-1")
        assert result["status"] == "Active"

    @patch.object(AWSScanner, "scan_service")
    def test_scan_all_services(self, mock_scan):
        account = self._make_account()
        scanner = AWSScanner(account)

        mock_scan.return_value = ScanResult(
            account_id="111222333444", region="us-east-1", service="EC2",
            resources=[{"resource_id": "i-123"}]
        )

        with patch("agenticops.scan.scanner.AWS_SERVICES", {"EC2": MagicMock(), "S3": MagicMock()}):
            results = scanner.scan_all_services(regions=["us-east-1"], services=["EC2", "S3"])
            assert len(results) == 2

    def test_process_items_ec2(self):
        account = self._make_account()
        scanner = AWSScanner(account)
        svc_def = MagicMock()
        svc_def.name = "EC2"

        items = [{"Instances": [{"InstanceId": "i-1", "State": {"Name": "running"}, "Tags": [], "Placement": {}}]}]
        result = scanner._process_items(items, svc_def, "us-east-1")
        assert len(result) == 1
        assert result[0]["resource_id"] == "i-1"

    def test_process_items_sqs(self):
        account = self._make_account()
        scanner = AWSScanner(account)
        svc_def = MagicMock()
        svc_def.name = "SQS"

        items = ["https://sqs.us-east-1.amazonaws.com/123/queue1"]
        result = scanner._process_items(items, svc_def, "us-east-1")
        assert result[0]["resource_name"] == "queue1"

    def test_process_items_eks(self):
        account = self._make_account()
        scanner = AWSScanner(account)
        svc_def = MagicMock()
        svc_def.name = "EKS"

        items = ["arn:aws:eks:us-east-1:123:cluster/prod"]
        result = scanner._process_items(items, svc_def, "us-east-1")
        assert result[0]["resource_name"] == "prod"

    def test_extract_metadata_skips_large(self):
        account = self._make_account()
        scanner = AWSScanner(account)
        svc_def = MagicMock()
        svc_def.id_field = "Id"
        svc_def.name_field = "Name"
        svc_def.arn_field = "Arn"

        item = {
            "Id": "x",
            "Name": "y",
            "Arn": "z",
            "Tags": {"a": "b"},
            "Small": "value",
            "Large": {"nested": "x" * 2000},
            "Created": datetime(2025, 6, 1),
        }

        meta = scanner._extract_metadata(item, svc_def)
        assert "Small" in meta
        assert "Large" not in meta
        assert meta["Created"] == "2025-06-01T00:00:00"
        assert "Tags" not in meta
