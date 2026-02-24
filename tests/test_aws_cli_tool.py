"""Tests for aws_cli_tool — _classify_command, run_aws_cli, run_aws_cli_readonly."""

from __future__ import annotations

import inspect
from unittest.mock import patch, MagicMock

import pytest

from agenticops.tools.aws_cli_tool import (
    _classify_command,
    run_aws_cli_readonly,
    run_aws_cli,
    MAX_OUTPUT_CHARS_READONLY,
    MAX_OUTPUT_CHARS,
)


# ── _classify_command tests ──────────────────────────────────────────


class TestClassifyCommand:
    """Test the _classify_command classifier."""

    # -- Original services (readonly) --

    @pytest.mark.parametrize("cmd", [
        "aws ec2 describe-instances --region us-east-1",
        "aws rds describe-db-instances",
        "aws lambda list-functions",
        "aws s3 ls",
        "aws cloudwatch get-metric-data --region us-east-1",
        "aws logs filter-log-events --log-group-name /test",
        "aws iam list-roles",
        "aws sts get-caller-identity",
    ])
    def test_original_readonly(self, cmd):
        assert _classify_command(cmd) == "readonly"

    # -- New services (readonly) --

    @pytest.mark.parametrize("cmd", [
        "aws elasticache describe-cache-clusters --region us-east-1",
        "aws elasticache list-tags-for-resource --resource-name arn:aws:...",
        "aws redshift describe-clusters",
        "aws redshift list-tags",
        "aws stepfunctions list-state-machines",
        "aws stepfunctions describe-execution --execution-arn arn:...",
        "aws stepfunctions get-execution-history --execution-arn arn:...",
        "aws apigateway get-rest-apis",
        "aws apigatewayv2 get-apis",
        "aws kinesis describe-stream --stream-name test",
        "aws kinesis list-streams",
        "aws firehose describe-delivery-stream --delivery-stream-name test",
        "aws firehose list-delivery-streams",
        "aws opensearch describe-domains",
        "aws opensearch list-domain-names",
        "aws acm describe-certificate --certificate-arn arn:...",
        "aws acm list-certificates",
        "aws kms describe-key --key-id alias/test",
        "aws kms list-keys",
        "aws secretsmanager list-secrets",
        "aws secretsmanager get-secret-value --secret-id test",
        "aws ecr describe-repositories",
        "aws ecr list-images --repository-name test",
        "aws codepipeline list-pipelines",
        "aws codepipeline get-pipeline --name test",
        "aws codebuild list-projects",
        "aws codebuild batch-get-projects --names test",
        "aws codecommit list-repositories",
        "aws guardduty list-detectors",
        "aws guardduty get-detector --detector-id abc123",
        "aws inspector2 list-findings",
        "aws securityhub get-findings",
        "aws securityhub describe-hub",
        "aws service-quotas list-services",
        "aws service-quotas get-service-quota --service-code ec2 --quota-code L-123",
        "aws health describe-events",
        "aws support describe-trusted-advisor-checks --language en",
        "aws ce get-cost-and-usage --time-period Start=2025-01-01,End=2025-02-01",
        "aws organizations describe-organization",
        "aws organizations list-accounts",
        "aws resourcegroupstaggingapi get-resources",
        "aws backup list-backup-plans",
        "aws backup describe-backup-vault --backup-vault-name test",
        "aws glue get-databases",
        "aws glue list-crawlers",
        "aws athena list-work-groups",
        "aws athena get-query-execution --query-execution-id abc",
        "aws emr describe-cluster --cluster-id j-123",
        "aws emr list-clusters",
    ])
    def test_new_services_readonly(self, cmd):
        assert _classify_command(cmd) == "readonly"

    # -- Write commands --

    @pytest.mark.parametrize("cmd", [
        "aws ec2 create-tags --resources i-123 --tags Key=Name,Value=test",
        "aws ec2 stop-instances --instance-ids i-123",
        "aws rds modify-db-instance --db-instance-identifier test",
        "aws lambda update-function-code --function-name test --zip-file fileb://test.zip",
        "aws s3 cp file.txt s3://bucket/",
        "aws s3 rm s3://bucket/file.txt",
        "aws autoscaling set-desired-capacity --auto-scaling-group-name test --desired-capacity 5",
    ])
    def test_write_commands(self, cmd):
        assert _classify_command(cmd) == "write"

    # -- Blocked commands --

    @pytest.mark.parametrize("cmd", [
        "aws iam create-user --user-name hacker",
        "aws iam delete-user --user-name victim",
        "aws iam create-access-key --user-name test",
        "aws iam attach-user-policy --user-name test --policy-arn arn:...",
        "aws ec2 terminate-instances --instance-ids i-123",
        "aws organizations create-account --email test@example.com",
        "aws organizations delete-organization",
        "aws organizations move-account --account-id 123 --source-parent-id r-abc --destination-parent-id ou-xyz",
        "aws organizations invite-account-to-organization --target Id=123,Type=ACCOUNT",
        "aws organizations leave-organization",
        "aws organizations remove-account-from-organization --account-id 123",
        "aws account close-account --account-id 123",
        "aws account delete-alternate-contact --account-id 123",
        "aws ec2 describe-instances --force",
    ])
    def test_blocked_commands(self, cmd):
        assert _classify_command(cmd) == "blocked"

    # -- Organizations read-only is now allowed --

    @pytest.mark.parametrize("cmd", [
        "aws organizations describe-organization",
        "aws organizations list-accounts",
    ])
    def test_organizations_readonly_allowed(self, cmd):
        assert _classify_command(cmd) == "readonly"

    # -- Unknown commands --

    @pytest.mark.parametrize("cmd", [
        "aws sagemaker something-custom",
        "aws custom-service do-thing",
    ])
    def test_unknown_commands(self, cmd):
        assert _classify_command(cmd) == "unknown"


# ── run_aws_cli_readonly tests ───────────────────────────────────────


class TestRunAwsCliReadonly:
    """Test the run_aws_cli_readonly tool."""

    def test_rejects_non_aws_command(self):
        result = run_aws_cli_readonly._tool_func(command="kubectl get pods")
        assert "Error" in result
        assert "must start with 'aws'" in result

    @pytest.mark.parametrize("cmd", [
        "aws ec2 describe-instances | cat",
        "aws ec2 describe-instances; rm -rf /",
        "aws ec2 describe-instances && echo hacked",
        "aws ec2 describe-instances $(whoami)",
        "aws ec2 describe-instances `whoami`",
        "aws ec2 describe-instances > /tmp/out",
        "aws ec2 describe-instances < /tmp/in",
    ])
    def test_rejects_shell_injection(self, cmd):
        result = run_aws_cli_readonly._tool_func(command=cmd)
        assert "Error" in result
        assert "Shell operators" in result

    @pytest.mark.parametrize("cmd", [
        "aws ec2 create-tags --resources i-123 --tags Key=Name,Value=test",
        "aws rds modify-db-instance --db-instance-identifier test",
        "aws s3 cp file.txt s3://bucket/",
    ])
    def test_rejects_write_commands(self, cmd):
        result = run_aws_cli_readonly._tool_func(command=cmd)
        assert "Error" in result
        assert "write" in result.lower()

    @pytest.mark.parametrize("cmd", [
        "aws iam create-user --user-name hacker",
        "aws ec2 terminate-instances --instance-ids i-123",
        "aws organizations create-account --email test@example.com",
    ])
    def test_rejects_blocked_commands(self, cmd):
        result = run_aws_cli_readonly._tool_func(command=cmd)
        assert "Error" in result
        assert "blocked" in result.lower()

    def test_rejects_unknown_commands(self):
        result = run_aws_cli_readonly._tool_func(command="aws sagemaker do-something")
        assert "Error" in result
        assert "unknown" in result.lower()

    @patch("agenticops.tools.aws_cli_tool.subprocess.run")
    def test_accepts_readonly_command(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='{"CacheClusters": []}',
            stderr="",
        )
        result = run_aws_cli_readonly._tool_func(
            command="aws elasticache describe-cache-clusters --region us-east-1"
        )
        assert "CacheClusters" in result
        mock_run.assert_called_once()
        # Verify --output json was appended
        call_args = mock_run.call_args[0][0]
        assert "--output" in call_args
        assert "json" in call_args

    @patch("agenticops.tools.aws_cli_tool.subprocess.run")
    def test_output_truncation_at_8000(self, mock_run):
        long_output = "x" * 10000
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=long_output,
            stderr="",
        )
        result = run_aws_cli_readonly._tool_func(
            command="aws ec2 describe-instances --region us-east-1"
        )
        assert len(result) < len(long_output)
        assert "truncated" in result

    def test_no_require_confirmation_parameter(self):
        """Verify run_aws_cli_readonly has no require_confirmation parameter."""
        sig = inspect.signature(run_aws_cli_readonly._tool_func)
        param_names = list(sig.parameters.keys())
        assert "require_confirmation" not in param_names

    @patch("agenticops.tools.aws_cli_tool.subprocess.run")
    def test_timeout_handling(self, mock_run):
        import subprocess as sp
        mock_run.side_effect = sp.TimeoutExpired(cmd="aws ...", timeout=30)
        result = run_aws_cli_readonly._tool_func(
            command="aws ec2 describe-instances --region us-east-1"
        )
        assert "timed out" in result.lower()

    @patch("agenticops.tools.aws_cli_tool.subprocess.run")
    def test_aws_cli_not_found(self, mock_run):
        mock_run.side_effect = FileNotFoundError()
        result = run_aws_cli_readonly._tool_func(
            command="aws ec2 describe-instances --region us-east-1"
        )
        assert "not found" in result.lower()

    @patch("agenticops.tools.aws_cli_tool.subprocess.run")
    def test_nonzero_exit_code(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=255,
            stdout="",
            stderr="An error occurred (AccessDenied)",
        )
        result = run_aws_cli_readonly._tool_func(
            command="aws ec2 describe-instances --region us-east-1"
        )
        assert "Error (exit code 255)" in result
        assert "AccessDenied" in result


# ── run_aws_cli tests (verify refactor didn't break) ────────────────


class TestRunAwsCli:
    """Smoke tests for the original run_aws_cli after refactoring."""

    def test_rejects_non_aws_command(self):
        result = run_aws_cli._tool_func(command="kubectl get pods")
        assert "Error" in result

    def test_blocks_dangerous_commands(self):
        result = run_aws_cli._tool_func(command="aws ec2 terminate-instances --instance-ids i-123")
        assert "blocked" in result.lower()

    def test_write_requires_confirmation(self):
        result = run_aws_cli._tool_func(command="aws ec2 create-tags --resources i-123 --tags Key=test,Value=v")
        assert "requires confirmation" in result.lower()

    def test_unknown_requires_confirmation(self):
        result = run_aws_cli._tool_func(command="aws sagemaker do-something")
        assert "requires confirmation" in result.lower()

    @patch("agenticops.tools.aws_cli_tool.subprocess.run")
    def test_readonly_executes_directly(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='{"Reservations": []}',
            stderr="",
        )
        result = run_aws_cli._tool_func(command="aws ec2 describe-instances --region us-east-1")
        assert "Reservations" in result

    @patch("agenticops.tools.aws_cli_tool.subprocess.run")
    def test_write_with_confirmation_executes(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='{"Tags": []}',
            stderr="",
        )
        result = run_aws_cli._tool_func(
            command="aws ec2 create-tags --resources i-123 --tags Key=test,Value=v",
            require_confirmation=True,
        )
        assert "Tags" in result
